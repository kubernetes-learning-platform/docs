# kubernetes-learning — Architecture & Repository Plan

> Planning output, 2026-11-02. Builds on the original brief in [PROJECT-BRIEF.md](PROJECT-BRIEF.md), which is still the source for product intent, sandbox design and the agent tool list. This document decides **how the work is split into repos, services and code**.
>
> **"kubernetes-learning" is a placeholder name** (the old working name is dropped). See [§12](#12-naming) for where the name appears and when to replace it.
>
> Labels, same as the brief: **DECIDED** = agreed by the team · **DEFAULT** = proposed, not objected to · **OPEN** = not decided. New label: **CALL** = chosen during this planning pass to keep things moving; change freely.

---

## 0. At a glance

| | Count | What |
|---|---|---|
| **Repos** | **6** | `docs` (parent), `contracts`, `sandbox`, `api`, `web`, `platform` |
| **Services we write** | **4** | `web`, `api`, `envmgr`, `harness` |
| **Off-the-shelf services** | **2** | Postgres, Caddy (reverse proxy, CALL) |
| **Libraries we write** | **3** | Contracts (C# + TS), SandboxClient, Agent |
| **REST controllers** | **4** | Auth, Sessions, Lessons, Events (+ 1 WebSocket endpoint) |
| **gRPC services** | **1** | EnvironmentManager (in `envmgr`) |
| **Other build outputs** | **2** | VM base image, lesson demo images |

### Scope decisions (DECIDED 2026-11-02)

| Topic | Decision | Consequence |
|---|---|---|
| **Demo shape** | **The presenter drives** on a projector, with 1–2 extra sessions for graders to try | Warm pool of 1–2 · LAN only · no spectator mode · light auth is enough · the mobile layout is nice-to-have |
| **Lessons** | **Checkpoints + replay** | Each lesson step has a checkpoint verified against the live topology, and the agent gets nudged back if it drifts. If the LLM is unavailable, the demo plays a recorded session through replay. |
| **BYO repo** | **Stretch goal** | MVP sandboxes are fully offline. Registry/package egress, building in the VM and opening apps in the browser all come after M4. |
| **Traffic** | **Static edges + lesson probe** | `routes-to` edges come from Endpoints. demo-web replies with its pod name, and a probe pod lets the canvas animate hits per pod. No network plugin changes. |

---

## 1. Team & ownership

| Person | Owns | DECIDED |
|---|---|---|
| **Filip** | Infra for every repo (CI, lint, releases, deploy), `contracts`, `sandbox` (envmgr + harness + VM image), the **Agent** library and the curated lessons | ✅ |
| **Person 2** | `api`: auth, sessions, WebSocket gateway, persistence, event log, control lock | ✅ |
| **Person 3** | `web`: topology canvas, chat, terminal, config inspector, timeline/replay | ✅ |

People help across lines when needed (DECIDED). Filip has the most surface area, but most of it (contracts, CI, sandbox) has to exist first anyway, before `api` and `web` can go far.

Ownership is enforced by repo boundaries, plus a `CODEOWNERS` file in `api` that assigns `src/KubernetesLearning.Agent/` and `lessons/` to Filip.

---

## 2. Repositories

All six live in the GitHub organization [`kubernetes-learning-platform`](https://github.com/kubernetes-learning-platform), so container images, packages and releases sit together. GitHub has no nested repos, so the org is the container and `docs` is the parent repo everything links from.

| Repo | Contains | Ships | Owner |
|---|---|---|---|
| **`docs`** (parent) | Architecture, features, the original brief, ADRs. The hub that links every other repo. | Nothing | Filip (everyone contributes) |
| **`contracts`** | Protobuf schema for the whole system + codegen | NuGet `KubernetesLearning.Contracts`, npm `@kubernetes-learning-platform/contracts` → GitHub Packages | Filip |
| **`sandbox`** | `envmgr`, `harness`, `SandboxClient` library, dev CLI, VM base image definition, lesson demo images | envmgr binary + harness binary → GitHub Releases · NuGet `KubernetesLearning.SandboxClient` · VM image → Releases · lesson images → GHCR | Filip |
| **`api`** | ASP.NET Core backend + Agent library + lesson definitions | `api` image → GHCR | Person 2 (Agent + lessons: Filip) |
| **`web`** | Next.js frontend | `web` image → GHCR | Person 3 |
| **`platform`** | Reusable CI workflows, canonical lint configs, deploy files (Compose, Caddyfile, systemd unit, env examples), dev Compose | Nothing at runtime; other repos call its workflows | Filip |

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

### Why this shape (CALL)

- **Grouped by owner, not one repo per service.** Nine repos for three people is overhead with no payoff.
- **envmgr + harness + SandboxClient share a repo.** They are the two ends of one private protocol and the client for it. A protocol change is one PR, and one CI run can test all three together (Docker provider, real harness, real client).
- **SandboxClient lives in `sandbox`, not `api`.** Everything about talking to a sandbox belongs to Filip. Person 2 consumes a clean `ISandboxSession` interface and never touches frame correlation or vsock details.
- **The Agent lives in `api`, not its own repo.** It runs in the api process (DECIDED) and changes constantly during M2–M4. A separate repo would mean publishing a package for every prompt or tool tweak.
- **`contracts` is its own repo** because everyone depends on it. It gets SemVer versions, `buf lint`, and `buf breaking` against `main` in CI.
- **`docs` is separate from `platform`** (DECIDED by Filip: the parent repo holds the documentation). Docs changes like a new ADR or a lesson idea don't go through the CI/deploy repo.
- **`platform` holds anything shared that isn't code a service runs or documentation.** Each other repo's CI file is about 10 lines that call a reusable workflow from here.

### Rejected repo layouts

- **Monorepo with CODEOWNERS.** Simplest for keeping contracts in sync, but the team wants each person's work to be clearly theirs at repo level.
- **One repo per service/library (8–9 repos).** Too much release and versioning overhead for three people.
- **Agent in its own repo.** The publish → bump → test loop is too slow for the most-iterated code in the project.

---

## 3. Runtime architecture

```mermaid
flowchart LR
    browser["Browser"]
    llm["LLM API"]

    subgraph host["Demo host (Linux + KVM)"]
        subgraph compose["Docker Compose"]
            proxy["proxy<br/>Caddy"]
            web["web<br/>Next.js"]
            api["api<br/>ASP.NET Core + agent"]
            db[("Postgres<br/>users, sessions, event log")]
        end
        envmgr["envmgr<br/>systemd daemon"]
        subgraph vm["Sandbox VM (one per session)"]
            harness["harness<br/>Native AOT"]
            k3d["k3d cluster<br/>cp, w1, w2"]
        end
    end

    browser -->|HTTPS| proxy
    proxy --> web
    proxy -->|"REST + WebSocket (protobuf)"| api
    api --> db
    api -->|HTTPS| llm
    api -->|"gRPC over unix socket"| envmgr
    envmgr <-->|vsock| harness
    harness -->|"kubectl, docker, watches"| k3d
```

Everything in the brief's §2–§5 still holds. Additions from this plan:

- **Caddy reverse proxy** (CALL). One origin for the browser: `/` → web, `/api/*` and `/ws/*` → api. Cookies stay same-origin and there's no CORS setup. It's off-the-shelf like Postgres, so the DECIDED rule "only web and api are images we build" still holds. Drop it if it gets in the way.
- **Harness traffic reaches api through envmgr** (brief §5's recommendation, adopted as CALL). envmgr relays each harness connection as one bidirectional gRPC `Connect` stream per session. api has one code path regardless of provider, and the VM never needs a route to api.

---

## 4. Services and their entry points

### 4.1 `api` — ASP.NET Core (.NET 10) · Person 2 + Filip

**REST controllers** (JSON bodies, defined as Protobuf messages in `rest.proto`, serialized with proto3 JSON mapping, CALL):

| Controller | Routes | Purpose |
|---|---|---|
| `AuthController` | `POST /api/auth/login` · `POST /api/auth/logout` · `GET /api/auth/me` | Delegates to `IAuthProvider`. The mechanism is **OPEN**, but the abstraction is fixed. |
| `SessionsController` | `POST /api/sessions` (body: `lessonId?`, `repoUrl?` is stretch) · `GET /api/sessions` · `GET /api/sessions/{id}` · `DELETE /api/sessions/{id}` | Start/list/inspect/end. Enforces one active session per user (DEFAULT). |
| `LessonsController` | `GET /api/lessons` · `GET /api/lessons/{id}` | Curated lesson catalog for the home screen. |
| `EventsController` | `GET /api/sessions/{id}/events?afterSeq=&limit=` | Event log pages for timeline + replay. Returns `application/x-protobuf` `EventBatch`. |

**WebSocket endpoint** (minimal API, not a controller): `GET /ws/sessions/{id}`. Binary frames, each one `ClientMessage` or `ServerMessage` from `session.proto`.

| Browser → api (`ClientMessage`) | api → Browser (`ServerMessage`, each with a per-session `seq`) |
|---|---|
| `ChatSend` · `TerminalInput` · `TerminalResize` · `ApplyManifest{yaml}` · `ControlTake` · `ControlRelease` · `AgentPause` · `AgentResume` · `Resync{afterSeq}` | `ChatDelta` · `ChatMessage` · `ToolCallStarted` · `ToolCallFinished` · `TopologySnapshot` · `TopologyDiff` · `ClusterEvent` · `ViewIntent` · `FaultMarked` · `FaultReverted` · `TrafficSample` · `LessonProgress` · `TerminalOutput{source: user\|agent}` · `ControlState` · `SessionStatus` · `Error` |

Health: `MapHealthChecks("/healthz")`, not a controller.

**Internal services** (`KubernetesLearning.Api`, Person 2):

| Area | Classes | Role |
|---|---|---|
| Sessions | `SessionService`, `SessionRegistry`, `LiveSession`, `ControlLock`, `IdleReaper` | Create/end sessions. Each live session holds its sandbox session, agent runner, subscribers and control lock. `IdleReaper` ends sessions idle > ~30 min (DEFAULT). |
| Realtime | `SessionSocketEndpoint`, `EventFanout`, `TopologyCache` | Assigns `seq`, **persists first, then broadcasts**. Keeps the latest topology so a fresh socket gets a snapshot immediately. `Resync` replays from the store. |
| Persistence | `AppDbContext` (EF Core + Npgsql), `EventStore`, migrations | Tables below. |
| Auth | `IAuthProvider` + one implementation | Implementation **OPEN**. |

**Agent library** (`KubernetesLearning.Agent`, Filip). No ASP.NET or EF dependency:

| Area | Classes | Role |
|---|---|---|
| Loop | `AgentRunner` | One per live session. `RunTurnAsync(userMessage)`. Stops at the next tool boundary when paused or when the user takes control. |
| Seam to api | `IAgentEventSink` | Agent emits chat deltas, tool-call events and view intents. api implements it with `EventFanout`. |
| Seam to sandbox | `ISandboxSession` (from SandboxClient) | Exec, files, faults, cluster state. |
| LLM | `ILlmClient` + one implementation | Provider **OPEN**. |
| Tools | `ToolRegistry`, `ExecuteTools`, `ObserveTools`, `ViewTools`, `FaultTools`, `HandoverTools` | The typed tool set from brief §6, plus `revert_fault` and `start_traffic(service)` / `stop_traffic()` for the lesson traffic probe. The cluster stays fixed at cp/w1/w2 for the MVP. `add_node` / `remove_node` (k3d node create/delete) are stretch goals. The topology is node-agnostic, so new nodes would just appear (CALL). |
| Budget | `TokenBudget` | Hard per-session cap (DEFAULT, number **OPEN**). |
| Lessons | `LessonCatalog`, `LessonDefinition`, `CheckpointEvaluator` | Loads `lessons/*.yaml`: goal, system-prompt addendum, and steps, each with a **checkpoint** (a predicate over the topology, e.g. "deployment demo-web has 3 Running pods"). `CheckpointEvaluator` checks each one against the live topology from `ISandboxSession`, emits `LessonProgress`, and nudges the agent if a checkpoint doesn't pass within its timeout. A lesson can name a **fallback recording** (a past session id) that the presenter replays if the LLM is unavailable. |

**Database** (CALL):

```
users           (id, display_name, auth_subject, created_at)
sessions        (id, user_id, sandbox_id, lesson_id?, repo_url?, status, tokens_used, created_at, ended_at?)
session_events  (session_id, seq, at, kind, payload bytea)   PK (session_id, seq)  -- append-only
```

`session_events.payload` is the serialized `ServerMessage`, so replay feeds the browser **exactly** what it saw live.

### 4.2 `envmgr` — .NET 10 self-contained daemon · Filip

No REST controllers. **One gRPC service** on `/run/kubernetes-learning/envmgr.sock`:

| gRPC `EnvironmentManager` | Purpose |
|---|---|
| `CreateSandbox` | Takes a VM from the warm pool (or boots one). Returns sandbox id + status. |
| `DestroySandbox` | Tears down the VM, its unit, taps and state. |
| `GetSandbox` / `ListSandboxes` | Status. `ListSandboxes` is for debugging and demo (CALL). |
| `WatchSandbox` | Stream: `booting → cluster_ready → failed / destroyed`. |
| `Connect` | Bidirectional `HarnessFrame` stream. envmgr pipes it to the harness. |

**Harness listeners** (where the harness dials in):
- VMM provider: a per-VM unix socket `<state>/vms/<id>/v.sock_5000`. Firecracker forwards a guest connection to `CID 2 : port 5000` to exactly this path (verified in Firecracker's vsock docs). Cloud Hypervisor uses the same hybrid-vsock scheme.
- Docker provider: WebSocket `/harness` on a TCP port. Each sandbox gets a one-time token injected at create time (CALL), because unlike vsock this port is reachable from containers.

**Internal services**:

| Area | Classes | Role |
|---|---|---|
| Providers | `ISandboxProvider`, `VmmProvider` (Firecracker **or** Cloud Hypervisor, **OPEN**), `DockerProvider` (privileged DinD + k3d) | Create / destroy / inspect / adopt |
| Lifecycle | `SandboxRegistry`, `StateStore` (`/var/lib/kubernetes-learning`), `Adopter`, `WarmPool`, `TtlReaper` | Re-adopt VMs after restart (DECIDED). Keep N warm VMs (DEFAULT). Hard max-lifetime backstop. |
| Relay | `HarnessRelay`, `VsockListener`, `HarnessWebSocketEndpoint` | Pairs each harness connection with its api `Connect` stream and buffers until both sides are present. |
| Host | `SystemdRunner` (`systemd-run --unit=kl-vm-<id>`), `NetworkManager` (bridge, taps, nftables egress) | Host plumbing |

### 4.3 `harness` — .NET 10 Native AOT, inside every VM · Filip

No controllers. One connection, one **frame router**:

| Component | Role |
|---|---|
| `Program` / `HarnessHost` | Parses `--connect vsock://2:5000` or `--connect wss://…`, dials with retry, sends `Hello{sandboxId, version}`. |
| `IHarnessTransport` → `VsockTransport`, `WebSocketTransport` | Length-prefixed `HarnessFrame`s |
| `FrameRouter` | Dispatches by `oneof body` |
| `ExecHandler` · `PtyHandler` · `FileHandler` · `FaultHandler` | The four request handlers |
| `FaultLedger` | Records every fault (id, kind, targets, undo action) so it can be **reverted** and the UI can **mark** it |
| `TrafficProbe` | Starts a probe pod (baked image) that curls a service in a loop. It tails the probe's logs, where demo-web replies with its pod name, and emits `TrafficSample{serviceId, hitsByPod}` about once a second. |
| `KubeWatcher` · `DockerWatcher` | Watch nodes, pods, deployments, replicasets, services, endpoints, events, plus Docker events for node containers |
| `TopologyModel` → `TopologyPublisher` | Normalized graph. Sends a snapshot on connect, then revisioned diffs. |
| `ClusterBootstrap` | Confirms the k3d cluster is healthy and reports `cluster_ready` |

### 4.4 `web` — Next.js (App Router) · Person 3

No controllers or API routes. It's a pure client of `api` through the proxy.

| Route | Screen |
|---|---|
| `/login` | Auth (form depends on the OPEN auth choice) |
| `/` | Lesson list, "free chat" start, BYO repo URL input, resume active session |
| `/session/[id]` | The lab: topology canvas · chat · terminal · config inspector · control bar |
| `/session/[id]/replay` | The same lab, fed from `GET …/events` instead of the socket |

| Module | Role |
|---|---|
| `lib/socket.ts` | WebSocket client: protobuf-es encode/decode, reconnect + `Resync` |
| `lib/api.ts` | REST client |
| `state/` (Zustand, CALL) | `topologyReducer` (applies snapshot/diff by revision), `viewReducer` (intents → camera), chat, control |
| `components/` | `TopologyCanvas` (React Flow + elkjs auto-layout, CALL), `ChatPanel`, `Terminal` (xterm.js), `ConfigInspector` (Monaco), `Timeline`, `ControlBar` |

The same reducers run live and in replay. Replay is just a different message source.

---

## 5. Contracts

```
proto/kubernetes_learning/v1/
  common.proto     ids, timestamps, error
  envmgr.proto     EnvironmentManager service, Sandbox, SandboxStatus
  harness.proto    HarnessFrame + exec / pty / file / fault messages
  topology.proto   Entity, Edge, TopologySnapshot, TopologyDiff, ClusterEvent, TrafficSample
  view.proto       ViewIntent: focus / highlight / annotate / show_config / clear
  session.proto    ClientMessage / ServerMessage for the browser socket
  rest.proto       REST request/response bodies
```

The starting sketch in brief §5 maps directly onto these files.

- **C#:** one NuGet package with messages + gRPC client and server stubs (`Grpc.Tools`). The harness only uses the messages, and trimming drops the rest.
- **TypeScript:** protobuf-es generated into `@kubernetes-learning-platform/contracts`.
- **Versioning** (CALL): a tag `vX.Y.Z` publishes a release. Every merge to `main` publishes a prerelease `X.Y.Z-main.<run>` so consumers can test unreleased changes. `buf breaking` gates PRs. While on `0.x`, breaking changes are allowed but must bump the minor version.
- **Unblocking others:** Filip publishes a **v0.1 with stubs early in M1**, even if half the messages are placeholders, so `api` and `web` can start against real types.

---

## 6. Key flows

1. **Start a session.** web `POST /api/sessions` → `SessionService` → envmgr `CreateSandbox` (warm pool) → api opens `Connect` → harness sends `TopologySnapshot` → `TopologyCache`. web opens `/ws/sessions/{id}` and immediately receives `SessionStatus` + the snapshot.
2. **Agent turn.** `ChatSend` → `AgentRunner.RunTurnAsync` (which tools it may use depends on who holds control, see §6.1) → LLM → tool calls through `ISandboxSession`. View tools emit `ViewIntent` through the sink. Every outgoing message gets a `seq`, is persisted, then fanned out.
3. **Two streams (DECIDED).** The canvas renders **only** from snapshot/diff. The camera moves **only** from `ViewIntent`. The agent's words never change the graph.
4. **User takeover.** `ControlTake` → the agent stops at its next tool boundary → the terminal and Monaco become writable → `ControlRelease` (or the agent's `pause_for_user` finishes) → the agent gets a takeover summary and resumes (§6.1).
5. **Fault.** `kill_node` → harness `FaultHandler` records it in `FaultLedger` → `FaultResult{faultId, targetIds}` → api emits `FaultMarked` → the UI badges the target. Meanwhile the watchers independently report the real effect (NotReady, pods rescheduling).
6. **Replay.** `/session/[id]/replay` pages through `EventsController` and feeds the same reducers.
7. **Teardown.** `DELETE /api/sessions/{id}` or `IdleReaper` → `DestroySandbox`. envmgr's `TtlReaper` is the backstop if api dies.
8. **Lesson checkpoint.** The agent works through step N → `CheckpointEvaluator` watches the topology → once it passes, `LessonProgress{step: N, passed}` goes out and the agent is told to move on. On timeout, the agent gets a nudge: "checkpoint N not met: expected X, cluster shows Y".
9. **Traffic.** The `start_traffic(demo-web)` tool → harness `TrafficProbe` → `TrafficSample` every ~1 s → the canvas animates Service→Pod edges by hit count. During the stuck-rollout lesson, the audience *sees* v1 pods still answering.

### 6.1 Control & terminal semantics (CALL)

These are fixed up front because they shape `harness.proto` and `session.proto`, which go into contracts v0.1.

| | Agent drives (default) | User drives (after `ControlTake`) |
|---|---|---|
| **Terminal** | Read-only. Agent commands run on the **Exec channel**, so the LLM gets clean stdout/stderr/exit codes. They're mirrored into the terminal as `agent$ <cmd>` + output (`TerminalOutput{source: agent}`). | Writable. Input goes to the shared PTY, a real bash in the VM. |
| **Config inspector** | Read-only (Monaco) | Editable, with an **Apply** button → `ApplyManifest{yaml}` → harness applies it |
| **Chat** | Open | **Still open.** The agent can answer, but only with observe + view tools. Execute and fault tools are refused until control comes back. |
| **On hand-back** | — | The agent receives a **takeover summary** built from the event log: the user's terminal input lines and the topology changes since `ControlTake`. That's how lesson step 6 ("the user fixes the tag") gets acknowledged. |

---

## 7. Folder structure

### `docs` (parent)
```
docs/
├── README.md            # project hub: overview, repo map, diagram, workspace layout
├── ARCHITECTURE.md      # this file
├── FEATURES.md          # every feature: what the user sees + how it works
├── PROJECT-BRIEF.md     # the original brief
├── adr/                 # architecture decision records, one file per decision
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
│   │   ├── Relay/{HarnessRelay,VsockListener,HarnessWebSocketEndpoint}.cs
│   │   ├── Providers/ISandboxProvider.cs
│   │   ├── Providers/Vmm/VmmProvider.cs           # Firecracker or Cloud Hypervisor (OPEN)
│   │   ├── Providers/Docker/DockerProvider.cs
│   │   ├── Lifecycle/{SandboxRegistry,StateStore,Adopter,WarmPool,TtlReaper}.cs
│   │   └── Host/{SystemdRunner,NetworkManager}.cs
│   ├── KubernetesLearning.Harness/                # PublishAot=true
│   │   ├── Program.cs
│   │   ├── Transport/{IHarnessTransport,VsockTransport,WebSocketTransport}.cs
│   │   ├── FrameRouter.cs
│   │   ├── Handlers/{Exec,Pty,File,Fault}Handler.cs
│   │   ├── Faults/{FaultLedger,KillNode,DeletePod,Partition,BadImage}.cs
│   │   ├── Watch/{KubeWatcher,DockerWatcher}.cs
│   │   ├── Topology/{TopologyModel,TopologyPublisher}.cs
│   │   ├── Traffic/TrafficProbe.cs
│   │   ├── Cluster/ClusterBootstrap.cs
│   │   └── Native/{Pty,VsockEndPoint}.cs          # P/Invoke via LibraryImport
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
│   ├── base/                                      # mkosi or Packer (OPEN)
│   └── lessons/
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
│   │   │   ├── LessonsController.cs
│   │   │   └── EventsController.cs
│   │   ├── Realtime/{SessionSocketEndpoint,EventFanout,TopologyCache}.cs
│   │   ├── Sessions/{SessionService,SessionRegistry,LiveSession,ControlLock,IdleReaper}.cs
│   │   ├── Auth/IAuthProvider.cs                  # + implementation (OPEN)
│   │   ├── Persistence/{AppDbContext,EventStore}.cs
│   │   ├── Persistence/Entities/{User,Session,SessionEvent}.cs
│   │   ├── Persistence/Migrations/
│   │   └── Formatting/ProtoJsonFormatter.cs
│   └── KubernetesLearning.Agent/                  # Filip
│       ├── AgentRunner.cs
│       ├── IAgentEventSink.cs
│       ├── Llm/ILlmClient.cs                      # + provider implementation (OPEN)
│       ├── Tools/{ToolRegistry,ExecuteTools,ObserveTools,ViewTools,FaultTools,HandoverTools}.cs
│       ├── Budget/TokenBudget.cs
│       ├── Prompts/system.md
│       └── Lessons/{LessonCatalog,LessonDefinition,CheckpointEvaluator}.cs
├── lessons/                                       # Filip
│   └── rollout-stuck.yaml
├── tests/{Api.Tests,Agent.Tests}/
├── Dockerfile
├── .github/CODEOWNERS                             # Agent/ + lessons/ → Filip
└── .github/workflows/ci.yml
```

### `web`
```
web/
├── src/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                               # lessons, start, BYO repo
│   │   ├── login/page.tsx
│   │   └── session/[id]/{page.tsx,replay/page.tsx}
│   ├── components/
│   │   ├── topology/{TopologyCanvas,NodeCard,PodChip,ServiceEdge}.tsx
│   │   ├── topology/layout.ts                     # elkjs
│   │   ├── chat/ChatPanel.tsx
│   │   ├── terminal/Terminal.tsx                  # xterm.js
│   │   ├── inspector/ConfigInspector.tsx          # Monaco
│   │   ├── timeline/Timeline.tsx
│   │   └── session/ControlBar.tsx
│   ├── lib/{api,socket}.ts
│   └── state/{sessionStore,topologyReducer,viewReducer}.ts
├── Dockerfile                                     # output: standalone
└── .github/workflows/ci.yml
```

### `platform`
```
platform/
├── .github/workflows/                             # all `on: workflow_call`
│   ├── dotnet-ci.yml          # format check, build, test
│   ├── node-ci.yml            # eslint, prettier, typecheck, test, build
│   ├── proto-ci.yml           # buf lint/breaking, generate, pack, publish
│   ├── container-publish.yml  # buildx → GHCR (sha + semver tags)
│   ├── release-binary.yml     # dotnet publish linux-x64 → GitHub Release
│   └── vm-image.yml           # build base image with pinned harness + lesson images
├── lint/
│   ├── .editorconfig
│   ├── Directory.Build.props  # analyzers, warnings-as-errors, LangVersion
│   ├── eslint.config.mjs
│   ├── prettier.config.mjs
│   └── sync.sh                # copy canonical configs into a repo
├── deploy/                    # the demo host
│   ├── docker-compose.yml     # proxy, web, api, postgres (image tags pinned via .env)
│   ├── Caddyfile
│   ├── envmgr.service
│   ├── envmgr.env.example
│   ├── api.env.example
│   └── install.sh             # fetch envmgr release + VM image, install unit, compose up
└── dev/
    └── docker-compose.dev.yml # postgres + api (fake or docker sandbox) for local dev
```

---

## 8. CI/CD & shared tooling (Filip)

- **Reusable workflows** live in `platform/.github/workflows`. Each repo's `ci.yml` is a short `uses: kubernetes-learning-platform/platform/.github/workflows/dotnet-ci.yml@main`. If `platform` is private, set it to "accessible from repositories in the organization" under Actions settings.
- **Lint** (CALL): C# uses `.editorconfig` + `dotnet format --verify-no-changes` + `TreatWarningsAsErrors` + `AnalysisLevel=latest-recommended`. TS uses ESLint flat config + Prettier + `tsc --noEmit`. Proto uses `buf lint`. Canonical copies live in `platform/lint/`, and the reusable CI fails if a repo's copy drifts.
- **Architectures** (CALL): envmgr and harness publish for **linux-x64 and linux-arm64 from M1**, and lesson images and the DinD sandbox image are multi-arch. The Docker provider on Apple Silicon runs linux/arm64 containers. The VM base image stays x64-only, for the demo host.
- **Releases:** tags trigger releases. `api`/`web` → GHCR images. `sandbox` → envmgr + harness binaries, SandboxClient NuGet, then `vm-image.yml` bakes the matching harness into a new base image. Nothing pulls from the internet at runtime (DECIDED).
- **Dependency bumps** (CALL): Renovate opens PRs in `sandbox`/`api`/`web` when `contracts` or `SandboxClient` publishes.
- **Branching** (CALL): trunk-based, short-lived branches, squash merge, Conventional Commit PR titles.
- **Config** is env vars only (DECIDED). For example, api uses `ConnectionStrings__Db`, `EnvManager__Socket`, `Llm__Provider`, `Llm__ApiKey`, `Session__IdleMinutes`, `Agent__TokenBudget`, `Sandbox__Mode=Real|Fake`. envmgr uses `Provider=Vmm|Docker`, `WarmPool__Size`, `StateDir`, `BaseImage__Path`, `Sandbox__MaxLifetime`.

### Local development without KVM

| Person | Runs locally |
|---|---|
| Filip | envmgr via `dotnet run` with `Provider=Docker`. The harness (linux-arm64 build) runs inside a privileged DinD container and dials envmgr over WebSocket. The dev Mac is an Apple M5 with 16 GB, so it fits **one sandbox at a time** (~4 GB in Docker Desktop). |
| Person 2 | `platform/dev` compose: Postgres + api with `Sandbox__Mode=Fake` (`FakeSandboxSession` plays a scripted cluster). Switches to `Real` once Filip's Docker provider works. |
| Person 3 | The same compose. The fake sandbox drives the socket, so the canvas, chat and terminal can be built before any real sandbox exists. |

---

## 9. Milestones by person

| | Filip | Person 2 | Person 3 |
|---|---|---|---|
| **M1 Sandbox** | `platform` repo: shared workflows + lint; `contracts` v0.1; envmgr with Docker provider, then VMM; harness exec over vsock; base image; `FakeSandboxSession` | api skeleton: auth abstraction, sessions CRUD, Postgres + migrations, WS endpoint with fan-out against the fake | App shell, routes, socket client, topology canvas rendering the fake's snapshot/diffs |
| **M2 Agent** | Agent loop, `ILlmClient`, execute/observe tools, token budget | Wire `AgentRunner` into `LiveSession`, chat streaming, PTY plumbing | Chat panel with streaming, xterm.js terminal |
| **M3 Live view** | Watchers → `TopologyModel` → snapshot/diff, view tools | `TopologyCache`, persist-then-broadcast, `Resync` | Real canvas, intent-driven camera, Monaco inspector |
| **M4 Lessons** | Fault tools + ledger, lessons with checkpoints, traffic probe, recorded fallback sessions | Control lock + takeover summary, `EventsController`, idle reaper | Control bar, editable inspector + Apply, timeline + replay, traffic animation, lesson progress |

**Stretch** (after M4): BYO repo (egress, in-VM builds, opening apps in the browser), `add_node` / `remove_node`, real VMs as nodes, KubeVirt provider, spectator mode.

---

## 10. Technical risks (read before M1)

1. **The official Kubernetes .NET client's AOT build has no watch support.** `KubernetesClient.Aot` omits `Watcher` and kubeconfig file loading (verified in the client's docs). The harness needs another route: either `kubectl get <kind> -A -w --output-watch-events -o json` subprocesses parsed with source-generated `System.Text.Json`, or a hand-rolled `?watch=true` HTTP stream. Recommendation: kubectl subprocesses first, since kubectl is already in the image.
2. **PTY in .NET.** There's no built-in API. Use `openpty` + spawn with a new session and controlling TTY. **Never call `fork()` from a running .NET process.** Budget real time for this, or shell through `script`/`setsid` as a fallback.
3. **vsock in .NET.** There's no `AddressFamily.Vsock`. The guest side needs `new Socket((AddressFamily)40, …)` plus a custom `EndPoint` that serializes `sockaddr_vm`. The host side is a plain `UnixDomainSocketEndPoint` (hybrid vsock).
4. **`DeviceAllow=/dev/vhost-vsock`** in the brief's unit is only needed for QEMU-style vhost-vsock. With Firecracker or Cloud Hypervisor's hybrid vsock it's likely unnecessary. Confirm once the VMM is chosen.
5. **GitHub Packages needs a token to install, even for public packages.** Each person creates a classic PAT with `read:packages` once, for `nuget.config` and `.npmrc`. CI uses `GITHUB_TOKEN`, but each consuming repo must be granted access to the package.
6. **Required reviews and branch protection on private repos need a paid plan** (or GitHub Education's Team plan). On a free org with private repos, CODEOWNERS only requests reviews and can't enforce them.
7. **Docker provider memory.** 3–4 GB per sandbox inside Docker Desktop's VM. Raise its memory limit.

---

## 11. Open questions

Carried from the brief: demo host OS · VMM (Firecracker vs Cloud Hypervisor) · LLM provider + token budget · auth mechanism · VM image tooling (mkosi vs Packer) · egress policy (deferred with BYO; MVP sandboxes are fully offline).

New:
- **Repo visibility:** public or private? Affects branch protection (risk 6) and whether the demo host needs a GHCR login to pull images.
- **Dates & capacity:** the final demo date, any course checkpoints, rough hours per person per week, and anything the course requires (evidence of individual contribution, where code must be hosted). This decides which M4 items and stretch goals make the cut.
- **Final project name:** see below.

## 12. Naming

"kubernetes-learning" is a placeholder. The GitHub org is already `kubernetes-learning-platform`, and the npm scope must match it because GitHub Packages requires that. The placeholder also appears in: NuGet package IDs, C# root namespaces (`KubernetesLearning.*`), the proto package (`kubernetes_learning.v1`), the state/runtime dirs (`/var/lib/kubernetes-learning`, `/run/kubernetes-learning`) and systemd unit names. **Rename before `contracts` reaches 1.0.** After that, renaming the proto package is a breaking wire change. Before then it's a find-and-replace.
