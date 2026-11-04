# kubernetes-learning-platform

> **An AI tutor combined with a live Kubernetes lab**, where every explanation is backed by real infrastructure you can see, poke and break.

You ask the agent to explain or demonstrate a Kubernetes concept: rolling updates, scheduling, service discovery, a `CrashLoopBackOff`. The agent then builds and operates a **real, disposable 3-node cluster** in an isolated VM. It deploys apps, breaks things on purpose and troubleshoots them, while a **live visual interface** shows every change as it happens. You can take control at any point and fix things yourself.

University team project · demo-only · a Hetzner box + a Proxmox box at home on a WireGuard mesh · *"kubernetes-learning" is a placeholder name*

---

## 📚 Documentation

| Document | What's in it |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | **Start here.** Repos, services, controllers, contracts, key flows, per-repo folder trees, CI/CD, milestones, risks |
| [FEATURES.md](FEATURES.md) | Every feature, explained twice: what the user sees and how it works technically |
| [PROJECT-BRIEF.md](PROJECT-BRIEF.md) | The original brief: product intent, sandbox design, agent tools, rejected alternatives |
| [adr/](adr/) | Architecture decision records, one per decision. [0001](adr/0001-hosting-and-harness-transport.md): hosting over a WireGuard mesh, Proxmox sandboxes, WebSocket-only harness |

Decision labels used throughout: **DECIDED** (agreed) · **DEFAULT** (proposed, not objected to) · **OPEN** (not decided) · **CALL** (chosen during planning, change freely).

---

## 🗂️ Repositories

GitHub has no nested repos, so the organization is the container and **this repo is the parent** that links everything.

