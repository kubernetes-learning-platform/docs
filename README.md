# kubernetes-learning-platform

> A live Kubernetes lab with an optional AI helper. Learners work on a real, disposable cluster and see every change as it happens.

University team project · demo only · hosted on a Hetzner box and a Proxmox box joined by a WireGuard mesh · "kubernetes-learning" is a placeholder name

---

## Overview

The platform gives each learner a real Kubernetes cluster to work on. A session provides:

- **A dedicated cluster.** A disposable 3-node cluster in its own virtual machine, with a terminal and unrestricted `kubectl` access. Nothing is simulated.
- **A live view.** A diagram of the cluster next to the terminal, updated as nodes, pods, services and ingresses change.
- **Scenarios.** Guided exercises, such as repairing a broken ingress, with automatic checks, optional hints and a reset.
- **An optional AI helper.** It explains and demonstrates on request, shows every command it runs, and asks how to continue. The rest of the platform works without it.

The virtual machine is deleted when the session ends.

---

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/system-map-dark.svg">
  <img src="assets/diagrams/system-map-light.svg" width="100%" alt="The whole system. A browser reaches the Caddy proxy on the Hetzner box, which serves web and forwards to api. api uses Postgres, RabbitMQ and an LLM API, and reaches envmgr on the Proxmox box over the WireGuard mesh. envmgr relays to the harness inside a sandbox VM, which drives a three-node k3d cluster.">
</picture>

A browser connects to the stack on the Hetzner box. The stack connects over the WireGuard mesh to the Proxmox box, which hosts one sandbox VM per session.

| Component | Responsibility |
|---|---|
| **web** | The browser application: cluster view, terminal, scenario panel and helper chat. It holds no business logic and reads all data from `api`. |
| **Caddy** | Reverse proxy. Serves one HTTPS origin and routes page requests to `web`, and API and WebSocket requests to `api`. |
| **api** | Backend. Handles authentication and sessions, runs scenarios and the optional helper, and records every session event in order. It does not run Kubernetes. |
| **Postgres** | Stores accounts, sessions, progress and the session event log used for replay. |
| **RabbitMQ** | Work queue for sandbox start and teardown requests. No other traffic uses it. |
| **envmgr** | Sandbox manager on the Proxmox host. Maintains a pool of ready VMs, assigns one per session, deletes it afterwards, and relays messages between `api` and the VM. |
| **harness** | Agent inside each VM. Executes commands, provides the terminal, runs scenario checks, and watches the cluster to report changes. |
| **k3d cluster** | The Kubernetes cluster: three nodes (`cp`, `w1`, `w2`) running as containers inside the VM. |

`web`, `api`, `envmgr` and `harness` are developed in this project. Postgres, RabbitMQ and Caddy are standard components.

### Design principles

1. **The learner is in control.** The terminal belongs to the learner by default, and scenarios and their checks do not require an LLM. The helper acts only on request, shows every command, and then asks how to continue.
2. **The helper's logic runs in the backend.** The LLM loop runs in `api`. The `harness` only executes commands and observes, so API keys never enter the VM, and a VM can be lost without losing the conversation.
3. **The view reflects actual cluster state.** The canvas is drawn only from what the harness observes in Kubernetes. The helper can move the camera (`focus`, `highlight`, `annotate`) but cannot change what is shown.
4. **Faults are typed operations.** `kill_node`, `partition` and `bad_image` are recorded and reversible, so the UI knows exactly what was broken.

### Machines

