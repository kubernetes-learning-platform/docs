# Features

Every feature of the platform: first **what the user sees**, then **how it works** under the hood. For the component-level design, see [ARCHITECTURE.md](ARCHITECTURE.md).

**In one sentence:** a web app whose backend runs an LLM agent. For each session the agent gets its own disposable VM running a real 3-node Kubernetes cluster, and every change in that cluster streams live into a graph on screen.

---

## 1. Your own real cluster per session
**What you see:** click "Start", and seconds later you have a working Kubernetes cluster with nodes `cp`, `w1`, `w2`.

**How it works:**
- **envmgr** is a host daemon that keeps 1–2 **microVMs** pre-booted (the "warm pool"). The VM software is Firecracker or Cloud Hypervisor, still OPEN.
- Inside each VM, **k3d** runs **k3s** (lightweight Kubernetes). Each "node" is a Docker container, so the cluster comes up in seconds instead of minutes.
- Every image the cluster needs is baked into the VM's disk image. Nothing is downloaded when a session starts.
- Each VM runs in its own systemd unit, so restarting envmgr doesn't kill running sessions.
- The VM is destroyed when the session ends or after ~30 minutes idle.

## 2. AI tutor chat
**What you see:** you ask "why would a rollout get stuck?" and the agent explains while actually doing things in the cluster.

**How it works:**
- The **agent loop** runs inside **api** (.NET). It sends your message to an LLM, which replies with text and/or **tool calls**.
- Tools are **typed functions** like `apply_manifest` or `get_logs`, not "run any shell command". Each call goes to the sandbox, and the result goes back to the LLM. This repeats until the turn is done.
- Text streams to the browser token by token (`ChatDelta`) over a WebSocket.
- A per-session **token budget** caps LLM cost.
- The LLM API key lives only in api and never enters the VM.

## 3. Live topology canvas
**What you see:** a graph of nodes, pods, deployments and services that updates itself live as pods start, crash or move.

