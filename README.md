# kubernetes-learning-platform

> A live Kubernetes lab with an optional AI helper. Learners work on a real, disposable cluster and see every change as it happens.

University team project · demo only · hosted on one course-provided VM, reached over Tailscale · "kubernetes-learning" is a placeholder name

---

## Overview

The platform gives each learner a real Kubernetes cluster to work on. A session provides:

- **A dedicated cluster.** A disposable 3-node cluster in its own virtual machine, with a terminal and unrestricted `kubectl` access. Nothing is simulated.
- **A live view.** A diagram of the cluster next to the terminal, updated as nodes, pods, services and ingresses change.
- **Scenarios.** Guided exercises, such as repairing a broken ingress, with automatic checks, optional hints and a reset.
- **An optional AI helper.** It explains and demonstrates on request, shows every command it runs, and asks how to continue. The rest of the platform works without it.

The sandbox is deleted when the session ends.

---

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/system-map-dark.svg">
  <img src="assets/diagrams/system-map-light.svg" width="100%" alt="The whole system. A browser in the tailnet reaches the Caddy proxy on the course VM, which serves web and forwards to api. api uses Postgres, RabbitMQ and an LLM API, and reaches envmgr on the same VM. envmgr relays to the harness inside a sandbox VM, which drives three Sysbox node machines.">
</picture>

A browser in the team's Tailscale tailnet connects to the stack on the course-provided VM. The same VM runs `envmgr` and one sandbox per session.

| Component | Responsibility |
|---|---|
| **web** | The browser application: cluster view, terminal, scenario panel and helper chat. It holds no business logic and reads all data from `api`. |
| **Caddy** | Reverse proxy. Serves one HTTPS origin and routes page requests to `web`, and API and WebSocket requests to `api`. |
| **api** | Backend. Handles authentication and sessions, runs scenarios and the optional helper, and records every session event in order. It does not run Kubernetes. |
| **Postgres** | Stores accounts, sessions, progress and the session event log used for replay. |
| **RabbitMQ** | Work queue for sandbox start and teardown requests. No other traffic uses it. |
| **envmgr** | Sandbox manager, a systemd service on the VM. Maintains a pool of ready sandboxes, assigns one per session, deletes it afterwards, and relays messages between `api` and the sandbox. |
| **harness** | Agent inside each sandbox. Executes commands, provides the terminal, runs scenario checks, and watches the cluster to report changes. |
| **Nodes** | The Kubernetes cluster: three nodes (`cp`, `w1`, `w2`), small machines running k3s inside the sandbox that the learner can `ssh` into. The sandbox VM itself is the learner's workstation. |

`web`, `api`, `envmgr` and `harness` are developed in this project. Postgres, RabbitMQ and Caddy are standard components.

### Design principles

1. **The learner is in control.** The terminal belongs to the learner by default, and scenarios and their checks do not require an LLM. The helper acts only on request, shows every command, and then asks how to continue.
2. **The helper's logic runs in the backend.** The LLM loop runs in `api`. The `harness` only executes commands and observes, so API keys never enter the VM, and a VM can be lost without losing the conversation.
3. **The view reflects actual cluster state.** The canvas is drawn only from what the harness observes in Kubernetes. The helper can move the camera (`focus`, `highlight`, `annotate`) but cannot change what is shown.
4. **Faults are typed operations.** Stopping a node or a service, deleting a pod or setting a bad image is recorded and reversible, so the UI knows exactly what was broken.

### Hosting