| Repo | Purpose | Owner | Status |
|---|---|---|---|
| **[docs](https://github.com/kubernetes-learning-platform/docs)** | This documentation hub | Filip (everyone contributes) | ✅ |
| **[contracts](https://github.com/kubernetes-learning-platform/contracts)** | Protobuf schema for the whole system → NuGet + npm packages | Filip | README only |
| **[sandbox](https://github.com/kubernetes-learning-platform/sandbox)** | `envmgr` (daemon on the Proxmox box), `harness` (in-VM agent), SandboxClient library, Proxmox VM template, lesson images | Filip | README only |
| **[api](https://github.com/kubernetes-learning-platform/api)** | ASP.NET Core backend + the Agent library + curated lessons | Person 2 (Agent + lessons: Filip) | README only |
| **[web](https://github.com/kubernetes-learning-platform/web)** | Next.js frontend: canvas, chat, terminal, inspector, replay | Person 3 | README only |
| **[platform](https://github.com/kubernetes-learning-platform/platform)** | Shared CI workflows, lint configs, infrastructure code, deploy files per machine, dev Compose | Filip | README only |

```mermaid
flowchart LR
    contracts["contracts<br/>proto + generated packages"]
    sandbox["sandbox<br/>envmgr, harness, VM image"]
    api["api<br/>backend + agent"]
    web["web<br/>Next.js"]
    platform["platform<br/>CI, lint, deploy"]

    contracts -->|NuGet| sandbox
    contracts -->|NuGet| api
    contracts -->|npm| web
    sandbox -->|"SandboxClient (NuGet)"| api
    platform -.->|"reusable CI + lint configs"| contracts & sandbox & api & web
```

---

## 🏗️ Architecture at a glance

```mermaid
flowchart LR
    laptop["Demo laptop<br/>browser"]
    llm["LLM API"]

    subgraph hetzner["Hetzner box · Docker Compose"]
        proxy["proxy<br/>Caddy"]
        web["web<br/>Next.js"]
        api["api<br/>ASP.NET Core + agent"]
        db[("Postgres<br/>users, sessions, event log")]
    end

    subgraph home["Proxmox box (home)"]
        envmgr["envmgr<br/>systemd on the host"]
        subgraph vm["Sandbox VM (one per session)"]
            harness["harness<br/>Native AOT"]
            k3d["k3d cluster<br/>cp, w1, w2"]
        end
    end

    laptop -->|"HTTPS over WireGuard"| proxy
    proxy --> web
    proxy -->|"REST + WebSocket (protobuf)"| api
    api --> db
    api -->|HTTPS| llm
    api -->|"gRPC over WireGuard"| envmgr
    harness -->|"WebSocket, isolated bridge"| envmgr
    harness -->|"kubectl, docker, watches"| k3d
```

**Three ideas shape everything:**

1. **The agent's brain lives in the backend; the VM gets a thin executor.** The LLM loop runs in `api`. The `harness` only executes commands and observes, so API keys never enter the VM, and a VM can die without losing the conversation.
2. **The view never trusts the narrator.** The canvas is drawn *only* from real cluster state (the harness watches Kubernetes). The agent can only move the camera (`focus`, `highlight`, `annotate`). If the agent says "done" while a pod is crashing, you see the crash.
3. **Faults are typed tools, not ad-hoc shell commands.** `kill_node`, `partition`, `bad_image` are recorded and reversible, so the UI knows exactly what was broken.

### Machines

All three are on one **WireGuard mesh**. Nothing is public: the app is only reachable over the mesh. Details in [ARCHITECTURE §3.1](ARCHITECTURE.md#31-machines-and-the-mesh) and [ADR 0001](adr/0001-hosting-and-harness-transport.md).

| Machine | Runs | Mesh address |
|---|---|---|
| **Hetzner box** | Docker Compose: Caddy, `web`, `api`, Postgres. The only peer with a public endpoint (WireGuard + SSH only). | `10.66.0.1` |
| **Proxmox box** (home) | Proxmox VE, `envmgr`, one sandbox VM per session on an isolated bridge | `10.66.0.2` |
| **Demo laptop** | The browser on the projector | `10.66.0.3` |

### Services

| Service | Tech | Runs | Entry points |
|---|---|---|---|
| **web** | Next.js (React Flow, xterm.js, Monaco) | Docker Compose on the Hetzner box | Routes: `/`, `/login`, `/session/[id]`, `/session/[id]/replay` |
| **api** | ASP.NET Core, .NET 10 | Docker Compose on the Hetzner box | **4 controllers**: `Auth`, `Sessions`, `Lessons`, `Events` · WebSocket `/ws/sessions/{id}` |
| **envmgr** | .NET 10 daemon | systemd on the Proxmox host | **1 gRPC service** on the mesh: `Create` / `Destroy` / `Get` / `List` / `Watch` sandbox + `Connect` relay · harness WebSocket on the sandbox bridge |
| **harness** | .NET 10 Native AOT | inside every sandbox VM | Frame router → `Exec`, `Pty`, `File`, `Fault` handlers + Kubernetes/Docker watchers |
| Postgres | off the shelf | Docker Compose on the Hetzner box | Users, sessions, append-only event log |
| Caddy | off the shelf | Docker Compose on the Hetzner box | `/` → web, `/api` + `/ws` → api, HTTPS on the mesh address only |

---

## 📁 Workspace folder structure

Clone every repo side by side into one local folder. Full per-repo trees are in [ARCHITECTURE.md §7](ARCHITECTURE.md#7-folder-structure).

```
kubernetes-learning/                          # local workspace
├── docs/                                     # ← this repo
├── contracts/
│   ├── proto/kubernetes_learning/v1/         # common, envmgr, harness, topology, view, session, rest
│   ├── dotnet/KubernetesLearning.Contracts/  # → NuGet
│   └── ts/                                   # → @kubernetes-learning-platform/contracts (npm)
├── sandbox/
│   ├── src/
│   │   ├── KubernetesLearning.EnvManager/    # VM lifecycle, warm pool, gRPC service, harness relay
│   │   ├── KubernetesLearning.Harness/       # exec, PTY, files, faults, watchers, topology, traffic probe
│   │   ├── KubernetesLearning.SandboxClient/ # → NuGet, used by api (+ a fake sandbox for dev)
│   │   └── KubernetesLearning.Sbx/           # dev CLI: create | exec | watch | destroy
│   ├── tests/
│   └── images/
│       ├── base/                             # Packer: Proxmox VM template (Linux + Docker + k3d + harness)
│       └── lessons/                          # demo-web v1/v2, traffic-probe
├── api/
│   ├── src/
│   │   ├── KubernetesLearning.Api/           # Controllers/, Realtime/, Sessions/, Auth/, Persistence/
│   │   └── KubernetesLearning.Agent/         # AgentRunner, tools, LLM client, lesson checkpoints
│   ├── lessons/                              # curated lesson YAML
│   └── tests/
├── web/
│   └── src/
│       ├── app/                              # routes
│       ├── components/                       # topology, chat, terminal, inspector, timeline, session
│       ├── lib/                              # REST + WebSocket (protobuf) clients
│       └── state/                            # topology / view / session reducers
└── platform/
    ├── .github/workflows/                    # reusable: dotnet-ci, node-ci, proto-ci, publish, release, vm-image
    ├── lint/                                 # canonical .editorconfig, analyzers, eslint, prettier
    ├── infra/                                # OpenTofu: hetzner/ (server, firewall), proxmox/ (bridge, pool, token)
    ├── deploy/                               # hetzner/ (compose, Caddyfile), proxmox/ (envmgr unit, nftables), wireguard/
    └── dev/                                  # local dev compose (Postgres + api with a fake sandbox)
```

---

## 🚀 Getting started

> Every repo exists, but the code repos only hold a README so far. Code lands in M1.

```bash
mkdir kubernetes-learning && cd kubernetes-learning
for repo in docs contracts sandbox api web platform; do
  git clone https://github.com/kubernetes-learning-platform/$repo.git
done
```

You'll need:
- .NET 10 SDK
- Node.js LTS
- Docker Desktop (give it ≥ 6 GB of memory for one local sandbox)
- A GitHub personal access token with `read:packages`, to install the `contracts` packages from GitHub Packages

Nobody needs KVM or Proxmox for day-to-day work. `envmgr` has a **Docker provider** for macOS/Windows, and `api` can run against a **fake sandbox** that plays a scripted cluster. To open the deployed app, ask Filip for a WireGuard peer config.

---

## 📏 Conventions

- **Commits:** strict [Conventional Commits](https://www.conventionalcommits.org/), one line, e.g. `feat: add warm pool`. No body, no co-author trailers.
- **PRs:** the title uses the same format. Every repo only allows squash merges, and the squash commit is the PR title, so `main` gets one clean line per change. A check fails any PR whose title doesn't follow the format.
- **Copilot:** every PR gets one Copilot review when it opens, except Markdown-only PRs and PRs labelled `skip-copilot`. It needs Copilot on your account, which is free through GitHub Student.
- **Branches:** `type/anything`, e.g. `feat/warm-pool` or `fix/harness-reconnect`, deleted after merging. For an issue, use its **Create a branch** button and rename the suggested branch to match.

More in [platform → Conventions](https://github.com/kubernetes-learning-platform/platform#-conventions).

---

## 👥 Team

| | Owns |
|---|---|
| **Filip** | Infra for every repo (CI, lint, releases, deploy), the machines and the mesh, `contracts`, `sandbox`, the Agent, curated lessons |
| **Person 2** | `api`: auth, sessions, WebSocket gateway, persistence, event log, control lock |
| **Person 3** | `web`: topology canvas, chat, terminal, config inspector, timeline/replay |

## 🛣️ Roadmap

| Milestone | Demoable result |
|---|---|
| **M1 Sandbox** | A 3-node cluster comes up in a Proxmox sandbox; commands run over the harness WebSocket; the UI renders a (fake) topology |
| **M2 Agent** | Chat with the agent; it runs typed tools; streamed answers; live terminal; the stack is deployed on the Hetzner box over the mesh |
| **M3 Live view** | Real topology from the cluster's watch streams, agent-driven camera, YAML inspector |
| **M4 Lessons** | Fault injection, lessons with checkpoints, traffic animation, take control / hand back, replay |

**Stretch:** bring-your-own repo, add/remove nodes, spectator mode, real VMs as nodes.

## 📄 License

[MIT](LICENSE)
