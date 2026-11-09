# kubernetes-learning-platform

> **A live Kubernetes lab with an optional AI helper**, where you learn by doing on real infrastructure you can see, poke and break.

University team project · demo-only · a Hetzner box + a Proxmox box at home on a WireGuard mesh · *"kubernetes-learning" is a placeholder name*

---

## 🧭 What this is

Kubernetes is hard to learn from slides, because the interesting part is what happens when something changes or breaks. This project gives every learner a real cluster of their own to change and break.

- **One click, one cluster.** You get a real, disposable 3-node Kubernetes cluster inside its own virtual machine, and a real terminal into it. Nothing is simulated, and `kubectl` works the way it does anywhere else.
- **You see what you do.** A live picture of the cluster sits next to the terminal. Start a deployment and its pods appear. Kill a node and you watch its pods move to another one.
- **Scenarios give you something to fix.** A scenario such as "the site returns 503, find out why" comes with checks that turn green when the cluster really works, hints you can open, and a reset.
- **A helper, if you want one.** An AI helper can explain what's going on or demonstrate a step. It only acts when you ask, shows every command it runs, and then asks you how to continue. Everything else works without it.

When you're done, the virtual machine is thrown away.

---

## 🏗️ The system in one picture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/system-map-dark.svg">
  <img src="assets/diagrams/system-map-light.svg" width="100%" alt="The whole system. A browser reaches the Caddy proxy on the Hetzner box, which serves web and forwards to api. api uses Postgres, RabbitMQ and an LLM API, and reaches envmgr on the Proxmox box over the WireGuard mesh. envmgr relays to the harness inside a sandbox VM, which drives a three-node k3d cluster.">
</picture>

Read it left to right. Your browser is on the left, and your cluster is on the far right, inside a sandbox VM. Everything in between exists to connect the two safely.

| Part | What it does, in plain words |
|---|---|
| **web** | The app you see in the browser: the picture of the cluster, the terminal, the scenario panel and the chat. It has no logic of its own and gets everything from `api`. |
| **Caddy** | The front door. It gives the browser one HTTPS address, and passes page requests to `web` and everything else to `api`. |
| **api** | The brain. It knows who you are and which session is yours, runs the scenarios and the optional helper, and records every event of a session in order. It never runs Kubernetes itself. |
| **Postgres** | The memory: accounts, sessions, progress, and the event log that makes replay possible. |
| **RabbitMQ** | The waiting line. Requests to start or delete a sandbox wait here until the sandbox host has room. Nothing else goes through it. |
| **envmgr** | The sandbox manager, on the machine that hosts the VMs. It keeps a few VMs booted and ready, hands one out per session, deletes it afterwards, and passes messages between `api` and the VM. |
| **harness** | A small program inside every VM. It runs commands, provides the terminal, checks scenario steps, and watches the cluster so it can report every change. |
| **k3d cluster** | The actual Kubernetes: three nodes (`cp`, `w1`, `w2`) that run as containers inside the VM. |

We write four of these: `web`, `api`, `envmgr` and `harness`. Postgres, RabbitMQ and Caddy are used off the shelf.

**Four ideas shape everything:**

1. **The learner drives.** The terminal is yours by default, and scenarios and their checks work with no LLM. The helper only acts when you ask, shows every command, and then asks you how to continue.
2. **The helper's brain lives in the backend; the VM gets a thin executor.** The LLM loop runs in `api`. The `harness` only executes commands and observes, so API keys never enter the VM, and a VM can die without losing the conversation.
3. **The view never trusts the narrator.** The canvas is drawn *only* from real cluster state (the harness watches Kubernetes). The helper can only move the camera (`focus`, `highlight`, `annotate`). If it says "done" while a pod is crashing, you see the crash.
4. **Faults are typed tools, not ad-hoc shell commands.** `kill_node`, `partition`, `bad_image` are recorded and reversible, so the UI knows exactly what was broken.

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

## ▶️ What happens when you click Start

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/session-start-dark.svg">
  <img src="assets/diagrams/session-start-light.svg" width="100%" alt="Starting a session in eight steps, from the browser through api and the RabbitMQ work queue to envmgr and a sandbox VM, and back to the browser.">
