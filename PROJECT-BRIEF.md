# kubernetes-learning — Project Brief & Architecture Handoff

> Handoff document for Claude Code. It captures every decision made while designing the project.
> Status labels: **DECIDED** = agreed by the team lead · **DEFAULT** = proposed and not objected to, confirm before relying on it · **OPEN** = not decided yet.
> "kubernetes-learning" is a placeholder name. The original working name was dropped.
>
> **This is the original brief.** Where it and [ARCHITECTURE.md](ARCHITECTURE.md) disagree (repo layout in §12, open questions answered since), ARCHITECTURE.md wins.
>
> **Hosting and the harness transport changed on 2026-11-04** ([ADR 0001](adr/0001-hosting-and-harness-transport.md)): the stack runs on a Hetzner box, sandboxes are Proxmox VMs on a PC at home, all machines (including the demo laptop) are joined by a WireGuard mesh, and the harness speaks WebSocket instead of vsock. Sections §1, §2, §4, §5, §10 and §14 below are marked where this applies; the original text is kept for history.

---

## 1. What it is

An AI-powered, interactive **Kubernetes learning platform**. A user asks an agent to explain or demonstrate a concept (rolling updates, service discovery, scheduling, a CrashLoopBackOff…). The agent builds and operates a **real, ephemeral Kubernetes cluster inside an isolated VM**: it deploys apps, configures nodes, deliberately breaks things and troubleshoots them. A **live visual interface** follows every action in real time, zooming into nodes, highlighting resources, revealing configs and showing how components interact. Users can also supply their **own public repository** and watch the agent build and deploy it into the cluster.

One-liner: *an AI tutor combined with a live Kubernetes lab, where every explanation is backed by real infrastructure you can see, poke and break.*

### Context
- University team project (generic team-project course). The deadline is far off, but the team wants to build ASAP. **DECIDED**
- **Demo/presentation only.** Not public, single-host deployment on one team member's PC. **DECIDED** *(Superseded by ADR 0001: still demo-only and not public, but split across a Hetzner box and a Proxmox box on a WireGuard mesh.)*

### Scope
- **Kubernetes only.** **DECIDED**
- **Non-goals:** Docker Swarm, CI/CD as a teaching topic, native mobile apps (a responsive web app covers phones). **DECIDED**
- Separate "provision a nested VM" CLI: **dropped**. Node management is agent tools backed by k3d. **DECIDED**
- Job/message queue: **none**. **DECIDED** (see §11)
- Local container registry / pull-through cache: **none**. **DECIDED** (see §10)

---

## 2. Architecture overview

