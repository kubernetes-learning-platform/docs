# kubernetes-learning — Architecture & Repository Plan

> Planning output, 2026-11-02, updated by two decision records. [ADR 0001](adr/0001-hosting-and-harness-transport.md): the stack runs on a Hetzner box, sandboxes run on a Proxmox box at home, everything (including the demo laptop) is joined by a WireGuard mesh, and the harness speaks WebSocket only. [ADR 0002](adr/0002-learner-driven-scenarios-and-scale-target.md): the learner drives, the agent is an optional helper that acts when asked, scenarios replace lessons, RabbitMQ handles sandbox start and teardown, and the design target is 30 concurrent sandboxes. Builds on the original brief in [PROJECT-BRIEF.md](PROJECT-BRIEF.md), which is still the source for the cluster design and the agent tool list. This document decides **how the work is split into repos, services, machines and code**.
>
> **"kubernetes-learning" is a placeholder name** (the old working name is dropped). See [§12](#12-naming) for where the name appears and when to replace it.
>
> Labels, same as the brief: **DECIDED** = agreed by the team · **DEFAULT** = proposed, not objected to · **OPEN** = not decided. New label: **CALL** = chosen during this planning pass to keep things moving; change freely.

---

## 0. At a glance

| | Count | What |
|---|---|---|
| **Repos** | **6** | `docs` (parent), `contracts`, `sandbox`, `api`, `web`, `platform`. A seventh, `scenarios`, is created once the flow is up and working (DECIDED). |
| **Services we write** | **4** | `web`, `api`, `envmgr`, `harness` |
| **Off-the-shelf services** | **3** | Postgres, Caddy (reverse proxy, CALL), RabbitMQ (sandbox start and teardown, DECIDED) |
| **Machines** | **3** | Hetzner box (the stack), Proxmox box at home (sandboxes), demo laptop (browser), joined by a WireGuard mesh |
| **Libraries we write** | **4** | Contracts (C# + TS), SandboxClient, Scenarios, Agent |
| **REST controllers** | **4** | Auth, Sessions, Scenarios, Events (+ 1 WebSocket endpoint) |
| **gRPC services** | **1** | EnvironmentManager (in `envmgr`) |
| **Other build outputs** | **2** | Proxmox VM template (Packer), scenario demo images |
| **Infra code** | **1** | OpenTofu for the Hetzner box and the Proxmox side (CALL) |

### Scope decisions (DECIDED, latest changes in [ADR 0002](adr/0002-learner-driven-scenarios-and-scale-target.md))

| Topic | Decision | Consequence |
|---|---|---|
| **Product** | **One click gives you a ready cluster and a real terminal, with full `kubectl` freedom.** You start with a scenario or a blank cluster (CALL). | The learner drives. Everything except the helper works with no LLM. |
| **Helper** | **Optional, and acts only when asked.** It shows every command, then asks feedback questions it writes itself. | A helper turn only starts from a learner's message or answer. There's no control lock and no take-control step (§6.1). |
| **Scenarios** | **3–5 from simple to complex, one folder each, on one shared VM template.** Automatic checks on real behaviour, and reset goes back to the step's start. | Adding a scenario is a folder and a PR. The list, and whether Helm is included, are decided later (OPEN). |
| **Demo shape** | **Final demo by June 2027**, on a projector from Filip's laptop with sandboxes on his home PC, plus 1–2 extra sessions for graders to try | Mesh only (graders try from a device on the mesh) · no spectator mode · light auth is enough · the mobile layout is nice-to-have |
| **Scale** | **Design target: 30 concurrent sandboxes.** Provision only what the demo needs. | A capacity cap and a wait line, no single-host assumptions, a load test in M5 (§3.3). Multiple `api` instances, high availability and autoscaling stay out of scope. |
| **Work queue** | **RabbitMQ for sandbox start and teardown only.** | Requests wait for capacity and survive link drops. Live streams stay direct. |
| **Progress** | **Saved per account.** No admin tools. | The home screen shows what you've finished and what's next. |
| **Hosting** (2026-11-04, [ADR 0001](adr/0001-hosting-and-harness-transport.md)) | **Stack on a small Hetzner box, sandboxes on a Proxmox box at home, all on a WireGuard mesh with the demo laptop** | Nothing is public, so light auth stays enough. The `api` ↔ `envmgr` link crosses the internet and must survive drops. vsock is gone: the harness speaks WebSocket for every provider. |
| **BYO repo** | **Stretch goal** | MVP sandboxes are fully offline. Registry/package egress, building in the VM and opening apps in the browser all come after M5. |
| **Traffic** | **Static edges + scenario probe** | `routes-to` edges come from Endpoints. demo-web replies with its pod name, and a probe pod lets the canvas animate hits per pod. No network plugin changes. |

---

## 1. Team & ownership

| Person | Owns | DECIDED |
|---|---|---|
| **Filip** | Infra for every repo (CI, lint, releases, deploy), the machines (Hetzner box, Proxmox box, WireGuard mesh), `contracts`, `sandbox` (envmgr + harness + VM template), the **Agent** and **Scenarios** libraries, and the curated scenarios | ✅ |
| **Person 2** | `api`: auth, sessions, WebSocket gateway, persistence, event log, queue integration, progress | ✅ |
| **Person 3** | `web`: topology canvas, scenario panel, chat and question card, terminal, config inspector, timeline/replay | ✅ |

People help across lines when needed (DECIDED). Filip has the most surface area, but most of it (contracts, CI, sandbox) has to exist first anyway, before `api` and `web` can go far.

Ownership is enforced by repo boundaries, plus a `CODEOWNERS` file in `api` that assigns `src/KubernetesLearning.Agent/`, `src/KubernetesLearning.Scenarios/` and `scenarios/` to Filip.

---

## 2. Repositories

All six live in the GitHub organization [`kubernetes-learning-platform`](https://github.com/kubernetes-learning-platform), so container images, packages and releases sit together. GitHub has no nested repos, so the org is the container and `docs` is the parent repo everything links from. A seventh repo, `scenarios`, is created **once the flow is up and working** (DECIDED, [ADR 0002](adr/0002-learner-driven-scenarios-and-scale-target.md)). Until then, the first scenario lives in `api/scenarios/` and its custom images in `sandbox/images/`.

| Repo | Contains | Ships | Owner |
|---|---|---|---|
| **`docs`** (parent) | Architecture, features, the original brief, ADRs. The hub that links every other repo. | Nothing | Filip (everyone contributes) |
| **`contracts`** | Protobuf schema for the whole system + codegen | NuGet `KubernetesLearning.Contracts`, npm `@kubernetes-learning-platform/contracts` → GitHub Packages | Filip |
| **`sandbox`** | `envmgr`, `harness`, `SandboxClient` library, dev CLI, the Packer definition of the Proxmox VM template, scenario demo images | envmgr binary + harness binary → GitHub Releases · NuGet `KubernetesLearning.SandboxClient` · VM template → the Proxmox box · scenario images → GHCR | Filip |
| **`api`** | ASP.NET Core backend + Scenarios library + Agent library + the first scenario | `api` image → GHCR | Person 2 (Scenarios + Agent: Filip) |
| **`web`** | Next.js frontend | `web` image → GHCR | Person 3 |
| **`platform`** | Reusable CI workflows, canonical lint configs, infrastructure code (OpenTofu), deploy files per machine (Compose with RabbitMQ, Caddyfile, envmgr unit, firewall rules, WireGuard and env examples), dev Compose | Nothing at runtime; other repos call its workflows | Filip |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/repos-dark.svg">
  <img src="assets/diagrams/repos-light.svg" width="100%" alt="The five code repositories and the packages that connect them. Every repo calls the CI workflows in platform.">
</picture>

### Why this shape (CALL)

- **Grouped by owner, not one repo per service.** Nine repos for three people is overhead with no payoff.
- **envmgr + harness + SandboxClient share a repo.** They are the two ends of one private protocol and the client for it. A protocol change is one PR, and one CI run can test all three together (Docker provider, real harness, real client).
- **SandboxClient lives in `sandbox`, not `api`.** Everything about talking to a sandbox belongs to Filip. Person 2 consumes a clean `ISandboxSession` interface and never touches frame correlation, reconnects or relay details.
- **The Agent lives in `api`, not its own repo.** It runs in the api process (DECIDED) and changes constantly during M4–M5. A separate repo would mean publishing a package for every prompt or tool tweak.
- **Scenarios get their own library, not part of the Agent** (CALL). They must work with the helper off, so `KubernetesLearning.Scenarios` has no LLM dependency. The Agent references it, not the other way round.
- **`contracts` is its own repo** because everyone depends on it. It gets SemVer versions, `buf lint`, and `buf breaking` against `main` in CI.
- **`docs` is separate from `platform`** (DECIDED by Filip: the parent repo holds the documentation). Docs changes like a new ADR or a scenario idea don't go through the CI/deploy repo.
- **`platform` holds anything shared that isn't code a service runs or documentation.** Each other repo's CI file is about 10 lines that call a reusable workflow from here.

### Rejected repo layouts

- **Monorepo with CODEOWNERS.** Simplest for keeping contracts in sync, but the team wants each person's work to be clearly theirs at repo level.
- **One repo per service/library (8–9 repos).** Too much release and versioning overhead for three people.
- **Agent in its own repo.** The publish → bump → test loop is too slow for the most-iterated code in the project.

---

## 3. Runtime architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/system-map-dark.svg">
  <img src="assets/diagrams/system-map-light.svg" width="100%" alt="The runtime architecture: browser, the Compose stack on the Hetzner box, envmgr and the sandbox VMs on the Proxmox box, joined by the WireGuard mesh.">
</picture>

Everything in the brief's §2–§5 still holds, except hosting and the harness transport, which [ADR 0001](adr/0001-hosting-and-harness-transport.md) replaces, and the product shape, which [ADR 0002](adr/0002-learner-driven-scenarios-and-scale-target.md) replaces. Additions from this plan:

- **Caddy reverse proxy** (CALL). One origin for the browser: `/` → web, `/api/*` and `/ws/*` → api. Cookies stay same-origin and there's no CORS setup. It listens only on the Hetzner box's mesh address and serves HTTPS from its internal CA (`tls internal`, CALL), which the demo laptop trusts once. HTTPS still matters inside WireGuard: browsers only give secure contexts (clipboard, `crypto.randomUUID`) to HTTPS pages. It's off-the-shelf like Postgres, so the DECIDED rule "only web and api are images we build" still holds. Drop it if it gets in the way.
- **Harness traffic reaches api through envmgr** (brief §5's recommendation, adopted as CALL). envmgr relays each harness connection as one bidirectional gRPC `Connect` stream per session. api has one code path regardless of provider, and the VM never needs a route to api.
- **RabbitMQ for sandbox start and teardown only** (DECIDED). Starts arrive in bursts and capacity is limited, so requests wait in a work queue, and `envmgr` takes one only when it has room. Chat, tool calls, terminal, topology, checks and the event log never touch the broker: they're per-session, ordered and latency-sensitive, so they stream directly.

### 3.1 Machines and the mesh

**DECIDED** by Filip, 2026-11-04 ([ADR 0001](adr/0001-hosting-and-harness-transport.md)).

| Machine | Runs | Mesh address (CALL) | Reachable from the internet |
|---|---|---|---|
| **Hetzner box** (small cloud server) | Docker Compose: Caddy, `web`, `api`, Postgres, RabbitMQ | `10.66.0.1` | WireGuard (UDP 51820) and SSH only |
| **Proxmox box** (home server PC) | Proxmox VE, `envmgr` (systemd on the host), sandbox VMs | `10.66.0.2` | Nothing. It dials out to the Hetzner box. |
| **Demo laptop** | The browser on the projector | `10.66.0.3` | Nothing. It dials out to the Hetzner box. |

- The Hetzner box is the only peer with a public endpoint. The other two connect out to it with `PersistentKeepalive`, so neither the home network nor the demo venue needs port forwarding. Traffic between the laptop and the Proxmox box (only needed for admin, like the Proxmox web UI) is routed through the Hetzner box.
- **Nothing is public.** `web`, `api` and Postgres are only reachable over the mesh. Graders try the app from a device on the mesh: the demo laptop, or a second laptop with its own peer config.
- `api` reaches `envmgr`'s gRPC service at `10.66.0.2:7070` (CALL) over plain HTTP/2. WireGuard already encrypts and authenticates both ends. A firewall rule on the Proxmox box accepts that port only from `10.66.0.1`. The address comes from each `ProvisionResult`, not from a single setting, so nothing assumes one sandbox host.
- `envmgr` dials out to RabbitMQ at `10.66.0.1:5672` (CALL). It's firewalled to sandbox hosts and has its own credentials. Requests still queue while the home link is down.
- The Hetzner box can be x64 or ARM: the `api` and `web` images are built multi-arch (CALL).

### 3.2 Sandbox network (on the Proxmox box)

- Sandbox VMs sit on their own Proxmox bridge (`vmbr1`, `10.67.0.0/24`, CALL) with no physical port.
- `envmgr`'s harness endpoint listens on the host's address on that bridge, `10.67.0.1:7071` (CALL). It is the **only** thing a sandbox can reach: static firewall rules on the bridge drop traffic to the internet, the home LAN, the mesh and other sandboxes.
- Each VM gets a static address on the bridge from `envmgr`, through cloud-init.
- MVP sandboxes stay fully offline. BYO-repo egress (stretch) would mean NAT on this bridge with the home LAN and the mesh still blocked.

### 3.3 Design target: 30 concurrent sandboxes

**DECIDED** by Filip ([ADR 0002](adr/0002-learner-driven-scenarios-and-scale-target.md)). Planning for more usage than the demo needs leads to better decisions. **Nothing beyond what the demo needs gets provisioned.** Everything below except the target itself is CALL:

| Area | Decision |
|---|---|
| **Machines** | Two roles, the **stack** and the **sandbox host**, connected by configured addresses. Today they're the Hetzner box and the home PC. Nothing may assume they're separate machines, or that there's only one sandbox host. |
| **Capacity** | A hard cap per host, `Sandbox__MaxConcurrent`, set from that host's RAM. It counts every running VM, warm ones included. Over the cap, a session waits: `SessionStatus{queued, position}`. `WarmPool__Size` stays a setting and can be raised ahead of busy periods. |
| **RAM** | The real limit. 4 GB per sandbox is an estimate: 30 would need about 120 GB before any sharing between identical clones. Measure real usage in M1, including Proxmox's KSM memory sharing. |
| **`api`** | One instance. 30 sessions should fit, and the load test confirms it. |
| **Event log** | Persist-then-broadcast stays. Terminal output is batched (about 50 ms) before it's written, so typing doesn't mean one database row per chunk. |
| **LLM** | A global limit on concurrent helper turns (`Agent__MaxConcurrentTurns`) on top of the per-session token budget. |
| **Link drops** | Every session reconnects at the same moment, so redials use backoff **with jitter**. |
| **Load test** | 30 scripted sessions against `FakeSandboxSession`, plus as many real sandboxes as the home PC holds. |

---

## 4. Services and their entry points

### 4.1 `api` — ASP.NET Core (.NET 10) · Person 2 + Filip

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/api-dark.svg">
  <img src="assets/diagrams/api-light.svg" width="100%" alt="Inside the api process: controllers and the socket face the browser, LiveSession holds one running lab, EventFanout persists then broadcasts, and the Scenarios, Agent and SandboxClient libraries sit behind it.">
</picture>

**REST controllers** (JSON bodies, defined as Protobuf messages in `rest.proto`, serialized with proto3 JSON mapping, CALL):

| Controller | Routes | Purpose |
|---|---|---|
| `AuthController` | `POST /api/auth/login` · `POST /api/auth/logout` · `GET /api/auth/me` | Delegates to `IAuthProvider`. The mechanism is **OPEN**, but the abstraction is fixed. |
| `SessionsController` | `POST /api/sessions` (body: `scenarioId?`, none means a blank cluster; `repoUrl?` is stretch) · `GET /api/sessions` · `GET /api/sessions/{id}` · `DELETE /api/sessions/{id}` | Start/list/inspect/end. A start creates a `queued` session. Enforces one active session per user (DEFAULT). One scenario per session: picking another starts a new sandbox (CALL). |
| `ScenariosController` | `GET /api/scenarios` · `GET /api/scenarios/{id}` | Scenario catalog for the home screen, with this account's progress. Goals and hints are included; the `helper` notes and `solution` are not (CALL). |
| `EventsController` | `GET /api/sessions/{id}/events?afterSeq=&limit=` | Event log pages for timeline + replay. Returns `application/x-protobuf` `EventBatch`. |

**WebSocket endpoint** (minimal API, not a controller): `GET /ws/sessions/{id}`. Binary frames, each one `ClientMessage` or `ServerMessage` from `session.proto`.

| Browser → api (`ClientMessage`) | api → Browser (`ServerMessage`, each with a per-session `seq`) |
|---|---|
| `ChatSend` · `TerminalInput` · `TerminalResize` · `ApplyManifest{yaml}` · `HelperStop` · `AgentAnswer{questionId, optionId \| text}` · `ScenarioNext` · `StepReset` · `Resync{afterSeq}` | `ChatDelta` · `ChatMessage` · `ToolCallStarted` · `ToolCallFinished` · `AgentQuestion{questionId, text, options[]}` · `HelperState{idle \| acting \| waiting}` · `TopologySnapshot` · `TopologyDiff` · `ClusterEvent` · `ViewIntent` · `FaultMarked` · `FaultReverted` · `TrafficSample` · `ScenarioProgress` · `TerminalOutput{source: user\|agent}` · `SessionStatus{queued, position \| starting \| live \| reconnecting \| ended}` · `Error` |

Health: `MapHealthChecks("/healthz")`, not a controller.

**Internal services** (`KubernetesLearning.Api`, Person 2):

| Area | Classes | Role |
|---|---|---|
| Sessions | `SessionService`, `SessionRegistry`, `LiveSession`, `IdleReaper` | Create/end sessions. Each live session holds its sandbox session, scenario runner, optional agent runner, subscribers and helper state. Terminal input and `ApplyManifest` are refused while the helper is acting (§6.1). `IdleReaper` ends sessions idle > ~30 min (DEFAULT). |
| Provisioning | `ISandboxProvisioner`, `RabbitMqProvisioner` (Real mode), a fake (Fake mode, no broker) | Publishes start and teardown requests with publisher confirms, and consumes results and dead letters. If the broker can't be reached, a start returns "try again". Computes queue positions from its own `queued` sessions in Postgres, because RabbitMQ doesn't report them. |
| Realtime | `SessionSocketEndpoint`, `EventFanout`, `TopologyCache` | Assigns `seq`, **persists first, then broadcasts**, batching terminal output (about 50 ms) before writing it. Keeps the latest topology so a fresh socket gets a snapshot immediately. `Resync` replays from the store. |
| Sandbox link | `LiveSession` + `SandboxClient` | `envmgr` is on another machine across the mesh. If the `Connect` stream drops, the session goes `SessionStatus{reconnecting}`, in-flight tool calls fail with a retryable error, `SandboxClient` redials with backoff and jitter, and the fresh `TopologySnapshot` sent on reattach replaces the cached topology (flow 10). |
| Persistence | `AppDbContext` (EF Core + Npgsql), `EventStore`, migrations | Tables below. |
| Auth | `IAuthProvider` + one implementation | Implementation **OPEN**. |

**Scenarios library** (`KubernetesLearning.Scenarios`, Filip). No LLM dependency, so everything here works with the helper off (CALL):

| Area | Classes | Role |
|---|---|---|
| Catalog | `ScenarioCatalog`, `ScenarioDefinition` | Loads scenario folders: `scenario.yaml`, manifests and optional solutions. The format is in [ADR 0002 §4](adr/0002-learner-driven-scenarios-and-scale-target.md#4-scenarios-decided-a-folder-per-scenario-automatic-checks-reset-to-the-steps-start). |
| Runner | `ScenarioRunner` | One per live session with a scenario. Sends the files to the sandbox through the harness, applies a step's `start`, `enter` and `faults`, runs the checks about every 3 seconds and on topology changes, emits `ScenarioProgress`, handles `ScenarioNext` and `StepReset`, and records progress. |
| Seam to sandbox | `ISandboxSession` (from SandboxClient) | Files, exec, faults, checks, cluster state. |

**Agent library** (`KubernetesLearning.Agent`, Filip). No ASP.NET or EF dependency. It's the optional helper:

| Area | Classes | Role |
|---|---|---|
| Loop | `AgentRunner` | One per live session that uses the helper. `RunTurnAsync` only ever starts from a learner's message or answer, so the helper can't act on its own (CALL). Stops at the next tool boundary on `HelperStop`. Each turn starts with what the learner typed and what changed in the cluster since the last turn, built from the event log (CALL). |
| Seam to api | `IAgentEventSink` | Agent emits chat deltas, tool-call events, view intents and questions. api implements it with `EventFanout`. |
| Seam to sandbox | `ISandboxSession` (from SandboxClient) | Exec, files, faults, cluster state. |
| Seam to scenarios | `ScenarioRunner` | The current step's `helper` notes and `solution`, and `reset_step`. |
| LLM | `ILlmClient` + one implementation | Provider **OPEN**. |
| Tools | `ToolRegistry`, `ExecuteTools`, `ObserveTools`, `ViewTools`, `FaultTools`, `InteractionTools` | The typed tool set from brief §6, plus `revert_fault` and `start_traffic(service)` / `stop_traffic()` for the scenario traffic probe. `InteractionTools` holds `ask_user(question, options[])`, which suspends the turn until the answer becomes its result, and `reset_step()`, so the helper can act on a "reset it" answer. The cluster stays fixed at cp/w1/w2 for the MVP. `add_node` / `remove_node` (k3d node create/delete) are stretch goals. The topology is node-agnostic, so new nodes would just appear (CALL). |
| Budget | `TokenBudget` | Hard per-session cap (DEFAULT, number **OPEN**), plus a global limit on concurrent turns. When the budget runs out, the helper turns off and says so, and the scenario carries on (CALL). |

**Database** (CALL):

```
users           (id, display_name, auth_subject, created_at)
sessions        (id, user_id, sandbox_id?, sandbox_host?, scenario_id?, repo_url?, status, tokens_used, created_at, ended_at?)
session_events  (session_id, seq, at, kind, payload bytea)   PK (session_id, seq)  -- append-only
scenario_progress (user_id, scenario_id, step_id, status, helper_demonstrated, updated_at)   PK (user_id, scenario_id, step_id)
```

`session_events.payload` is the serialized `ServerMessage`, so replay feeds the browser **exactly** what it saw live.

`scenario_progress` drives the home screen. A step the helper demonstrated still counts, and the flag records that it did (CALL).

### 4.2 `envmgr` — .NET 10 self-contained daemon on the Proxmox host · Filip

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/sandbox-dark.svg">
  <img src="assets/diagrams/sandbox-light.svg" width="100%" alt="envmgr on the Proxmox host (gRPC service, relay, reconciler, queue consumers, providers) and the sandbox VM (harness, watchers, a three-node k3d cluster).">
</picture>

Runs as a systemd service directly on the Proxmox host (CALL, [ADR 0001](adr/0001-hosting-and-harness-transport.md)). Proxmox runs the VMs, so `envmgr` needs no `/dev/kvm`, no `/dev/net/tun` and no host network plumbing.

No REST controllers. **One gRPC service** on the mesh address `10.66.0.2:7070` (CALL), accepted only from the Hetzner box:

| gRPC `EnvironmentManager` | Purpose |
|---|---|
| `CreateSandbox` | Takes a VM from the warm pool (or clones one from the template). Returns sandbox id + status. Used by the `sbx` dev CLI; in Real mode, `api` starts sandboxes through the work queue (CALL). |
| `DestroySandbox` | Stops and deletes the VM, and frees its IP lease and token. Used by the `sbx` dev CLI; in Real mode, `api` uses the work queue (CALL). |
| `GetSandbox` / `ListSandboxes` | Status. `ListSandboxes` is for debugging and demo (CALL). |
| `WatchSandbox` | Stream: `booting → cluster_ready → failed / destroyed`. |
| `Connect` | Bidirectional `HarnessFrame` stream. envmgr pipes it to the harness. |

**Harness endpoint** (where the harness dials in, DECIDED): one WebSocket endpoint, `/harness`, for every provider. Each sandbox gets a one-time token at create time, and the harness's first frame is `Hello{sandboxId, token, version}`.
- Proxmox provider: listens on the host's address on the sandbox bridge, `10.67.0.1:7071` (CALL). cloud-init writes the token into the VM.
- Docker provider: listens on a TCP port reachable from the DinD container. The token is passed as an env var.

**Work queue** (DECIDED, details CALL, [ADR 0002 §6](adr/0002-learner-driven-scenarios-and-scale-target.md#6-rabbitmq-for-sandbox-start-and-teardown-only-decided)):
- `envmgr` consumes `ProvisionRequest` and `TeardownRequest` with manual acks. It takes a warm sandbox or clones one, and pauses its consumer when no warm sandbox is free and it's at `Sandbox__MaxConcurrent`.
- Redeliveries happen, so it records `requestId` with the sandbox and handles repeats idempotently.
- It publishes `ProvisionResult{requestId, sandboxId, host}`, then acks. `host` is its own gRPC address.
- After repeated failures (the queue's delivery limit), a request dead-letters and `api` marks the session failed.
- Queues are quorum queues with one member, for the delivery limit and dead-lettering. One node gives no fault tolerance, which is accepted.
- A second sandbox host later is just a second consumer, with no scheduler to write.
- It uses the official `RabbitMQ.Client` with automatic recovery. The harness never touches the broker, so Native AOT isn't affected.

**Proxmox provider** (CALL):
- **Template:** a Proxmox VM template built by Packer from `sandbox/images/base/` (Linux, Docker, k3d, kubectl, the harness, every scenario image).
- **Clone:** a linked clone per sandbox, so creating one takes seconds. Clones go into the resource pool `kl-sandboxes`, are tagged `kl-sandbox`, and are named `kl-sbx-<id>`.
- **Identity:** cloud-init sets `ipconfig0` (a static address on `10.67.0.0/24`) and a `cicustom` user-data snippet that writes `/etc/kubernetes-learning/harness.env` (sandbox id, token, envmgr URL). envmgr writes the snippet straight to host storage. Every clone is otherwise identical.
- **Credentials:** an API token for a dedicated Proxmox user whose role covers only the `kl-sandboxes` pool, the template, its storage and the sandbox bridge. The token never leaves the box.

**Internal services**:

| Area | Classes | Role |
|---|---|---|
| Providers | `ISandboxProvider`, `ProxmoxProvider`, `DockerProvider` (privileged DinD + k3d) | Create / destroy / inspect / list |
| Proxmox | `ProxmoxApiClient`, `CloudInitWriter` | A thin `HttpClient` over about five endpoints (clone, config, start, stop, delete, plus task status). Writes the per-sandbox cloud-init snippet. |
| Lifecycle | `SandboxRegistry`, `StateStore` (`/var/lib/kubernetes-learning`), `Reconciler` | **One reconcile loop** (CALL). Desired: `WarmPool__Size` idle sandboxes (DEFAULT) plus the ones in use, never more than `Sandbox__MaxConcurrent` in total. Actual: the VMs in the pool. It clones or deletes until they match, deletes VMs past `Sandbox__MaxLifetime` (the hard backstop) and VMs it has no record of, and re-adopts running VMs after a restart (DECIDED). Proxmox is the source of truth; `StateStore` keeps only tokens and IP leases. |
| Queue | `ProvisionConsumer`, `TeardownConsumer` | The work queue above. |
| Relay | `HarnessRelay`, `HarnessWebSocketEndpoint` | Pairs each harness connection with its api `Connect` stream and buffers until both sides are present. If api's stream drops, the harness connection stays open. On reattach, envmgr sends the harness a `SnapshotRequest` (flow 10). |

### 4.3 `harness` — .NET 10 Native AOT, inside every VM · Filip

No controllers. One connection, one **frame router**:

| Component | Role |
|---|---|
| `Program` / `HarnessHost` | Reads `Harness__Url`, `Harness__SandboxId` and `Harness__Token` (from `/etc/kubernetes-learning/harness.env`, written by cloud-init, or from container env vars in the Docker provider). Dials with retry and sends `Hello{sandboxId, token, version}`. |
| `IHarnessTransport` → `WebSocketTransport` | One `HarnessFrame` per binary WebSocket message. The interface stays so tests can use an in-memory transport. |
| `FrameRouter` | Dispatches by `oneof body` |
| `ExecHandler` · `PtyHandler` · `FileHandler` · `FaultHandler` · `CheckHandler` | The five request handlers. `CheckHandler` runs a scenario's `resource`, `http` and `command` checks inside the VM, so they test real behaviour without an LLM. |
| `FaultLedger` | Records every fault (id, kind, targets, undo action) so it can be **reverted** and the UI can **mark** it |
| `TrafficProbe` | Starts a probe pod (baked image) that curls a service in a loop. It tails the probe's logs, where demo-web replies with its pod name, and emits `TrafficSample{serviceId, hitsByPod}` about once a second. |
| `KubeWatcher` · `DockerWatcher` | Watch nodes, pods, deployments, replicasets, services, endpoints, ingresses and events, plus Docker events for node containers. More kinds, such as StatefulSets, get added as scenarios need them. |
| `TopologyModel` → `TopologyPublisher` | Normalized graph. Sends a snapshot on connect and on every `SnapshotRequest`, then revisioned diffs. |
| `ClusterBootstrap` | Confirms the k3d cluster is healthy and reports `cluster_ready` |

### 4.4 `web` — Next.js (App Router) · Person 3

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/web-dark.svg">
  <img src="assets/diagrams/web-light.svg" width="100%" alt="The lab screen: socket.ts feeds a topology store and a view store, which together draw the canvas, next to the terminal, scenario panel, helper chat and config inspector.">
</picture>

No controllers or API routes. It's a pure client of `api` through the proxy.

| Route | Screen |
|---|---|
| `/login` | Auth (form depends on the OPEN auth choice) |
| `/` | Scenario list with your progress, blank cluster start, resume active session |
| `/session/[id]` | The lab: topology canvas · terminal · scenario panel · helper chat · config inspector |
| `/session/[id]/replay` | The same lab, fed from `GET …/events` instead of the socket |

| Module | Role |
|---|---|
| `lib/socket.ts` | WebSocket client: protobuf-es encode/decode, reconnect + `Resync` |
| `lib/api.ts` | REST client |
| `state/` (Zustand, CALL) | `topologyReducer` (applies snapshot/diff by revision), `viewReducer` (intents → camera), scenario, chat, helper state |
| `components/` | `TopologyCanvas` (React Flow + elkjs auto-layout, CALL), `ScenarioPanel` (goal, checks, hints, Next, reset, Start over), `ChatPanel`, `QuestionCard` (the helper's options + free text), `Terminal` (xterm.js), `ConfigInspector` (Monaco), `Timeline`, `QueuedScreen` |

The same reducers run live and in replay. Replay is just a different message source.

When api reports `SessionStatus{reconnecting}` (the sandbox link across the mesh dropped), the lab shows a banner and the canvas holds its last state until the fresh snapshot arrives.

The terminal and the editable inspector are the learner's, and read-only with a **Stop** button only while the helper is acting (§6.1). While a session is `queued`, the lab shows its position in line.

---

## 5. Contracts

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/contracts-dark.svg">
  <img src="assets/diagrams/contracts-light.svg" width="100%" alt="Which proto file crosses which boundary, and which package each consumer installs.">
</picture>

```
proto/kubernetes_learning/v1/
  common.proto     ids, timestamps, error
  envmgr.proto     EnvironmentManager service, Sandbox, SandboxStatus
  harness.proto    HarnessFrame + hello / exec / pty / file / fault / check / snapshot-request messages
  topology.proto   Entity, Edge, TopologySnapshot, TopologyDiff, ClusterEvent, TrafficSample
  view.proto       ViewIntent: focus / highlight / annotate / show_config / clear
  session.proto    ClientMessage / ServerMessage for the browser socket, including helper questions and scenario progress
  jobs.proto       ProvisionRequest, ProvisionResult, TeardownRequest for the RabbitMQ work queue
  rest.proto       REST request/response bodies
```

The starting sketch in brief §5 maps directly onto these files.

- **C#:** one NuGet package with messages + gRPC client and server stubs (`Grpc.Tools`). The harness only uses the messages, and trimming drops the rest.
- **Transports:** the same `HarnessFrame` travels as one binary WebSocket message from the harness to envmgr, and as one gRPC stream message from envmgr to api. `jobs.proto` messages travel as RabbitMQ message bodies, covered by the same `buf lint` and `buf breaking` checks.
- **TypeScript:** protobuf-es generated into `@kubernetes-learning-platform/contracts`.
- **Versioning** (CALL): a tag `vX.Y.Z` publishes a release. Every merge to `main` publishes a prerelease `X.Y.Z-main.<run>` so consumers can test unreleased changes. `buf breaking` gates PRs. While on `0.x`, breaking changes are allowed but must bump the minor version.
- **Unblocking others:** Filip publishes a **v0.1 with stubs early in M1**, even if half the messages are placeholders, so `api` and `web` can start against real types.

---

## 6. Key flows

Flow 1 and flows 3 to 4, drawn out:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/session-start-dark.svg">
  <img src="assets/diagrams/session-start-light.svg" width="100%" alt="Starting a session in eight steps, through the RabbitMQ work queue.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/two-streams-dark.svg">
  <img src="assets/diagrams/two-streams-light.svg" width="100%" alt="The state stream from the cluster to the canvas, and the separate intent stream from the helper to the camera.">
</picture>

1. **Start a session.** web `POST /api/sessions` → `SessionService` creates a `queued` session → `ProvisionRequest` to RabbitMQ with a publisher confirm → `envmgr` takes it when it has room and uses a warm sandbox or clones one → `ProvisionResult` → api stores the host and opens `Connect` → harness sends `TopologySnapshot` → `TopologyCache`. With a scenario, `ScenarioRunner` then applies the first step. web opens `/ws/sessions/{id}` and receives `SessionStatus` (with its queue position while waiting), then the snapshot.
2. **Scenario step.** `ScenarioRunner` applies the step's `start` (or `enter` when arriving from the previous step) and any `faults` → it runs the checks about every 3 seconds and on topology changes → once all pass, `ScenarioProgress` goes out and progress is saved → the panel shows **Next**, and nothing changes in the cluster until the learner sends `ScenarioNext`.
3. **Two streams (DECIDED).** The canvas renders **only** from snapshot/diff, with the helper on or off. The camera moves **only** from `ViewIntent`. The helper's words never change the graph.
4. **Helper turn (DECIDED).** `ChatSend` → `AgentRunner.RunTurnAsync` → `HelperState{acting}`, and the terminal and inspector go read-only → LLM → tool calls through `ISandboxSession`, with every command mirrored into the terminal. View tools emit `ViewIntent` through the sink. Every outgoing message gets a `seq`, is persisted, then fanned out.
5. **Helper question (DECIDED).** The helper calls `ask_user(question, options[])` → `AgentQuestion` → `HelperState{waiting}`, and the terminal and inspector become writable again → the question card shows the options and free text → `AgentAnswer` (a normal chat message also counts as the answer, CALL) → the answer becomes the tool's result and the turn continues. If the answer is "reset it", the helper calls `reset_step()`.
6. **Stop.** `HelperStop` → the turn ends at the next tool boundary → `HelperState{idle}`.
7. **Reset (DECIDED).** `StepReset` or `reset_step()` → `ScenarioRunner` reverts the step's faults through the `FaultLedger`, deletes the scenario's namespaces, and applies the step's `start`. **Start over** is separate: it ends the session and starts a new one with a fresh VM (CALL). It's also the only reset for a blank cluster, and for anything changed outside the scenario's namespaces.
8. **Fault.** `kill_node`, from the helper on request or from a scenario's `faults` → harness `FaultHandler` records it in `FaultLedger` → `FaultResult{faultId, targetIds}` → api emits `FaultMarked` → the UI badges the target. Meanwhile the watchers independently report the real effect (NotReady, pods rescheduling).
9. **Replay.** `/session/[id]/replay` pages through `EventsController` and feeds the same reducers.
10. **Mesh link drop** (CALL). The `Connect` stream between api (Hetzner) and envmgr (home) crosses the internet, so it can break. envmgr keeps the harness connection open and the sandbox keeps running. api sets `SessionStatus{reconnecting}`, fails in-flight tool calls with a retryable error, and `SandboxClient` redials with backoff and jitter, because every session reconnects at once. On reattach, envmgr sends the harness a `SnapshotRequest`, the fresh `TopologySnapshot` replaces api's cached topology, and the session is live again. Terminal output during the gap is lost. `envmgr`'s RabbitMQ connection recovers on its own, and requests wait in the queue meanwhile.
11. **Teardown.** `DELETE /api/sessions/{id}` or `IdleReaper` → `TeardownRequest` → envmgr stops and deletes the clone, and acks. The request survives a link drop. envmgr's `Reconciler` enforces `Sandbox__MaxLifetime` as the backstop if api dies. A session cancelled while still queued gets a teardown as soon as its result arrives.
12. **Traffic.** The `start_traffic(demo-web)` tool → harness `TrafficProbe` → `TrafficSample` every ~1 s → the canvas animates Service→Pod edges by hit count. In the stuck-rollout scenario, you *see* v1 pods still answering.

### 6.1 Who drives (DECIDED, [ADR 0002](adr/0002-learner-driven-scenarios-and-scale-target.md))

The terminal and the editable config inspector belong to the learner by default. These states shape `session.proto`, which goes into contracts v0.1.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/helper-turn-dark.svg">
  <img src="assets/diagrams/helper-turn-light.svg" width="100%" alt="The helper is idle, acting or waiting. A turn only starts from the learner's message or answer.">
</picture>

| Helper is | Terminal + inspector | Helper can use |
|---|---|---|
| **Idle** | Writable. Input goes to the shared PTY, a real bash in the VM. Apply sends `ApplyManifest{yaml}`, and the harness applies it. | Nothing, because no turn is running |
| **Acting** on a request | Read-only, with a **Stop** button (CALL). Commands run on the **Exec channel**, so the LLM gets clean stdout/stderr/exit codes, and they're mirrored into the terminal as `agent$ <cmd>` + output (`TerminalOutput{source: agent}`). A chat message sent now waits until the turn ends (CALL). | Observe, view, execute and fault tools |
| **Waiting** on its question | Writable | Nothing until the answer arrives |

---

## 7. Folder structure

### `docs` (parent)
```
docs/
├── README.md            # project hub: overview, repo map, diagram, workspace layout
├── ARCHITECTURE.md      # this file
├── FEATURES.md          # every feature: what the user sees + how it works
├── PROJECT-BRIEF.md     # the original brief
├── adr/                 # architecture decision records, one file per decision (0001: hosting + harness transport, 0002: learner-driven scenarios + scale target)
├── assets/diagrams/     # generate.py and the SVG sheets it writes; edit the script, never an SVG
└── LICENSE
```

### `contracts`
```
contracts/
├── proto/kubernetes_learning/v1/*.proto
├── buf.yaml                       # lint + breaking rules
├── buf.gen.yaml                   # protobuf-es codegen
├── dotnet/KubernetesLearning.Contracts/
│   └── KubernetesLearning.Contracts.csproj   # Grpc.Tools compiles ../../proto at build time
├── ts/
│   ├── package.json               # @kubernetes-learning-platform/contracts
│   └── src/gen/                   # generated, not committed
└── .github/workflows/ci.yml       # → platform/proto-ci.yml
```

### `sandbox`
```
sandbox/
├── src/
│   ├── KubernetesLearning.EnvManager/
│   │   ├── Program.cs
│   │   ├── Grpc/EnvironmentManagerService.cs      # the only "controller"
│   │   ├── Relay/{HarnessRelay,HarnessWebSocketEndpoint}.cs
│   │   ├── Providers/ISandboxProvider.cs
│   │   ├── Providers/Proxmox/{ProxmoxProvider,ProxmoxApiClient,CloudInitWriter}.cs
│   │   ├── Providers/Docker/DockerProvider.cs
│   │   ├── Lifecycle/{SandboxRegistry,StateStore,Reconciler}.cs
│   │   └── Queue/{ProvisionConsumer,TeardownConsumer}.cs
│   ├── KubernetesLearning.Harness/                # PublishAot=true
│   │   ├── Program.cs
│   │   ├── Transport/{IHarnessTransport,WebSocketTransport}.cs
│   │   ├── FrameRouter.cs
│   │   ├── Handlers/{Exec,Pty,File,Fault,Check}Handler.cs
│   │   ├── Faults/{FaultLedger,KillNode,DeletePod,Partition,BadImage}.cs
│   │   ├── Watch/{KubeWatcher,DockerWatcher}.cs
│   │   ├── Topology/{TopologyModel,TopologyPublisher}.cs
│   │   ├── Traffic/TrafficProbe.cs
│   │   ├── Cluster/ClusterBootstrap.cs
│   │   └── Native/Pty.cs                          # P/Invoke via LibraryImport
│   ├── KubernetesLearning.SandboxClient/          # NuGet, consumed by api
│   │   ├── EnvironmentManagerClient.cs
│   │   ├── ISandboxSession.cs, SandboxSession.cs  # request/response correlation, PTY + state streams
│   │   └── Fakes/FakeSandboxSession.cs            # scripted cluster for api tests and web dev
│   └── KubernetesLearning.Sbx/                    # dev CLI: sbx create | exec | watch | destroy
├── tests/
│   ├── EnvManager.Tests/
│   ├── Harness.Tests/
│   └── Integration.Tests/                         # Docker provider + real harness + SandboxClient
├── images/
│   ├── base/                                      # Packer (Proxmox builder) → the Proxmox VM template (CALL)
│   └── scenarios/                                 # custom scenario images, until the `scenarios` repo exists
│       ├── demo-web/                              # v1, v2; replies with its pod name ("typo tag" = a tag that doesn't exist)
│       └── traffic-probe/                         # tiny curl loop used by TrafficProbe
├── Directory.Build.props
└── .github/workflows/{ci,release}.yml             # → platform workflows
```

### `api`
```
api/
├── src/
│   ├── KubernetesLearning.Api/                    # Person 2
│   │   ├── Program.cs
│   │   ├── Controllers/
│   │   │   ├── AuthController.cs
│   │   │   ├── SessionsController.cs
│   │   │   ├── ScenariosController.cs
│   │   │   └── EventsController.cs
│   │   ├── Realtime/{SessionSocketEndpoint,EventFanout,TopologyCache}.cs
│   │   ├── Sessions/{SessionService,SessionRegistry,LiveSession,IdleReaper}.cs
│   │   ├── Provisioning/{ISandboxProvisioner,RabbitMqProvisioner,FakeProvisioner}.cs
│   │   ├── Auth/IAuthProvider.cs                  # + implementation (OPEN)
│   │   ├── Persistence/{AppDbContext,EventStore}.cs
│   │   ├── Persistence/Entities/{User,Session,SessionEvent,ScenarioProgress}.cs
│   │   ├── Persistence/Migrations/
│   │   └── Formatting/ProtoJsonFormatter.cs
│   ├── KubernetesLearning.Scenarios/              # Filip; no LLM dependency
│   │   └── {ScenarioCatalog,ScenarioDefinition,ScenarioRunner}.cs
│   └── KubernetesLearning.Agent/                  # Filip
│       ├── AgentRunner.cs
│       ├── IAgentEventSink.cs
│       ├── Llm/ILlmClient.cs                      # + provider implementation (OPEN)
│       ├── Tools/{ToolRegistry,ExecuteTools,ObserveTools,ViewTools,FaultTools,InteractionTools}.cs
│       ├── Budget/TokenBudget.cs
│       └── Prompts/system.md
├── scenarios/                                     # Filip; moves to the `scenarios` repo once the flow works
│   └── broken-ingress/                            # scenario.yaml, manifests/ (format: ADR 0002 §4)
├── tests/{Api.Tests,Scenarios.Tests,Agent.Tests}/
├── Dockerfile
├── .github/CODEOWNERS                             # Agent/ + Scenarios/ + scenarios/ → Filip
└── .github/workflows/ci.yml
```

### `web`
```
web/
├── src/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                               # scenarios + progress, blank cluster, resume
│   │   ├── login/page.tsx
│   │   └── session/[id]/{page.tsx,replay/page.tsx}
│   ├── components/
│   │   ├── topology/{TopologyCanvas,NodeCard,PodChip,ServiceEdge}.tsx
│   │   ├── topology/layout.ts                     # elkjs
│   │   ├── chat/{ChatPanel,QuestionCard}.tsx
│   │   ├── terminal/Terminal.tsx                  # xterm.js
│   │   ├── inspector/ConfigInspector.tsx          # Monaco
│   │   ├── timeline/Timeline.tsx
│   │   └── session/{ScenarioPanel,QueuedScreen}.tsx
│   ├── lib/{api,socket}.ts
│   └── state/{sessionStore,scenarioStore,topologyReducer,viewReducer}.ts
├── Dockerfile                                     # output: standalone
└── .github/workflows/ci.yml
```

### `platform`
```
platform/
├── .github/workflows/                             # all `on: workflow_call`
│   ├── pr-title.yml           # Conventional Commit PR titles; also runs on platform's own PRs
│   ├── copilot-review.yml     # one Copilot review per PR; also runs on platform's own PRs
│   ├── dotnet-ci.yml          # format check, build, test
│   ├── node-ci.yml            # eslint, prettier, typecheck, test, build
│   ├── proto-ci.yml           # buf lint/breaking, generate, pack, publish
│   ├── container-publish.yml  # buildx → GHCR, multi-arch (sha + semver tags)
│   ├── release-binary.yml     # dotnet publish linux-x64 + linux-arm64 → GitHub Release
│   └── vm-image.yml           # Packer → Proxmox VM template; runs on the self-hosted runner on the Proxmox box
├── lint/
│   ├── .editorconfig
│   ├── Directory.Build.props  # analyzers, warnings-as-errors, LangVersion
│   ├── eslint.config.mjs
│   ├── prettier.config.mjs
│   └── sync.sh                # copy canonical configs into a repo
├── infra/                     # OpenTofu (CALL); state is never committed
│   ├── hetzner/               # server + cloud firewall (hcloud provider)
│   └── proxmox/               # sandbox bridge, resource pool, envmgr user/role/token, runner LXC (bpg/proxmox provider)
├── deploy/
│   ├── hetzner/
│   │   ├── docker-compose.yml # proxy, web, api, postgres, rabbitmq (image tags pinned via .env); Caddy and RabbitMQ published on the mesh address only
│   │   ├── Caddyfile          # tls internal; / → web, /api + /ws → api
│   │   ├── api.env.example
│   │   └── install.sh         # compose up, ordered after wg-quick
│   ├── proxmox/
│   │   ├── envmgr.service
│   │   ├── envmgr.env.example
│   │   ├── nftables.conf      # sandbox bridge isolation + gRPC port only from the Hetzner box
│   │   └── install.sh         # fetch the envmgr release, install the unit and the rules
│   └── wireguard/             # peer config templates: hetzner, proxmox, laptop (keys are never committed)
└── dev/
    └── docker-compose.dev.yml # postgres + api (fake sandbox, no broker), plus rabbitmq when using the docker sandbox
```

---

## 8. CI/CD & shared tooling (Filip)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/platform-dark.svg">
  <img src="assets/diagrams/platform-light.svg" width="100%" alt="Which reusable workflow ships what, and which machine it ends up on.">
</picture>

- **Reusable workflows** live in `platform/.github/workflows`. Each repo's `ci.yml` is a short `uses: kubernetes-learning-platform/platform/.github/workflows/dotnet-ci.yml@main`. If `platform` is private, set it to "accessible from repositories in the organization" under Actions settings.
- **Lint** (CALL): C# uses `.editorconfig` + `dotnet format --verify-no-changes` + `TreatWarningsAsErrors` + `AnalysisLevel=latest-recommended`. TS uses ESLint flat config + Prettier + `tsc --noEmit`. Proto uses `buf lint`. Canonical copies live in `platform/lint/`, and the reusable CI fails if a repo's copy drifts.
- **Architectures** (CALL): envmgr and harness publish for **linux-x64 and linux-arm64 from M1**, and scenario images and the DinD sandbox image are multi-arch. The Docker provider on Apple Silicon runs linux/arm64 containers. The `api` and `web` images are multi-arch too, so the Hetzner box can be x64 or ARM. The VM template stays x64-only, for the Proxmox box.
- **Releases:** tags trigger releases. `api`/`web` → GHCR images. `sandbox` → envmgr + harness binaries, SandboxClient NuGet, then `vm-image.yml` builds a new Proxmox VM template with the matching harness baked in. Nothing pulls from the internet at runtime (DECIDED).
- **Self-hosted runner** (CALL): GitHub-hosted runners can't reach Proxmox, so `vm-image.yml` runs on a self-hosted runner in an LXC on the Proxmox box. Every other workflow stays on GitHub-hosted runners.
- **Infrastructure as code** (CALL, [ADR 0001](adr/0001-hosting-and-harness-transport.md)): OpenTofu in `platform/infra/` creates the long-lived pieces: the Hetzner server and its cloud firewall, and on Proxmox the sandbox bridge, the `kl-sandboxes` pool, envmgr's user, role and token, and the runner LXC. Packer in `sandbox/images/base/` builds the VM template. **Sandboxes themselves are not IaC:** envmgr's reconcile loop owns them, because per-session state files and a plan/apply cycle on every create would be slow and go stale whenever a VM is deleted outside the tool.
- **Deploy:** `platform/deploy/` has one folder per machine. The Hetzner box runs the Compose stack, including RabbitMQ, published only on its mesh address. The Proxmox box runs envmgr as a systemd unit plus static nftables rules. `deploy/wireguard/` holds peer config templates; private keys are never committed.
- **Dependency bumps** (CALL): Renovate opens PRs in `sandbox`/`api`/`web` when `contracts` or `SandboxClient` publishes.
- **Branching** (CALL): trunk-based, short-lived branches, squash merge, Conventional Commit PR titles.
- **Config** is env vars only (DECIDED). For example, api uses `ConnectionStrings__Db`, `RabbitMq__Url`, `Llm__Provider`, `Llm__ApiKey`, `Session__IdleMinutes`, `Agent__TokenBudget`, `Agent__MaxConcurrentTurns`, `Sandbox__Mode=Real|Fake`. envmgr uses `Provider=Proxmox|Docker`, `Grpc__Listen`, `Harness__Listen`, `RabbitMq__Url`, `Proxmox__Url`, `Proxmox__TokenId`, `Proxmox__TokenSecret`, `Proxmox__Node`, `Proxmox__TemplateId`, `Proxmox__Pool`, `Sandbox__Subnet`, `Sandbox__MaxConcurrent`, `WarmPool__Size`, `StateDir`, `Sandbox__MaxLifetime`. The harness uses `Harness__Url`, `Harness__SandboxId`, `Harness__Token`.

### Local development without KVM

| Person | Runs locally |
|---|---|
| Filip | envmgr via `dotnet run` with `Provider=Docker`, plus RabbitMQ from `platform/dev`. The harness (linux-arm64 build) runs inside a privileged DinD container and dials envmgr over WebSocket, the same way it does on Proxmox. The dev Mac is an Apple M5 with 16 GB, so it fits **one sandbox at a time** (~4 GB in Docker Desktop). The Proxmox provider is tested on the Proxmox box itself. |
| Person 2 | `platform/dev` compose: Postgres + api with `Sandbox__Mode=Fake` (`FakeSandboxSession` plays a scripted cluster, and no broker is needed). Switches to `Real` once Filip's Docker provider works. |
| Person 3 | The same compose. The fake sandbox drives the socket, so the canvas, scenario panel, chat and terminal can be built before any real sandbox exists. |

---

## 9. Milestones by person

| | Filip | Person 2 | Person 3 |
|---|---|---|---|
| **M1 Sandbox** | `platform` repo: shared workflows + lint; `contracts` v0.1; envmgr with Docker provider, then Proxmox provider; harness exec over WebSocket; Packer VM template; Proxmox side as code (bridge, pool, token); `FakeSandboxSession`; measure real sandbox RAM | api skeleton: auth abstraction, sessions CRUD, Postgres + migrations, WS endpoint with fan-out against the fake | App shell, routes, socket client, topology canvas rendering the fake's snapshot/diffs |
| **M2 Scenarios** | Harness PTY, checks and reset; `ScenarioRunner`; first scenario; RabbitMQ + `jobs.proto`; `envmgr` consumer; Hetzner box + WireGuard mesh as code, first deploy of the stack | Scenario and progress endpoints, queue integration, `queued` state, PTY plumbing, batched terminal writes, idle reaper | Home screen, scenario panel (goal, checks, hints, reset), xterm.js terminal, queued state |
| **M3 Live view** | Watchers → `TopologyModel` → snapshot/diff, including Ingress | `TopologyCache`, persist-then-broadcast, `Resync` | Real canvas, Monaco inspector + Apply |
| **M4 Helper** | Agent loop, `ILlmClient`, tools, `ask_user`, `reset_step`, view tools, fault tools + ledger, token budget | `AgentRunner` in `LiveSession`, `HelperState`, Stop, LLM limits, chat streaming | Chat panel with streaming, question card, intent-driven camera and notes on the canvas |
| **M5 Scenarios + scale** | `scenarios` repo, the full 3–5 scenarios, CI scenario tests, traffic probe, recorded fallback sessions | Load test, `EventsController` | Timeline + replay, traffic animation, polish |

The core works and can be demonstrated before any LLM work, because the product must work without the helper (CALL).

**Stretch** (after M5): BYO repo (egress, in-VM builds, opening apps in the browser), `add_node` / `remove_node`, real VMs as nodes, KubeVirt provider, spectator mode.

---

## 10. Technical risks (read before M1)

1. **The official Kubernetes .NET client's AOT build has no watch support.** `KubernetesClient.Aot` omits `Watcher` and kubeconfig file loading (verified in the client's docs). The harness needs another route: either `kubectl get <kind> -A -w --output-watch-events -o json` subprocesses parsed with source-generated `System.Text.Json`, or a hand-rolled `?watch=true` HTTP stream. Recommendation: kubectl subprocesses first, since kubectl is already in the image.
2. **PTY in .NET.** There's no built-in API. Use `openpty` + spawn with a new session and controlling TTY. **Never call `fork()` from a running .NET process.** Budget real time for this, or shell through `script`/`setsid` as a fallback.
3. **The api ↔ envmgr link crosses the internet.** A blip in the home connection breaks the `Connect` stream. Flow 10 (reconnect, `SnapshotRequest`, fresh snapshot) has to work from M1, not as polish. Test it by restarting WireGuard in the middle of a scenario.
4. **Demo day depends on two networks.** Home power and internet keep the Proxmox box reachable, and the venue must allow outbound UDP for WireGuard. Test from the venue beforehand and keep a phone hotspot as a backup. The recorded fallback sessions are served from the Hetzner box, so they play even when the Proxmox box is unreachable.
5. **envmgr runs on the Proxmox host and is the only thing a sandbox can reach.** Users get a real bash in the VM, so a bug in the harness endpoint is a host bug. Keep that endpoint tiny (token check, then frames), and move envmgr into an LXC if it grows ([ADR 0001](adr/0001-hosting-and-harness-transport.md)).
6. **Proxmox details.** `cicustom` snippets need the `snippets` content type enabled on the storage envmgr writes to. Linked clones need the template on storage that supports them (LVM-thin, ZFS, or qcow2 on a directory).
7. **Compose and WireGuard start order.** Caddy is published only on `10.66.0.1`, so Docker must start after `wg-quick@wg0`, or the port binding fails at boot.
8. **GitHub Packages needs a token to install, even for public packages.** Each person creates a classic PAT with `read:packages` once, for `nuget.config` and `.npmrc`. CI uses `GITHUB_TOKEN`, but each consuming repo must be granted access to the package.
9. **Required reviews and branch protection on private repos need a paid plan** (or GitHub Education's Team plan). On a free org with private repos, CODEOWNERS only requests reviews and can't enforce them.
10. **Docker provider memory.** 3–4 GB per sandbox inside Docker Desktop's VM. Raise its memory limit.
11. **RabbitMQ is one more service, and it can be down.** A message published while disconnected is lost, so `api` uses publisher confirms and returns "try again" when the broker can't be reached. Consumers must handle redeliveries. It also shares the small Hetzner box with the rest of the stack, so measure its memory.
12. **Checks run real commands in every sandbox.** They run every few seconds, so each one must stay cheap.
13. **Scenario reset only covers the scenario's namespaces.** Scenarios must keep their resources inside them. Anything else needs **Start over**.

---

## 11. Open questions

Carried from the brief: LLM provider + token budget · auth mechanism (a light one is enough, since the stack is mesh-only) · egress policy (deferred with BYO; MVP sandboxes are fully offline).

Resolved by [ADR 0001](adr/0001-hosting-and-harness-transport.md): demo host OS (Proxmox VE on the home server PC) · VMM (Proxmox's QEMU/KVM) · VM image tooling (Packer, CALL).

Resolved by [ADR 0002](adr/0002-learner-driven-scenarios-and-scale-target.md): the final demo date (by June 2027).

New:
- **The scenario list,** and whether Helm is included.
- **Proxmox box RAM:** the home PC's RAM sets `Sandbox__MaxConcurrent` and `WarmPool__Size` for the demo, and how many graders can try at once.
- **Hetzner box size,** now that it also runs RabbitMQ.
- **Event log retention:** how long to keep `session_events` for finished sessions.
- **HTTPS name:** Caddy's internal CA on the mesh address works today. A real domain with a DNS-01 Let's Encrypt certificate would avoid installing a CA on every mesh device.
- **Repo visibility:** public or private? Affects branch protection (risk 9) and whether the Hetzner box and the self-hosted runner need a GHCR login to pull images.
- **Course requirements & capacity:** any course checkpoints, rough hours per person per week, and anything the course requires (evidence of individual contribution, where code must be hosted). This decides which M5 items and stretch goals make the cut.
- **Final project name:** see below.

## 12. Naming

"kubernetes-learning" is a placeholder. The GitHub org is already `kubernetes-learning-platform`, and the npm scope must match it because GitHub Packages requires that. The placeholder also appears in: NuGet package IDs, C# root namespaces (`KubernetesLearning.*`), the proto package (`kubernetes_learning.v1`), the state/config dirs (`/var/lib/kubernetes-learning`, `/etc/kubernetes-learning`), systemd unit names, and the `kl-` prefix on Proxmox names (`kl-sandboxes`, `kl-sandbox`, `kl-sbx-<id>`). **Rename before `contracts` reaches 1.0.** After that, renaming the proto package is a breaking wire change. Before then it's a find-and-replace.