</picture>

1. The browser asks `api` for a session. `api` creates it in the `queued` state.
2. `api` puts a start request on the work queue.
3. `envmgr` takes the request as soon as it has room. If every sandbox is in use, the request waits, and you see your place in line.
4. `envmgr` hands over a VM that is already booted (the warm pool), or clones a new one from the template. This is why a start takes seconds.
5. `envmgr` answers through the queue: which sandbox, and where to reach it.
6. `api` opens a direct connection to `envmgr` for this session. From here on the queue is out of the picture.
7. The harness sends a full snapshot of the cluster.
8. The browser shows the session as live and draws the snapshot.

Ending a session goes through the same queue, so a teardown isn't lost if the link between the two machines drops. Details: [ARCHITECTURE §6](ARCHITECTURE.md#6-key-flows), flows 1 and 11.

## 🔁 How a change reaches the screen

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/two-streams-dark.svg">
  <img src="assets/diagrams/two-streams-light.svg" width="100%" alt="A command travels from the terminal through api and envmgr to the harness, which runs it. The cluster changes, the harness sees the change through its watches, and a diff travels back through envmgr and api to the canvas. Separately, the helper can only move the camera.">
</picture>

1. You type a command in the terminal.
2. It travels through `api` and `envmgr` to the harness, which runs it in a real shell in the VM.
3. The cluster changes: a pod starts, a node goes down.
4. The harness is watching the Kubernetes API, so it sees the change for itself.
5. It sends a small diff, such as "this pod is now crash-looping", back the way the command came.
6. `api` gives the message a number, saves it, and sends it to the browser, which redraws.

The picture of the cluster is drawn **only** from step 4, from what the cluster really is. It isn't drawn from the command you typed, and never from what the helper says.

The helper has a second, separate channel. It can move the camera: zoom in on a pod, highlight a deployment, pin a note. It can't add or change anything in the picture.

Because step 6 saves every message before sending it, a browser that drops off can catch up from the last number it saw, and a finished session can be replayed exactly as it happened.

## 🤝 The helper

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/helper-turn-dark.svg">
  <img src="assets/diagrams/helper-turn-light.svg" width="100%" alt="The three states of the helper. Idle: the terminal is yours. Acting: the helper is working, the terminal is read-only and a Stop button is available. Waiting: the helper has asked a question and the terminal is yours again. If the token budget is spent, the helper switches off and the scenario carries on.">
</picture>

The terminal is yours by default, and the helper does nothing until you send it a message.

- **Acting.** While it works, your terminal is read-only, its commands scroll by as `agent$ …`, and a **Stop** button ends its turn.
- **Waiting.** When it wants to know how to continue, it asks a question with options it wrote itself, hands the terminal back, and waits for your answer.
- **Off.** Each session has a token budget. When it runs out, the helper switches off and says so, and your scenario carries on.

