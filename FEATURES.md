# Features

Every feature of the platform: first **what the user sees**, then **how it works** under the hood. For the component-level design, see [ARCHITECTURE.md](ARCHITECTURE.md).

**In one sentence:** a web app that gives you, in one click, your own disposable VM running a real 3-node Kubernetes cluster and a real terminal. Every change in that cluster streams live into a graph on screen, and an optional AI helper can explain and demonstrate when you ask.

---

## 1. Your own real cluster, in one click
**What you see:** click "Start", and seconds later you have a working Kubernetes cluster with nodes `cp`, `w1`, `w2`. You start with a scenario or a blank cluster, and you have full `kubectl` freedom either way.

**How it works:**
- Sandboxes run on a **Proxmox** box at home. **envmgr**, a daemon on that box, keeps 1–2 **VMs** pre-booted (the "warm pool"). Each VM is a linked clone of one VM template, so making a new one takes seconds.
- Inside each VM, **k3d** runs **k3s** (lightweight Kubernetes). Each "node" is a Docker container, so the cluster comes up in seconds instead of minutes.
- Every image the cluster needs is baked into the VM template. Nothing is downloaded when a session starts.
- Proxmox runs the VMs, not envmgr, so restarting envmgr doesn't kill running sessions.
- The VM is destroyed when the session ends or after ~30 minutes idle.

## 2. Waiting in line when it's full
**What you see:** if every sandbox is in use, the app shows "queued, #3" instead of an error, and your lab opens when your turn comes.

**How it works:**
- `api` publishes a start request to **RabbitMQ**, and envmgr takes one only when it has room. A hard cap, `Sandbox__MaxConcurrent`, is set from the host's RAM.
- Failed starts are retried. After too many failures, the session is marked failed and you're told.
- Teardown requests use the same queue, so they survive a link drop.
- Requests are Protobuf messages, checked by buf like every other contract. `api` works out your position in line from its own records.
- Only start and teardown use the queue. Everything live streams directly.

## 3. The optional AI helper
**What you see:** a chat you can use or ignore. Ask "why is this pod stuck?" and it looks at your cluster and explains. Everything else works without it.

**How it works:**
- The **agent loop** runs inside **api** (.NET). It sends your message to an LLM, which replies with text and/or **tool calls**.
- Tools are **typed functions** like `apply_manifest` or `get_logs`, not "run any shell command". Each call goes to the sandbox, and the result goes back to the LLM. This repeats until the turn is done.
- A turn only ever starts from your message or answer, so the helper can't act on its own.
- Text streams to the browser token by token (`ChatDelta`) over a WebSocket.
- A per-session **token budget** caps LLM cost, and a global limit caps how many turns run at once. When the budget runs out, the helper turns off and says so, and your scenario carries on.
- The LLM API key lives only in api and never enters the VM.

## 4. "Show me, then ask me"
**What you see:** you ask, "Can you demonstrate the first part and explain it?" The helper does it, with every command visible and notes on the canvas. Then it stops and asks something like:

> Should I continue?
> **Yes** · **Wait, I have a question** · **No, do it again** · **No, I want to continue myself** · **No, reset it so I can try this part myself**

Nothing happens until you answer.

**How it works:**
- The helper writes the question and its options itself, using the `ask_user(question, options[])` tool. The turn suspends until your answer becomes the tool's result.
- `AgentQuestion` shows up as a question card, which always offers free text as well. A normal chat message sent while a question is open counts as the answer.
- If you answer "reset it", the helper calls `reset_step()`.
- While the helper is acting, your terminal and editor are read-only and a **Stop** button ends the turn at the next tool boundary. Otherwise they're yours, including while it waits for your answer.
- Each turn starts with what you typed and what changed in the cluster since the last turn, so the helper knows what you did.

## 5. Live topology canvas
**What you see:** a graph of nodes, pods, deployments, services and ingresses that updates itself live as pods start, crash or move, whether you or the helper made the change.