> **Superseded in part by [ADR 0001](adr/0001-hosting-and-harness-transport.md):** web, api and Postgres run on a Hetzner box; envmgr and the sandbox VMs run on a Proxmox box at home; api reaches envmgr over a WireGuard mesh; the harness connects with WebSocket, not vsock. See [ARCHITECTURE §3](ARCHITECTURE.md#3-runtime-architecture) for the current diagram.

```
                      ┌──────────────────────────── Host machine (one team PC, Linux + KVM) ───────────────────────────┐
 ┌─────────┐  HTTPS   │  Docker Compose                                                                                 │
 │ Browser │─────────▶│  ┌───────┐                                                                                      │
 │         │  WS+pb   │  │  web  │ Next.js UI                                                                           │
 │         │─────────▶│  └───────┘                                                                                      │
 └─────────┘          │  ┌───────┐  gRPC (unix socket)  ┌────────────────────┐  vsock   ┌── Sandbox VM (per session) ──┐ │
                      │  │  api  │─────────────────────▶│ envmgr (systemd)   │◀────────▶│ harness (systemd, .NET AOT)  │ │
 ┌─────────┐  HTTPS   │  │ .NET  │                      │ VM lifecycle, pool │          │ Docker + k3d: cp, w1, w2     │ │
 │ LLM API │◀─────────│  └───┬───┘                      └────────────────────┘          │ images pre-loaded            │ │
 └─────────┘          │      │                                                          └──────────────────────────────┘ │
                      │  ┌───▼──────┐                                                                                     │
                      │  │ Postgres │ users, sessions, event log                                                          │
                      │  └──────────┘                                                                                     │
                      └─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Tech | Ships as | Runs where | Role |
|---|---|---|---|---|
| **web** | Next.js (React Flow for topology, xterm.js for terminal, Monaco for YAML) | Container image (GHCR) | Docker Compose on host | Topology canvas, chat, live terminal, config inspector, timeline/replay |
| **api** | ASP.NET Core | Container image (GHCR) | Docker Compose on host | Auth, sessions, **agent loop + tool definitions**, LLM calls, event fan-out, persistence |
| **envmgr** (environment manager) | .NET, self-contained binary | Binary (GitHub Releases) + systemd unit | Directly on host | VM lifecycle, warm pool, networking, egress rules, vsock bridge, TTL teardown |
| **harness** | .NET **Native AOT** single binary | Binary baked into VM base image | Inside every sandbox VM, started by systemd | Exec/PTY, file read/write, k8s + Docker watchers, fault injection |
| **VM base image** | Linux + Docker + k3d + kubectl + harness + pre-loaded images | Disk image (qcow2/raw rootfs) | Booted by envmgr | Fast, offline-capable sandbox |
| **PostgreSQL** | Official image | Off the shelf | Docker Compose on host | Users, sessions, **append-only event log** (enables replay) |

**DECIDED:** the services above, and that only `web` and `api` are container images we build.

---

## 3. Key design principles

1. **The agent's brain lives in the backend; the VM gets a thin executor.** **DECIDED**
   - The LLM loop runs in `api`. The harness only executes commands and observes.
   - API keys never enter the VM. This matters because user repo code runs there.
   - VMs can be killed or recreated without losing the conversation.
   - The backend owns the full event log, so replay comes for free.
2. **The view never trusts the narrator: two streams.** **DECIDED**
   - **State stream (ground truth).** The harness runs Kubernetes watches/informers (nodes, pods, deployments, replicasets, services, endpoints, events) plus Docker events. It sends a normalized topology graph snapshot, then diffs.
   - **Intent stream (camera directions).** The agent calls explicit tools (`focus`, `highlight`, `annotate`, `show_config`).
   - The UI renders the graph **only** from the state stream and moves the camera from the intent stream. If the agent forgets to report something, the UI is still correct. If the agent claims success while a pod is failing, the UI shows the failure, which becomes a teaching moment.
3. **Faults are first-class typed tools, not ad-hoc shell commands.** They are deterministic and reversible, and the UI knows exactly what was broken so it can mark it. **DECIDED**
4. **Platform-agnostic project.** The platform must run on any Linux host with `docker compose up` plus one systemd unit. No dependency on any specific PaaS. Configuration is environment variables only. **DECIDED**

---

## 4. Sandbox design

### Cluster topology
- **Containers as nodes:** k3d creates a 3-node k3s cluster (1 server `cp`, 2 agents `w1`, `w2`) inside the VM. **DECIDED**
  - Comes up in well under a minute and needs no nested virtualization.
  - Trade-off: "node failure" is simulated by stopping/pausing node containers. That's acceptable.
- The topology model must stay node-implementation-agnostic, so real VMs-as-nodes can slot in later as a stretch goal.

### Isolation

> **Superseded in part by [ADR 0001](adr/0001-hosting-and-harness-transport.md):** sandboxes are Proxmox VMs on an isolated bridge, and envmgr's harness WebSocket endpoint is the only address they can reach. There is no vsock. Proxmox runs the VMs, so the systemd-unit-per-VM scheme in *Lifecycle* below is no longer needed, though VMs still survive envmgr restarts. The *Local VMM* provider is now a Proxmox provider.

- **One VM per session**, destroyed at session end. **DECIDED**
- **No network path from VM to host services:** the harness talks to the host over **virtio-vsock**. **DECIDED** (Firecracker and Cloud Hypervisor support vsock; the VMM choice is **OPEN**.)
- **Keys stay outside the VM.** **DECIDED**
- **Nothing to pull at session start:** k3s system images and all lesson images are baked into the base image, so sandboxes need no internet to start. **DECIDED**
- Egress beyond that is restricted or none (exact allowlist **OPEN**; BYO repos need GitHub access for cloning, see §8).

### Lifecycle (envmgr)
- **Warm pool** of pre-booted VMs with the cluster already up, for near-instant sessions (**DEFAULT**). Snapshot/restore is an alternative.
- **TTL:** idle sessions expire after about 30 minutes (**DEFAULT**). One active environment per user (**DEFAULT**).
- **VMs must survive envmgr restarts.** systemd's default `KillMode=control-group` kills children on `systemctl restart`. So:
  - Launch each VM in its **own transient unit** (`systemd-run --unit=kl-vm-<id>` or the D-Bus equivalent).
  - On startup, envmgr **re-adopts** running VMs from a state directory (e.g. `/var/lib/kubernetes-learning`).

  **DECIDED**
- **Pluggable sandbox providers behind one gRPC contract.** envmgr exposes create / destroy / status / watch. **DECIDED**

| Provider | Isolation | Use |
|---|---|---|
| Local VMM (Firecracker / Cloud Hypervisor) | Full VM | Demo host / any Linux box with KVM |
| Docker (privileged DinD + k3d) | Container only | Teammates developing on macOS/Windows without KVM |
| KubeVirt | Full VM | Later, optional |

- **Pluggable harness transport.** The harness takes `--connect vsock://2:5000` or `--connect wss://<host>/harness`. vsock is for the VMM provider; WebSocket is for Docker/KubeVirt, where vsock isn't available. **DECIDED**

### Resources
- Each sandbox VM needs about **3–4 GB RAM** (Docker + k3s server + 2 agents + demo apps). CPU needs are light.
- 16 GB host → about 2–3 concurrent sessions; 32 GB → about 4–6.

---

## 5. Communication & protocols

> **Superseded in part by [ADR 0001](adr/0001-hosting-and-harness-transport.md):** api ↔ envmgr is gRPC over the WireGuard mesh (not a unix socket), and envmgr ↔ harness is WebSocket for every provider (not vsock). The relay recommendation below was adopted.

| Link | Transport | Notes |
|---|---|---|
| Browser ↔ web | HTTPS | UI |
| Browser ↔ api | **WebSocket carrying Protobuf** (protobuf-es on the TS side) | Live events, chat, terminal I/O, commands |
| api ↔ LLM | HTTPS | Only api talks to the LLM |
| api ↔ envmgr | **gRPC** over a Unix socket (e.g. `/run/kubernetes-learning/envmgr.sock`) | Sandbox lifecycle + harness channel |
| envmgr ↔ harness | **vsock** (or WebSocket per provider) | Protobuf frames |

- **One Protobuf schema** covers the whole system, harness to browser. **DECIDED**
- **OPEN (implementation choice):** how harness traffic reaches `api`.
  - Recommendation: envmgr relays the harness stream as a bidirectional gRPC stream per session. Then `api` has a single path regardless of provider, and the VM never needs a route to `api`.
  - Hide it behind an `IHarnessChannel` abstraction in `api`.

### Suggested Protobuf sketch (starting point, not final)

```proto
syntax = "proto3";
package kubernetes_learning.v1;

// ---- envmgr API ----
service EnvironmentManager {
  rpc CreateSandbox(CreateSandboxRequest) returns (Sandbox);
  rpc DestroySandbox(DestroySandboxRequest) returns (Empty);
  rpc GetSandbox(GetSandboxRequest) returns (Sandbox);
  rpc WatchSandbox(GetSandboxRequest) returns (stream SandboxStatus); // booting → cluster_ready → failed …
  rpc Connect(stream HarnessFrame) returns (stream HarnessFrame);     // relayed harness channel
}

// ---- harness channel ----
message HarnessFrame {
  string session_id = 1;
  uint64 seq = 2;
  oneof body {
    ExecRequest exec = 10;  ExecOutput exec_output = 11;  ExecExit exec_exit = 12;
    PtyOpen pty_open = 13;  PtyData pty_data = 14;        PtyResize pty_resize = 15;
    FileRead file_read = 16; FileWrite file_write = 17;   FileResult file_result = 18;
    FaultRequest fault = 19; FaultResult fault_result = 20;
    TopologySnapshot snapshot = 30; TopologyDiff diff = 31; ClusterEvent k8s_event = 32;
  }
}

// ---- topology model (state stream) ----
message TopologySnapshot { uint64 revision = 1; repeated Entity entities = 2; repeated Edge edges = 3; }
message TopologyDiff { uint64 from_revision = 1; uint64 to_revision = 2;
                       repeated Entity upserted = 3; repeated string removed_ids = 4;
                       repeated Edge edges_upserted = 5; repeated string edges_removed = 6; }
message Entity {
  string id = 1;          // e.g. "pod/default/web-7c9f-abc"
  string kind = 2;        // Node | Pod | Deployment | ReplicaSet | Service | Endpoint | Container
  string name = 3; string namespace = 4;
  string status = 5;      // Ready, Running, CrashLoopBackOff, ImagePullBackOff, NotReady…
  map<string,string> labels = 6;
  string parent_id = 7;   // pod → node, replicaset → deployment
  bytes raw = 8;          // optional YAML/JSON for the config inspector
}
message Edge { string id = 1; string from = 2; string to = 3; string type = 4; } // owns, selects, schedules-on, routes-to

// ---- intent stream (camera) — emitted by api from agent tool calls ----
message ViewIntent {
  oneof action {
    Focus focus = 1; Highlight highlight = 2; Annotate annotate = 3; ShowConfig show_config = 4; ClearView clear = 5;
  }
}
```

---

## 6. The agent

- The **agent loop runs in `api`**, with an LLM that supports tool use. **DECIDED** (architecture)
- **Provider: OPEN.**
- **Hard token cap per session.** **DEFAULT**

### Tools (typed; the agent does not get an unrestricted free-for-all)

| Category | Tools | Purpose |
|---|---|---|
| Execute | `exec`, `read_file`, `write_file`, `apply_manifest` | Do the work |
| Observe | `get_cluster_state`, `get_events`, `get_logs` | Stay grounded in real state |
| Direct the view | `focus(target)`, `highlight(targets)`, `annotate(target, text)`, `show_config(resource)` | Guide the user's eyes (intent stream) |
| Break things | `kill_node`, `delete_pod`, `partition(a, b)`, `bad_image`; candidates: `throttle_network`, `fill_disk`, `break_dns` | Teach by failure; deterministic and reversible |
| Hand over | `ask_user`, `pause_for_user` | Let the student drive |

Fault tools must record what they did so they can be **reverted** and so the UI can **mark the broken element**.

### User interaction model
- Shared live terminal, plus the ability to **pause** the agent, take over (run kubectl, edit YAML), then hand control back. **DEFAULT**
- **Per-session control lock:** exactly one driver (agent *or* user) at a time. Don't interleave commands from both; it makes lessons confusing.
- **Free-form chat plus curated lessons.** Curated lessons are the demo safety net. **DEFAULT**

### Example curated lesson: "Why did my rollout get stuck?"
1. User asks why a rollout hangs halfway.
2. Agent deploys `demo-web:v1` with 3 replicas; the view highlights the Deployment.
3. Agent rolls out `v2` with a mistyped image tag.
4. New pods hit `ImagePullBackOff`; the camera zooms in and opens their events.
5. Agent explains `maxUnavailable` / `maxSurge` and why v1 kept serving traffic, then rolls back.
6. Agent pauses; the user fixes the tag themselves in the terminal.

Lesson images (`demo-web:v1`, `v2`, plus a deliberately broken tag scenario) are tiny and baked into the VM image.

---

## 7. Frontend (web)

Main surfaces:
- **Topology canvas.** React Flow (or react-three-fiber for 3D) shows nodes, pods, services and traffic, rendered from the state stream. The camera is driven by intents; the user can also pan, zoom and click freely.
- **Chat panel** with streamed agent output.
- **Live terminal** (xterm.js) attached to the harness PTY. Read-only while the agent drives; writable when the user holds the control lock.
- **Config inspector** (Monaco) for YAML of the selected/agent-revealed resource.
- **Timeline/replay** from the Postgres event log.
- Responsive, so it's viewable on a phone.

---

## 8. Bring your own repo

- **Public repos only.** **DEFAULT**
- **Build:** use the repo's Dockerfile, with a Nixpacks/buildpacks fallback when there's none. **DEFAULT**
- **Build inside the VM**, then load the image into the cluster with `k3d image import`, or use a k3d-managed registry inside the VM. **The image never leaves the sandbox** and no registry credentials enter the VM. **DECIDED**

---

## 9. Users & auth

- Accounts plus one active environment per user with a ~30 min TTL. **DEFAULT** (e.g. GitHub OAuth)
- Since this is a private demo, the auth mechanism is **OPEN**. Keep auth behind an abstraction so it can be anything from a simple shared login to OIDC.

---

## 10. Build & ship

> **Superseded in part by [ADR 0001](adr/0001-hosting-and-harness-transport.md):** the VM base image is now a Proxmox VM template built by Packer. Compose runs on the Hetzner box, envmgr runs as a systemd unit on the Proxmox host, and the unit below no longer needs the `DeviceAllow` lines because Proxmox runs the VMs. Deploy files live in `platform/deploy/`, one folder per machine.

| Artifact | Published to |
|---|---|
| `web` image | GHCR |
| `api` image | GHCR |
| `envmgr` binary (+ `deploy/envmgr.service`) | GitHub Releases |
| `harness` binary (Native AOT, linux-x64; arm64 later if needed) | GitHub Releases + baked into VM image |
| VM base image | GitHub Releases (or built locally) |
| Lesson images | GHCR, then baked into the VM image at image-build time |

- **GHCR and GitHub Releases are only used at build time.** At runtime nothing pulls from the internet. **DECIDED**
- Deployment on the demo host:
  - `deploy/docker-compose.yml`: web, api, postgres.
  - `envmgr` as a systemd service.
  - **DECIDED**
- Images should be **built by CI** (GitHub Actions), not on the demo host.
- VM base image tooling: Packer or mkosi (**OPEN**).

### Example envmgr systemd unit

```ini
[Unit]
Description=kubernetes-learning environment manager
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/kubernetes-learning/envmgr/current/envmgr
EnvironmentFile=/etc/kubernetes-learning/envmgr.env
StateDirectory=kubernetes-learning
RuntimeDirectory=kubernetes-learning
Restart=on-failure
DeviceAllow=/dev/kvm rw
DeviceAllow=/dev/vhost-vsock rw
DeviceAllow=/dev/net/tun rw
ProtectHome=yes

[Install]
WantedBy=multi-user.target
```

Why envmgr is **not** a container:
- It needs `/dev/kvm`, `/dev/vhost-vsock` and `/dev/net/tun`.
- It creates bridges/taps and firewall rules on the host.
- It must spawn VMs that outlive its own restarts.

As a container it would need `--privileged` plus host networking anyway, which means all the packaging overhead and none of the isolation.

---

## 11. Rejected alternatives (don't reintroduce without discussion)

- **Job queue (Postgres SKIP LOCKED / NATS / RabbitMQ):** rejected. The live event stream is per-session, ordered and latency-sensitive, so it uses direct streaming. Provisioning is handled directly by envmgr.
- **Local registry / pull-through cache:** rejected in favour of pre-baking images into the VM base image and building BYO images inside the VM.
- **Nested VMs as cluster nodes:** rejected for the MVP (requires nested virtualization, slower). Containers-as-nodes via k3d instead.
- **Running sandboxes as k3d-in-pods on a shared cluster:** rejected. A lesson that kills nodes or fills disks must never touch real infrastructure.
- **Agent loop inside the VM:** rejected (keys in VM, state loss on VM death).
- **UI driven by agent narration only:** rejected (two-stream model instead).
- **Native mobile apps, Docker Swarm, CI/CD lessons:** out of scope.

---

## 12. Suggested repository layout (superseded: see ARCHITECTURE.md §2 and §7 for the multi-repo layout)

```
kubernetes-learning/
  proto/kubernetes_learning/v1/*.proto          # single source of truth for all messages
  src/
    KubernetesLearning.Contracts/              # generated C# from proto
    KubernetesLearning.Api/                    # ASP.NET Core: sessions, agent loop, tools, WS gateway, persistence
    KubernetesLearning.Agent/                  # (optional) agent loop + tool registry as a library used by Api
    KubernetesLearning.EnvManager/             # host daemon: providers (Vmm, Docker), warm pool, vsock relay
    KubernetesLearning.Harness/                # Native AOT: exec/PTY/files, k8s+docker watchers, faults
  web/                              # Next.js app (protobuf-es generated client)
  images/
    base/                           # Packer/mkosi definition for the VM base image
    lessons/                        # demo-web v1/v2 etc.
  lessons/                          # curated lesson definitions (scripts/prompts/expected states)
  deploy/
    docker-compose.yml
    envmgr.service
    envmgr.env.example
  docs/
```

Target **.NET 10** for all .NET projects (Native AOT for the harness; avoid reflection-heavy libraries there).

---

## 13. Roadmap (each milestone is demoable)

| Milestone | Scope |
|---|---|
| **M1 — Sandbox** | envmgr creates/destroys a VM (and the Docker provider for dev); base image with k3d; harness runs commands over vsock; 3-node cluster up |
| **M2 — Agent** | LLM loop in api, typed tools, chat UI with streamed output, terminal |
| **M3 — Live view** | Harness watchers → topology snapshot/diffs, React Flow canvas, intent tools (focus/highlight/annotate/show_config), YAML inspector |
| **M4 — Lessons** | Fault injection tools, curated lessons, BYO repo, control lock + pause/resume, session replay |

**Stretch:** real VMs as nodes, larger lesson library, shared sessions for pairs, KubeVirt provider.

---

## 14. Open questions

> **Answered since:** 1 (Proxmox VE on the home server PC), 2 (Proxmox's QEMU/KVM), 5 (envmgr relays over gRPC) and 6 (Packer, CALL), by [ADR 0001](adr/0001-hosting-and-harness-transport.md) and ARCHITECTURE.md. The current list is in [ARCHITECTURE §11](ARCHITECTURE.md#11-open-questions).

1. **Demo host OS:**
   - Linux on bare metal is preferred (KVM directly).
   - Windows/macOS hosts need a Linux "lab host" VM with nested virtualization, or else the Docker provider (weaker isolation, acceptable for a private demo).
   - The team PC may get an Ubuntu dual-boot, which would make bare-metal KVM possible.
2. **VMM:** Firecracker vs Cloud Hypervisor (both support vsock; Cloud Hypervisor is more flexible, Firecracker is leaner).
3. **LLM provider and per-session token budget.**
4. **Auth mechanism** (demo-only).
5. **Exact harness ↔ api relay design** (recommendation in §5).
6. **VM image tooling** (Packer vs mkosi).
7. **Egress policy** for BYO repo cloning (GitHub only?).
8. **Final project name** (kubernetes-learning is the placeholder; alternatives: Deckhand, Kubelab, Breakwater).

---

## 15. Notes for Claude Code

- Treat **DECIDED** items as constraints. Ask before changing them.
- Treat **DEFAULT** items as reasonable starting assumptions; flag them when they matter.
- Never resolve **OPEN** items silently.
- Start with **M1** and the proto contracts. The Docker provider lets everyone develop without KVM, so build it early alongside the VMM provider.
- Keep the project free of references to any specific hosting platform; config via environment variables only.