All three are on one **WireGuard mesh**. Nothing is public: the app is only reachable over the mesh. Details in [ARCHITECTURE §3.1](ARCHITECTURE.md#31-machines-and-the-mesh) and [ADR 0001](adr/0001-hosting-and-harness-transport.md).

| Machine | Runs | Mesh address |
|---|---|---|
| **Hetzner box** | Docker Compose: Caddy, `web`, `api`, Postgres, RabbitMQ. The only peer with a public endpoint (WireGuard + SSH only). | `10.66.0.1` |
| **Proxmox box** (home) | Proxmox VE, `envmgr`, one sandbox VM per session on an isolated bridge | `10.66.0.2` |
| **Demo laptop** | The browser on the projector | `10.66.0.3` |

### Services

| Service | Tech | Runs | Entry points |
|---|---|---|---|
| **web** | Next.js (React Flow, xterm.js, Monaco) | Docker Compose on the Hetzner box | Routes: `/`, `/login`, `/session/[id]`, `/session/[id]/replay` |
| **api** | ASP.NET Core, .NET 10 | Docker Compose on the Hetzner box | **4 controllers**: `Auth`, `Sessions`, `Scenarios`, `Events` · WebSocket `/ws/sessions/{id}` |
| **envmgr** | .NET 10 daemon | systemd on the Proxmox host | **1 gRPC service** on the mesh: `Create` / `Destroy` / `Get` / `List` / `Watch` sandbox + `Connect` relay · harness WebSocket on the sandbox bridge · consumes start and teardown requests from RabbitMQ |
| **harness** | .NET 10 Native AOT | inside every sandbox VM | Frame router → `Exec`, `Pty`, `File`, `Fault`, `Check` handlers + Kubernetes/Docker watchers |
| Postgres | off the shelf | Docker Compose on the Hetzner box | Users, sessions, progress, append-only event log |
| RabbitMQ | off the shelf | Docker Compose on the Hetzner box | Sandbox start and teardown requests only; live streams stay direct |
| Caddy | off the shelf | Docker Compose on the Hetzner box | `/` → web, `/api` + `/ws` → api, HTTPS on the mesh address only |

---

## Session startup

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/session-start-dark.svg">
  <img src="assets/diagrams/session-start-light.svg" width="100%" alt="Starting a session in eight steps, from the browser through api and the RabbitMQ work queue to envmgr and a sandbox VM, and back to the browser.">
</picture>

1. The browser requests a session. `api` creates it in the `queued` state.
2. `api` publishes a start request to the work queue.
3. `envmgr` consumes the request when capacity is available. Until then the request stays queued, and the learner sees their position.
4. `envmgr` assigns a VM from the warm pool, or clones a new one from the template.
5. `envmgr` publishes the result: the sandbox ID and its own address.
6. `api` opens a direct gRPC stream to `envmgr` for the session. The queue is not used after this point.
7. The harness sends a full snapshot of the cluster.
8. The browser marks the session as live and renders the snapshot.

Teardown uses the same queue, so a teardown request is not lost if the link between the two machines drops. See [ARCHITECTURE §6](ARCHITECTURE.md#6-key-flows), flows 1 and 11.

## State and intent streams

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/two-streams-dark.svg">
  <img src="assets/diagrams/two-streams-light.svg" width="100%" alt="A command travels from the terminal through api and envmgr to the harness, which runs it. The cluster changes, the harness sees the change through its watches, and a diff travels back through envmgr and api to the canvas. Separately, the helper can only move the camera.">
</picture>

1. The learner enters a command in the terminal.
2. `api` and `envmgr` forward it to the harness, which runs it in a shell inside the VM.
3. The cluster changes.
4. The harness observes the change through its Kubernetes watches.
5. The harness sends a diff back along the same path.
6. `api` assigns the message a sequence number, stores it, and sends it to the browser, which redraws the canvas.

The canvas is rendered only from this state stream. It does not use the command that was entered or anything the helper reports.

The helper uses a separate intent stream. It can focus, highlight and annotate elements on the canvas, but it cannot add or modify them.

Because each message is stored before it is sent, a reconnecting browser resumes from the last sequence number it received, and a finished session can be replayed exactly.

## Helper states

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/helper-turn-dark.svg">
  <img src="assets/diagrams/helper-turn-light.svg" width="100%" alt="The three states of the helper. Idle: the terminal is yours. Acting: the helper is working, the terminal is read-only and a Stop button is available. Waiting: the helper has asked a question and the terminal is yours again. If the token budget is spent, the helper switches off and the scenario carries on.">
</picture>

A helper turn starts only when the learner sends a message or answers a question.

| State | Terminal and inspector | Helper |
|---|---|---|
| **Idle** | Writable | Inactive |
| **Acting** | Read-only, with a **Stop** button | Runs tools. Its commands appear in the terminal as `agent$ …` |
| **Waiting** | Writable | Has asked a question and waits for the answer |

Each session has a token budget. When it is used up, the helper is disabled and reports this, and the scenario continues.

See [ARCHITECTURE §6.1](ARCHITECTURE.md#61-who-drives-decided-adr-0002) and [FEATURES §3–4](FEATURES.md#3-the-optional-ai-helper).

---

## Documentation

| Document | What's in it |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | The main reference. Repos, services, controllers, contracts, key flows, per-repo folder trees, CI/CD, milestones, risks |
| [FEATURES.md](FEATURES.md) | Every feature, explained twice: what the user sees and how it works technically |
| [PROJECT-BRIEF.md](PROJECT-BRIEF.md) | The original brief: product intent, sandbox design, agent tools, rejected alternatives |
| [adr/](adr/) | Architecture decision records, one per decision. [0001](adr/0001-hosting-and-harness-transport.md): hosting over a WireGuard mesh, Proxmox sandboxes, WebSocket-only harness. [0002](adr/0002-learner-driven-scenarios-and-scale-target.md): learner-driven scenarios, the optional helper, RabbitMQ, the 30-sandbox design target. [0003](adr/0003-course-vm-hosting.md): one course-provided VM runs the stack and the sandboxes |

The diagrams are generated by [`assets/diagrams/generate.py`](assets/diagrams/generate.py). To change one, edit its definition in that file and run the script.

Decision labels used throughout: **DECIDED** (agreed) · **DEFAULT** (proposed, not objected to) · **OPEN** (not decided) · **CALL** (chosen during planning, change freely).

---

## Repositories

GitHub has no nested repositories, so the organization groups them and this repository links to the others.

| Repo | Purpose | Owner | Status |
|---|---|---|---|
| **[docs](https://github.com/kubernetes-learning-platform/docs)** | This documentation hub | Filip (everyone contributes) | Current |
| **[contracts](https://github.com/kubernetes-learning-platform/contracts)** | Protobuf schema for the whole system → NuGet + npm packages | Filip | Documentation only |
| **[sandbox](https://github.com/kubernetes-learning-platform/sandbox)** | `envmgr` (daemon on the Proxmox box), `harness` (in-VM agent), SandboxClient library, Proxmox VM template, scenario images | Filip | Documentation only |
| **[api](https://github.com/kubernetes-learning-platform/api)** | ASP.NET Core backend + the Scenarios and Agent libraries | Person 2 (Scenarios + Agent: Filip) | Documentation only |
| **[web](https://github.com/kubernetes-learning-platform/web)** | Next.js frontend: canvas, scenarios, terminal, helper chat, inspector, replay | Person 3 | Documentation only |
| **[platform](https://github.com/kubernetes-learning-platform/platform)** | Shared CI workflows, lint configs, infrastructure code, deploy files per machine (including RabbitMQ), dev Compose | Filip | Documentation only |

A seventh repository, `scenarios`, will be created once the end-to-end flow works. Until then, the first scenario is kept in `api`.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/repos-dark.svg">
  <img src="assets/diagrams/repos-light.svg" width="100%" alt="The five code repositories. contracts publishes a NuGet and an npm package. sandbox and api install the NuGet package, web installs the npm package, and api also installs SandboxClient from sandbox. Every repo calls the CI workflows in platform.">
</picture>

An arrow means "installs a package from". `contracts` defines every message exchanged between the programs and publishes it as a NuGet package for the .NET repositories and an npm package for `web`. `api` also installs `SandboxClient` from `sandbox`. Each repository's CI calls reusable workflows in `platform`.

---

## Workspace layout

Clone the repositories side by side into one local folder. Full per-repo trees are in [ARCHITECTURE.md §7](ARCHITECTURE.md#7-folder-structure).

```
kubernetes-learning/                          # local workspace
├── docs/                                     # ← this repo
├── contracts/
│   ├── proto/kubernetes_learning/v1/         # common, envmgr, harness, topology, view, session, rest, jobs
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
│       └── scenarios/                        # demo-web v1/v2, traffic-probe
├── api/
│   ├── src/
│   │   ├── KubernetesLearning.Api/           # Controllers/, Realtime/, Sessions/, Provisioning/, Auth/, Persistence/
│   │   ├── KubernetesLearning.Scenarios/     # scenario catalog, runner and checks; no LLM dependency
│   │   └── KubernetesLearning.Agent/         # the optional helper: AgentRunner, tools, LLM client
│   ├── scenarios/                            # the first scenario, until the `scenarios` repo exists
│   └── tests/
├── web/
│   └── src/
│       ├── app/                              # routes
│       ├── components/                       # topology, scenario panel, chat, terminal, inspector, timeline
│       ├── lib/                              # REST + WebSocket (protobuf) clients
│       └── state/                            # topology / view / scenario / session state
└── platform/
    ├── .github/workflows/                    # reusable: dotnet-ci, node-ci, proto-ci, container-publish, release-binary, vm-image, pr-title, copilot-review
    ├── lint/                                 # canonical .editorconfig, analyzers, biome.json
    ├── infra/                                # OpenTofu: hetzner/ (server, firewall), proxmox/ (bridge, pool, token)
    ├── deploy/                               # hetzner/ (compose with RabbitMQ, Caddyfile), proxmox/ (envmgr unit, nftables), wireguard/
    └── dev/                                  # local dev compose (Postgres + api with a fake sandbox)
```

---

## Getting started

The code repositories currently contain documentation only. Implementation starts in milestone M1.

```bash
mkdir kubernetes-learning && cd kubernetes-learning
for repo in docs contracts sandbox api web platform; do
  git clone https://github.com/kubernetes-learning-platform/$repo.git
done
```

Requirements:
- .NET 10 SDK
- Node.js LTS
- Docker Desktop (give it ≥ 6 GB of memory for one local sandbox)
- A GitHub personal access token with `read:packages`, to install the `contracts` packages from GitHub Packages

KVM and Proxmox are not required for day-to-day development. `envmgr` has a **Docker provider** for macOS/Windows, and `api` can run against a **fake sandbox** that plays a scripted cluster. Access to the deployed application requires a WireGuard peer configuration from Filip.

---

## Conventions

- **Commits:** strict [Conventional Commits](https://www.conventionalcommits.org/), one line, e.g. `feat: add warm pool`. No body, no co-author trailers.
- **PRs:** the title uses the same format. Every repo only allows squash merges, and the squash commit is the PR title, so `main` gets one clean line per change. A check fails any PR whose title doesn't follow the format.
- **Copilot:** every PR gets one Copilot review when it opens, except Markdown-only PRs and PRs labelled `skip-copilot`. It needs Copilot on your account, which is free through GitHub Student.
- **Branches:** `type/anything`, e.g. `feat/warm-pool` or `fix/harness-reconnect`, deleted after merging. For an issue, use its **Create a branch** button and rename the suggested branch to match.

More in [platform → Conventions](https://github.com/kubernetes-learning-platform/platform#conventions).

---

## Team

| | Owns |
|---|---|
| **Filip** | Infra for every repo (CI, lint, releases, deploy), the machines and the mesh, `contracts`, `sandbox`, the Scenarios and Agent libraries, curated scenarios |
| **Person 2** | `api`: auth, sessions, WebSocket gateway, persistence, event log, queue integration, progress |
| **Person 3** | `web`: topology canvas, scenario panel, chat and question card, terminal, config inspector, timeline/replay |

## Roadmap

| Milestone | Demoable result |
|---|---|
| **M1 Sandbox** | A 3-node cluster comes up in a Proxmox sandbox; commands run over the harness WebSocket; the UI renders a (fake) topology |
| **M2 Scenarios** | One click starts a queued sandbox; a real terminal; the first scenario with checks and reset, no LLM needed; the stack is deployed on the Hetzner box over the mesh |
| **M3 Live view** | Real topology from the cluster's watch streams, including Ingress; YAML inspector |
| **M4 Helper** | The optional helper: typed tools, streamed answers, demonstrations with feedback questions, an agent-driven camera |
| **M5 Scenarios + scale** | The full 3–5 scenarios, the `scenarios` repo, a load test, timeline + replay, traffic animation |

The final demo is **by June 2027**. The design target is 30 concurrent sandboxes, and only what the demo needs gets provisioned.

**Stretch:** bring-your-own repo, add/remove nodes, spectator mode, real VMs as nodes.

## License

[MIT](LICENSE)