**How it works:**
- The **harness**, a small program inside the VM, **watches** the Kubernetes API (nodes, pods, deployments, replicasets, services, endpoints, ingresses, events) and Docker events. More kinds get added as scenarios need them.
- It keeps a normalized **graph model** of entities and edges ("owns", "runs on", "routes to"). It sends a full **snapshot** first, then only **diffs**, each with a revision number.
- Path: harness → **WebSocket** on an isolated network bridge → envmgr (on the Proxmox box) → gRPC stream over the **WireGuard mesh** → api (on the Hetzner box) → WebSocket → browser.
- If the home connection blips, the lab shows "reconnecting", and the graph reloads from a fresh snapshot once the link is back.
- **React Flow** draws it, and **elkjs** computes the layout.
- **Key principle:** the graph is drawn *only* from real cluster state, with the helper on or off, never from what the helper *says*. If it claims "it worked" while a pod is crashing, the screen shows the crash.

## 6. The helper directs your attention
**What you see:** the view zooms into a failing pod, highlights a deployment, or pins a note like "this is the old ReplicaSet".

**How it works:**
- The helper has **view tools**: `focus`, `highlight`, `annotate`, `show_config`. Each call produces a `ViewIntent` message.
- The frontend's view reducer turns intents into camera movement and highlights.
- This is the second of the **two streams**: the **state stream** decides *what exists*, and the **intent stream** decides *where you look*.

## 7. Live terminal
**What you see:** a real terminal into the cluster that's yours from the start. It's read-only only while the helper is acting, and you watch its commands scroll by as `agent$ kubectl …`.

**How it works:**
- **xterm.js** in the browser connects to a real bash in the VM through a **PTY** (pseudo-terminal) created by the harness.
- Keystrokes go up as `TerminalInput`, and output comes back as `TerminalOutput`, over the same pipe as everything else.
- The helper's commands run on a separate **exec channel**, so the LLM gets clean output and exit codes. They're mirrored into your terminal so you see everything.

## 8. Config inspector
**What you see:** click any resource to see its full YAML, edit it and hit Apply.