One **course-provided VM** (16 vCPU, 32 GB RAM) runs everything. Nothing is public: the VM is reached over **Tailscale**, and Caddy serves the app on our own domain with a certificate obtained through the DNS-01 challenge. Details in [ARCHITECTURE §3.1](ARCHITECTURE.md#31-hosting) and [ADR 0003](adr/0003-course-vm-hosting.md).

| On the VM | Runs |
|---|---|
| **The stack** | Caddy, `web`, `api`, Postgres, RabbitMQ. The deploy format is OPEN. |
| **envmgr** | A systemd service on the host, because it needs `/dev/kvm` and libvirt |
| **The sandboxes** | One per session, on an isolated network: a QEMU/libvirt VM if the VM supports nested virtualization (OPEN until checked), with three Sysbox node machines inside ([ADR 0004](adr/0004-node-machines-in-the-sandbox.md)). |

The demo laptop, the team and the graders use the app from devices in the tailnet.

### Services

| Service | Tech | Runs | Entry points |
|---|---|---|---|
| **web** | Next.js (React Flow, xterm.js, Monaco) | The stack on the VM | Routes: `/`, `/login`, `/session/[id]`, `/session/[id]/replay` |
| **api** | ASP.NET Core, .NET 10 | The stack on the VM | **4 controllers**: `Auth`, `Sessions`, `Scenarios`, `Events` · WebSocket `/ws/sessions/{id}` |
| **envmgr** | .NET 10 daemon | systemd on the VM | **1 gRPC service** for `api`: `Create` / `Destroy` / `Get` / `List` / `Watch` sandbox + `Connect` relay · harness WebSocket on the sandbox network · consumes start and teardown requests from RabbitMQ |
| **harness** | .NET 10 Native AOT | inside every sandbox | Frame router → `Exec`, `Pty`, `File`, `Fault`, `Check` handlers + Kubernetes/Docker watchers |
| Postgres | off the shelf | The stack on the VM | Users, sessions, progress, append-only event log |
| RabbitMQ | off the shelf | The stack on the VM | Sandbox start and teardown requests only; live streams stay direct |
| Caddy | off the shelf | The stack on the VM | `/` → web, `/api` + `/ws` → api, HTTPS on the Tailscale address only |

---

## Session startup

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/session-start-dark.svg">
  <img src="assets/diagrams/session-start-light.svg" width="100%" alt="Starting a session in eight steps, from the browser through api and the RabbitMQ work queue to envmgr and a sandbox, and back to the browser.">
</picture>

1. The browser requests a session. `api` creates it in the `queued` state.
2. `api` publishes a start request to the work queue.
3. `envmgr` consumes the request when capacity is available. Until then the request stays queued, and the learner sees their position.
4. `envmgr` assigns a sandbox from the warm pool, or creates a new one from the template.
5. `envmgr` publishes the result: the sandbox ID and its own address.
6. `api` opens a direct gRPC stream to `envmgr` for the session. The queue is not used after this point.
7. The harness sends a full snapshot of the cluster.
8. The browser marks the session as live and renders the snapshot.

Teardown uses the same queue, so a teardown request is not lost while `envmgr` restarts. See [ARCHITECTURE §6](ARCHITECTURE.md#6-key-flows), flows 1 and 11.

## State and intent streams

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/two-streams-dark.svg">
  <img src="assets/diagrams/two-streams-light.svg" width="100%" alt="A command travels from the terminal through api and envmgr to the harness, which runs it. The cluster changes, the harness sees the change through its watches, and a diff travels back through envmgr and api to the canvas. Separately, the helper can only move the camera.">
</picture>

1. The learner enters a command in the terminal.
2. `api` and `envmgr` forward it to the harness, which runs it in a shell inside the sandbox.
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
| [adr/](adr/) | Architecture decision records, one per decision. [0001](adr/0001-hosting-and-harness-transport.md): the WebSocket-only harness; its hosting plan is superseded by 0003. [0002](adr/0002-learner-driven-scenarios-and-scale-target.md): learner-driven scenarios, the optional helper, RabbitMQ, the 30-sandbox design target. [0003](adr/0003-course-vm-hosting.md): one course-provided VM runs the stack and the sandboxes, reached over Tailscale. [0004](adr/0004-node-machines-in-the-sandbox.md): cluster nodes are Sysbox machines inside the sandbox VM, which is the workstation |
| [plans/](plans/) | Plans for upcoming work. [schema-v0.1](plans/schema-v0.1.md): every message of contracts v0.1, file by file. [milestone-1](plans/milestone-1.md): what Milestone 1 builds in each repo, and in what order |

The diagrams are generated by [`assets/diagrams/generate.py`](assets/diagrams/generate.py). To change one, edit its definition in that file and run the script.

Decision labels used throughout: **DECIDED** (agreed) · **DEFAULT** (proposed, not objected to) · **OPEN** (not decided) · **CALL** (chosen during planning, change freely).

---

## Repositories

GitHub has no nested repositories, so the organization groups them and this repository links to the others.

| Repo | Purpose | Owner | Status |
|---|---|---|---|
| **[docs](https://github.com/kubernetes-learning-platform/docs)** | This documentation hub | Filip (everyone contributes) | Current |
| **[contracts](https://github.com/kubernetes-learning-platform/contracts)** | Protobuf schema for the whole system → NuGet + npm packages | Filip | Documentation only |
| **[sandbox](https://github.com/kubernetes-learning-platform/sandbox)** | `envmgr` (daemon on the VM), `harness` (agent in each sandbox), SandboxClient library, sandbox template, scenario images | Filip | Documentation only |
| **[api](https://github.com/kubernetes-learning-platform/api)** | ASP.NET Core backend + the Scenarios and Agent libraries | Person 2 (Scenarios + Agent: Filip) | Documentation only |
| **[web](https://github.com/kubernetes-learning-platform/web)** | Next.js frontend: canvas, scenarios, terminal, helper chat, inspector, replay | Person 3 | Documentation only |
| **[platform](https://github.com/kubernetes-learning-platform/platform)** | Shared CI workflows, lint configs, the VM install script and deploy files, dev Compose | Filip | Documentation only |

A seventh repository, `scenarios`, will be created once the end-to-end flow works. Until then, the first scenario is kept in `api`.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/repos-dark.svg">
  <img src="assets/diagrams/repos-light.svg" width="100%" alt="The five code repositories. contracts publishes a NuGet and an npm package. sandbox and api install the NuGet package, web installs the npm package, and api also installs SandboxClient from sandbox. Every repo calls the CI workflows in platform.">
</picture>

An arrow means "installs a package from". `contracts` defines every message exchanged between the programs and publishes it as a NuGet package for the .NET repositories and an npm package for `web`. Every merge that changes the schema publishes a release, and a bot moves `sandbox`, `api` and `web` to it. `api` also installs `SandboxClient` from `sandbox`. Each repository's CI calls reusable workflows in `platform`.

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
│       ├── node/                             # node machine image (systemd + sshd + k3s)
│       ├── base/                             # sandbox template (Ubuntu + Docker + Sysbox + node image + harness)
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
    ├── .github/workflows/                    # reusable: dotnet-ci, node-ci, proto-ci, contracts-bump, lint-sync, container-publish, release-version, sandbox-release, sandbox-template, pr-title, copilot-review
    ├── lint/                                 # canonical .editorconfig, analyzers, biome.json, sync.sh
    ├── deploy/vm/                            # install script, envmgr unit, libvirt network, nftables, stack config
    └── dev/                                  # local dev Compose: Postgres + Caddy, one origin on localhost:8080
```

---

## Getting started

The code repositories are scaffolded and build. Milestone 1 is planned in [plans/milestone-1.md](plans/milestone-1.md), and its issues are in each repo's **Milestone 1**. Each repo keeps its scripts in `scripts/`.

```bash
mkdir kubernetes-learning && cd kubernetes-learning
for repo in docs contracts sandbox api web platform; do
  git clone https://github.com/kubernetes-learning-platform/$repo.git
done
```

Requirements:
- .NET 10 SDK
- Node.js 24
- Docker Desktop, for the dev Compose and the database tests
- Only for running real sandboxes on a Mac: Lima, on Apple M3 or later (see `sandbox`)
- The GitHub CLI (`gh`), signed in as a member of the organization, for the `contracts` packages (below)

KVM is not required for day-to-day development. `api` runs against a **fake sandbox** that plays a scripted cluster, on Windows and macOS. Real sandboxes run in a Lima VM with nested virtualization on a Mac, or on the course VM. Access to the deployed application requires joining the team's Tailscale tailnet; ask Filip for an invite.

### The contracts packages

`sandbox` and `api` install `KubernetesLearning.Contracts`, and `web` installs `@kubernetes-learning-platform/contracts`, from GitHub Packages, which needs a token even to read. Each repo commits a `nuget.config` or `.npmrc` that reads the token from `GITHUB_PACKAGES_TOKEN`, so nobody adds a package source by hand. Set it up once:

```bash
gh auth refresh --hostname github.com --scopes read:packages
```

```bash
echo 'export GITHUB_PACKAGES_TOKEN="$(gh auth token)"' >> ~/.zshrc
```

Then open a new terminal, and restart Rider or VS Code so they see the variable. `dotnet restore` in `sandbox` or `api` and `npm ci` in `web` should now work. Docker image builds take the token as a build secret:

```bash
docker build --secret id=github-packages-token,env=GITHUB_PACKAGES_TOKEN --tag api .
```

- **Without the GitHub CLI,** a classic personal access token with `read:packages` works as `GITHUB_PACKAGES_TOKEN`. Fine-grained tokens don't work with GitHub Packages.
- **If a restore fails with 401 or 403,** check that `gh auth status` lists `read:packages` and that the variable is set in that shell. If both are fine, your account has no read access to the packages yet; ask Filip.
- **New versions** arrive on `main` as `build(deps): bump contracts to X.Y.Z` commits from the update bot. Pull, and restore again.

---

## Conventions

- **Commits:** strict [Conventional Commits](https://www.conventionalcommits.org/), one line, e.g. `feat: add warm pool`. No body, no co-author trailers.
- **PRs:** the title uses the same format. Every repo only allows squash merges, and the squash commit is the PR title, so `main` gets one clean line per change. A check fails any PR whose title doesn't follow the format.
- **Reviews:** every repo is public, and `main` is protected: PRs only, squash merges, a passing title check on a branch that is up to date with `main`, and one approval from someone other than the author. Filip is requested as reviewer on every PR, and the author is assigned automatically.
- **Copilot:** every PR gets one Copilot review when it opens, except Markdown-only PRs and PRs labelled `skip-copilot`. It needs Copilot on your account, which is free through GitHub Student.
- **Branches:** each issue names its branch in a `Branch:` line, e.g. `feat/warm-pool`. Create it with `gh issue develop <number> --name <branch>`, or with the issue's **Create a branch** button renamed to match. Branches are deleted after merging.
- **Where changes land:** in the code repos, every change goes through a PR, and its README and doc updates go in the same PR as the feature they describe. The `docs` repo is only documentation, so it commits straight to `main`.

- **AI agents:** every repo has an `AGENTS.md` that explains the repo and these rules, and a `CLAUDE.md` symlinked to it. Agents ask before creating a branch or committing.

More in [platform → Conventions](https://github.com/kubernetes-learning-platform/platform#conventions).

---

## Team

| | Owns |
|---|---|
| **Filip** | Infra for every repo (CI, lint, releases, deploy), the VM and the tailnet, `contracts`, `sandbox`, the Scenarios and Agent libraries, curated scenarios |
| **Person 2 and Person 3** | `api` and `web`, split by feature: each takes whole features through both repos, such as sign-in and sessions, or the live lab with its socket, event log and canvas |

## Roadmap

| Milestone | Demoable result |
|---|---|
| **Milestone 1** | A real sandbox with three node machines comes up from the `sbx` CLI on a Lima VM, and commands run over the harness WebSocket. In the browser, you sign in, start a session and watch the fake cluster live on the canvas ([plan](plans/milestone-1.md)) |
| **Milestone 2** Scenarios | The two halves joined: one click starts a queued real sandbox; a real terminal; the first scenario with checks and reset, no LLM needed; the stack is deployed on the course VM |
| **Milestone 3** Live view | Real topology from the cluster's watch streams, including Ingress; YAML inspector |
| **Milestone 4** Helper | The optional helper: typed tools, streamed answers, demonstrations with feedback questions, an agent-driven camera |
| **Milestone 5** Scenarios + scale | The full 3–5 scenarios, the `scenarios` repo, a load test, timeline + replay, traffic animation |

The final demo is **by June 2027**. The design target is 30 concurrent sandboxes, and only what the demo needs gets provisioned.

**Stretch:** bring-your-own repo, add/remove nodes, spectator mode.

## License

[MIT](LICENSE)