Details: [ARCHITECTURE §6.1](ARCHITECTURE.md#61-who-drives-decided-adr-0002) and [FEATURES §3–4](FEATURES.md#3-the-optional-ai-helper).

---

## 📚 Documentation

| Document | What's in it |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | **Start here.** Repos, services, controllers, contracts, key flows, per-repo folder trees, CI/CD, milestones, risks |
| [FEATURES.md](FEATURES.md) | Every feature, explained twice: what the user sees and how it works technically |
| [PROJECT-BRIEF.md](PROJECT-BRIEF.md) | The original brief: product intent, sandbox design, agent tools, rejected alternatives |
| [adr/](adr/) | Architecture decision records, one per decision. [0001](adr/0001-hosting-and-harness-transport.md): hosting over a WireGuard mesh, Proxmox sandboxes, WebSocket-only harness. [0002](adr/0002-learner-driven-scenarios-and-scale-target.md): learner-driven scenarios, the optional helper, RabbitMQ, the 30-sandbox design target |

The pictures on this page are generated by [`assets/diagrams/generate.py`](assets/diagrams/generate.py). To change one, edit its definition in that file and run it again.

Decision labels used throughout: **DECIDED** (agreed) · **DEFAULT** (proposed, not objected to) · **OPEN** (not decided) · **CALL** (chosen during planning, change freely).

---

## 🗂️ Repositories

GitHub has no nested repos, so the organization is the container and **this repo is the parent** that links everything.

| Repo | Purpose | Owner | Status |
|---|---|---|---|
| **[docs](https://github.com/kubernetes-learning-platform/docs)** | This documentation hub | Filip (everyone contributes) | ✅ |
| **[contracts](https://github.com/kubernetes-learning-platform/contracts)** | Protobuf schema for the whole system → NuGet + npm packages | Filip | README only |
| **[sandbox](https://github.com/kubernetes-learning-platform/sandbox)** | `envmgr` (daemon on the Proxmox box), `harness` (in-VM agent), SandboxClient library, Proxmox VM template, scenario images | Filip | README only |
| **[api](https://github.com/kubernetes-learning-platform/api)** | ASP.NET Core backend + the Scenarios and Agent libraries | Person 2 (Scenarios + Agent: Filip) | README only |
| **[web](https://github.com/kubernetes-learning-platform/web)** | Next.js frontend: canvas, scenarios, terminal, helper chat, inspector, replay | Person 3 | README only |
| **[platform](https://github.com/kubernetes-learning-platform/platform)** | Shared CI workflows, lint configs, infrastructure code, deploy files per machine (including RabbitMQ), dev Compose | Filip | README only |

A seventh repo, `scenarios`, gets created once the flow is up and working. Until then, the first scenario lives in `api`.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/repos-dark.svg">
  <img src="assets/diagrams/repos-light.svg" width="100%" alt="The five code repositories. contracts publishes a NuGet and an npm package. sandbox and api install the NuGet package, web installs the npm package, and api also installs SandboxClient from sandbox. Every repo calls the CI workflows in platform.">
</picture>

Read the arrows as "installs a package from". `contracts` defines every message the programs exchange and publishes it twice, as a NuGet package for the .NET repos and an npm package for `web`. `api` also installs `SandboxClient` from `sandbox`, so it can talk to a sandbox without knowing how the connection works. Every repo's CI is a few lines that call a workflow in `platform`.

---

## 📁 Workspace folder structure

Clone every repo side by side into one local folder. Full per-repo trees are in [ARCHITECTURE.md §7](ARCHITECTURE.md#7-folder-structure).

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
    ├── lint/                                 # canonical .editorconfig, analyzers, eslint, prettier
    ├── infra/                                # OpenTofu: hetzner/ (server, firewall), proxmox/ (bridge, pool, token)
    ├── deploy/                               # hetzner/ (compose with RabbitMQ, Caddyfile), proxmox/ (envmgr unit, nftables), wireguard/
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
| **Filip** | Infra for every repo (CI, lint, releases, deploy), the machines and the mesh, `contracts`, `sandbox`, the Scenarios and Agent libraries, curated scenarios |
| **Person 2** | `api`: auth, sessions, WebSocket gateway, persistence, event log, queue integration, progress |
| **Person 3** | `web`: topology canvas, scenario panel, chat and question card, terminal, config inspector, timeline/replay |

## 🛣️ Roadmap

| Milestone | Demoable result |
|---|---|
| **M1 Sandbox** | A 3-node cluster comes up in a Proxmox sandbox; commands run over the harness WebSocket; the UI renders a (fake) topology |
| **M2 Scenarios** | One click starts a queued sandbox; a real terminal; the first scenario with checks and reset, no LLM needed; the stack is deployed on the Hetzner box over the mesh |
| **M3 Live view** | Real topology from the cluster's watch streams, including Ingress; YAML inspector |
| **M4 Helper** | The optional helper: typed tools, streamed answers, demonstrations with feedback questions, an agent-driven camera |
| **M5 Scenarios + scale** | The full 3–5 scenarios, the `scenarios` repo, a load test, timeline + replay, traffic animation |

The final demo is **by June 2027**. The design target is 30 concurrent sandboxes, and only what the demo needs gets provisioned.

**Stretch:** bring-your-own repo, add/remove nodes, spectator mode, real VMs as nodes.

## 📄 License

[MIT](LICENSE)