**How it works:**
- The **harness**, a small program inside the VM, **watches** the Kubernetes API (nodes, pods, deployments, replicasets, services, endpoints, events) and Docker events.
- It keeps a normalized **graph model** of entities and edges ("owns", "runs on", "routes to"). It sends a full **snapshot** first, then only **diffs**, each with a revision number.
- Path: harness → **vsock** (a VM-to-host socket that doesn't use networking) → envmgr → gRPC stream → api → WebSocket → browser.
- **React Flow** draws it, and **elkjs** computes the layout.
- **Key principle:** the graph is drawn *only* from real cluster state, never from what the agent *says*. If the agent claims "it worked" while a pod is crashing, the screen shows the crash.

## 4. The agent directs your attention
**What you see:** the view zooms into a failing pod, highlights a deployment, or pins a note like "this is the old ReplicaSet".

**How it works:**
- The agent has **view tools**: `focus`, `highlight`, `annotate`, `show_config`. Each call produces a `ViewIntent` message.
- The frontend's view reducer turns intents into camera movement and highlights.
- This is the second of the **two streams**: the **state stream** decides *what exists*, and the **intent stream** decides *where you look*.

## 5. Live terminal
**What you see:** a real terminal into the cluster. It's read-only while the agent works, and you watch its commands scroll by as `agent$ kubectl …`.

**How it works:**
- **xterm.js** in the browser connects to a real bash in the VM through a **PTY** (pseudo-terminal) created by the harness.
- Keystrokes go up as `TerminalInput`, and output comes back as `TerminalOutput`, over the same pipe as everything else.
- The agent's commands run on a separate **exec channel**, so the LLM gets clean output and exit codes. They're mirrored into your terminal so you see everything.

## 6. Config inspector
**What you see:** click any resource to see its full YAML. While you have control, you can edit it and hit Apply.

**How it works:**
- **Monaco** (VS Code's editor) shows the raw manifest the harness attached to each graph entity.
- Apply sends `ApplyManifest{yaml}`, and the harness runs the equivalent of `kubectl apply`.
- The graph updates on its own through the watchers.

## 7. Breaking things on purpose
**What you see:** "let's kill a node" → the node goes red, its pods get rescheduled onto other nodes, and the broken node gets a badge.

**How it works:**
- **Fault tools** are typed, deterministic operations the harness performs:
  - `kill_node`: stops the node's Docker container
  - `delete_pod`: deletes a pod
  - `partition(a, b)`: firewall rules that drop traffic between two node containers
  - `bad_image`: sets an image tag that doesn't exist
- Every fault is recorded in a **fault ledger** with its undo action, so `revert_fault` can fix it and the UI knows exactly what was broken.
- The *effects* (node `NotReady`, pods moving) arrive through the normal watchers. It's real Kubernetes behaviour, not an animation.
- ⚠️ **Demo gotcha:** by default Kubernetes waits ~5 minutes before moving pods off a dead node. The cluster config should shorten these timeouts so rescheduling is visible in seconds.

## 8. Taking over from the agent
**What you see:** a "Take control" button. The agent pauses, your terminal and editor unlock, and you fix things yourself. When you hand back, the agent knows what you did.

**How it works:**
- A per-session **control lock** in api means exactly one driver at a time.
- `ControlTake` pauses the agent at its next tool boundary. While you drive you can still chat, but the agent can only *look and point*: no commands, no faults.
- On `ControlRelease`, api builds a **takeover summary** from the event log (the commands you typed and the cluster changes since you took over) and gives it to the agent.

## 9. Curated lessons with checkpoints
**What you see:** a lesson list ("Why did my rollout get stuck?") that runs in steps with a progress indicator.

**How it works:**
- Lessons are **YAML files**: a goal, extra instructions for the agent, and steps.
- Each step has a **checkpoint**, a condition on real cluster state like "deployment demo-web has 3 Running pods", which the checkpoint evaluator tests against the live graph.
- If the agent drifts and a checkpoint doesn't pass in time, the agent gets nudged: "expected X, the cluster shows Y".
- **Demo safety net:** a lesson can point to a recorded session. If the LLM is down on demo day, the presenter replays the recording.

## 10. Traffic visualization
**What you see:** during the stuck-rollout lesson, animated traffic on the Service → Pod edges shows that the old v1 pods are *still answering requests*.

**How it works:**
- The demo app (`demo-web`) replies with its own pod name.
- A **probe pod** in the cluster curls the service in a loop. The harness reads the probe's logs, counts hits per pod, and emits a `TrafficSample` about once a second.
- The canvas animates edges by hit count.
- This works for the lesson apps only. Real traffic tracing for any app would need a different network plugin (Cilium), which is out of scope.

## 11. Timeline & replay
**What you see:** a timeline you can scrub, and a replay mode that plays a past session back exactly as it happened.

**How it works:**
- Every message the server sends gets a **sequence number**. It's written to Postgres in an **append-only event log** *before* it's sent to the browser.
- Replay reads those same messages back and feeds them into the same frontend code. To the UI, replay is just a different source.
- The same log handles reconnects: a dropped browser sends `Resync{afterSeq}` and catches up.

## 12. Accounts & sessions
**What you see:** a login, and one active lab per person that cleans itself up when you walk away.

**How it works:**
- Auth sits behind an `IAuthProvider` interface. The mechanism is still OPEN, and a light one is enough for a presenter-driven demo.
- An idle reaper in api ends sessions after ~30 minutes, and envmgr has its own hard time limit as a backstop.

## 13. Isolation (invisible, but the reason the design looks like this)
- **One VM per session:** a lesson that kills nodes or fills a disk can't touch the host or other sessions.
- **No network route from the VM to host services.** The only way out is vsock to envmgr.
- **No secrets in the VM.** Keys stay in api.
- **MVP sandboxes are fully offline.**

---

## Not in the MVP (stretch goals)
- **Bring your own repo:** clone a public repo, build it inside the VM and deploy it. Needs internet egress from the VM and more RAM.
- Adding and removing nodes (`add_node` / `remove_node`).
- Spectator mode, so others can watch a session live.
- Real VMs as cluster nodes, KubeVirt provider.