**How it works:**
- **Monaco** (VS Code's editor) shows the raw manifest the harness attached to each graph entity.
- Apply sends `ApplyManifest{yaml}`, and the harness runs the equivalent of `kubectl apply`.
- The graph updates on its own through the watchers.
- It's read-only while the helper is acting.

## 9. Breaking things on purpose
**What you see:** a scenario starts with something broken, or you ask the helper to "kill a node": the node goes red, its pods get rescheduled onto other nodes, and the broken node gets a badge.

**How it works:**
- **Fault tools** are typed, deterministic operations the harness performs. A scenario can inject them, and the helper can use them when you ask:
  - `kill_node`: stops the node's Docker container
  - `delete_pod`: deletes a pod
  - `partition(a, b)`: firewall rules that drop traffic between two node containers
  - `bad_image`: sets an image tag that doesn't exist
- Every fault is recorded in a **fault ledger** with its undo action, so `revert_fault` can fix it and the UI knows exactly what was broken.
- The *effects* (node `NotReady`, pods moving) arrive through the normal watchers. It's real Kubernetes behaviour, not an animation.
- ⚠️ **Demo gotcha:** by default Kubernetes waits ~5 minutes before moving pods off a dead node. The cluster config should shorten these timeouts so rescheduling is visible in seconds.

## 10. Scenarios
**What you see:** a list of 3–5 scenarios from simple to complex, such as "Fix a broken ingress", covering services, ingress, YAML and `kubectl`. Each one runs in steps with a goal, hints you can open, checks that turn green and a **Next** button. **Reset** takes you back to the start of the step, and **Start over** gives you a fresh VM.

**How it works:**
- A scenario is **one folder**: a `scenario.yaml` with its steps, plus manifests. All scenarios share one VM template, and `api` sends the files to the sandbox when it starts. Only a brand-new container image needs a template rebuild, so adding a scenario is usually just a folder and a PR. The format is in [ADR 0002](adr/0002-learner-driven-scenarios-and-scale-target.md).
- **Checks** run inside the VM through the harness, and test real behaviour with no LLM: a `resource` exists or has a value, an `http` request returns a status, or a `command` exits cleanly.
- A passed step shows **Next**, and nothing changes in the cluster until you click it.
- **Reset** reverts the step's faults, deletes the scenario's namespaces and re-applies the step's starting state.
- A step can include a **solution**, so CI can prove it's solvable, and notes telling the helper how to demonstrate it.
- **Demo safety net:** a scenario can point to a recorded session. If something fails on demo day, the presenter replays the recording.

## 11. Traffic visualization
**What you see:** in the stuck-rollout scenario, animated traffic on the Service → Pod edges shows that the old v1 pods are *still answering requests*.

**How it works:**
- The demo app (`demo-web`) replies with its own pod name.
- A **probe pod** in the cluster curls the service in a loop. The harness reads the probe's logs, counts hits per pod, and emits a `TrafficSample` about once a second.
- The canvas animates edges by hit count.
- This works for the scenario apps only. Real traffic tracing for any app would need a different network plugin (Cilium), which is out of scope.

## 12. Timeline & replay
**What you see:** a timeline you can scrub, and a replay mode that plays a past session back exactly as it happened.

**How it works:**
- Every message the server sends gets a **sequence number**. It's written to Postgres in an **append-only event log** *before* it's sent to the browser. Terminal output is batched first, so typing doesn't mean one database row per chunk.
- Replay reads those same messages back and feeds them into the same frontend code. To the UI, replay is just a different source.
- The same log handles reconnects: a dropped browser sends `Resync{afterSeq}` and catches up.
- The log lives on the Hetzner box, so replay works even when the Proxmox box at home is unreachable.

## 13. Accounts, sessions & progress
**What you see:** a login, a home screen showing what you've finished and what's next, and one active lab per person that cleans itself up when you walk away.

**How it works:**
- Auth sits behind an `IAuthProvider` interface. The mechanism is still OPEN, and a light one is enough: the app is only reachable over the WireGuard mesh.
- `scenario_progress` stores each account's status per scenario step. A step the helper demonstrated still counts, and a flag records that it did.
- An idle reaper in api ends sessions after ~30 minutes, and envmgr has its own hard time limit as a backstop.

## 14. Isolation (invisible, but the reason the design looks like this)
- **One VM per session:** a scenario that kills nodes or fills a disk can't touch the host or other sessions.
- **One way out of a sandbox.** The VM sits on an isolated bridge, and envmgr's harness endpoint is the only address it can reach: no internet, no home network, no mesh, no other sandboxes, no broker.
- **No secrets in the VM.** Keys stay in api. The VM only gets its own one-time token.
- **MVP sandboxes are fully offline.**
- **Nothing is public.** The whole app is only reachable over the WireGuard mesh.

## 15. Where it runs (invisible)
- **Hetzner box:** a small cloud server running `web`, `api`, Postgres, RabbitMQ and Caddy in Docker Compose.
- **Proxmox box:** a PC at home running Proxmox VE, envmgr and the sandbox VMs.
- **Demo laptop:** the browser on the projector.
- All three are joined by a **WireGuard mesh**. The Hetzner box is the only one with a public address; the other two connect out to it, so no port forwarding is needed. See [ADR 0001](adr/0001-hosting-and-harness-transport.md).

## 16. Built for 30 at once (invisible)
- The design target is **30 concurrent sandboxes**, though only what the demo needs gets provisioned. See [ADR 0002](adr/0002-learner-driven-scenarios-and-scale-target.md).
- The stack and the sandbox host are separate roles connected by addresses, so a second sandbox host would simply be a second consumer of the queue.
- RAM is the real limit, so real sandbox usage gets measured in M1. A load test in M5 runs 30 scripted sessions against the fake sandbox, plus as many real ones as the home PC holds.

---

## Not in the MVP (stretch goals)
- **Bring your own repo:** clone a public repo, build it inside the VM and deploy it. Needs internet egress from the VM and more RAM.
- Adding and removing nodes (`add_node` / `remove_node`).
- Spectator mode, so others can watch a session live.
- Real VMs as cluster nodes, KubeVirt provider.
