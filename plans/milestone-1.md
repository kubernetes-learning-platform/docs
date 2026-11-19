# Plan: Milestone 1

The plan for the first implementation milestone: what it builds in each repo, how the code is laid out, the order of work, and when it's done. The issues come from this plan in a separate step, and the GitHub milestone is named **Milestone 1**. Once the issues exist, they are the source of truth and this plan is history.

**Status:** brainstormed with Filip on 2026-11-19. **Revised the same day:** real sandboxes are tested on a Hetzner test VM with the Sysbox provider instead of a Lima VM on the Mac ([ADR 0004 §5](../adr/0004-node-machines-in-the-sandbox.md#5-development-and-testing-call-revised-2026-11-19)). The QEMU provider and the template move after Milestone 1, to sandbox#18 and sandbox#19, so §4's `sbx create` walkthrough shows the later QEMU path; on the test VM, the Sysbox provider starts a workstation container instead of a VM. The sandbox issues are the source of truth. Labels follow the docs rules: **DECIDED**, **DEFAULT**, **OPEN**, **CALL**.

**Inputs:** [ARCHITECTURE](../ARCHITECTURE.md), [FEATURES](../FEATURES.md), [ADR 0002](../adr/0002-learner-driven-scenarios-and-scale-target.md), [ADR 0003](../adr/0003-course-vm-hosting.md), [ADR 0004](../adr/0004-node-machines-in-the-sandbox.md), the [schema plan](schema-v0.1.md) and contracts `v0.1.1`, the lab interface design, and the scaffolds in `sandbox`, `api` and `web`.

---

## 1. The shape: two halves, joined in Milestone 2

**DECIDED** by Filip.

| Half | Who | Ends with |
|---|---|---|
| **The real sandbox** | Filip | `sbx` creates a real sandbox on the Hetzner test VM through the Sysbox provider, its three nodes come up, and commands run on the workstation and on each node through the harness. |
| **The lab on the fake** | Person 2 and Person 3 | In the browser you sign in with a name, start a blank cluster, and watch the fake cluster on the canvas update live. |

- The two halves meet at `ISandboxSession`. `api` builds against `FakeSandboxSession` in Milestone 1 and switches to the real `SandboxSession` in Milestone 2.
- **No date.** The milestone is sized by its work, at about 10 hours a week per person. Filip's half is the biggest, and Filip takes on the extra hours (DECIDED).
- **Course requirements:** only the final demo is graded, so issues are organised for the team, not for grading (DECIDED).
- **The course VM** isn't available yet. If it arrives during Milestone 1, platform#6 (the KVM check) runs at once, and the VM setup (platform#8 to #10) waits for the milestone with the first deploy (DECIDED).

### Approaches considered

| Approach | Trade-off | |
|---|---|---|
| **Two halves, joined later** | All three can work in parallel from day one. The halves aren't proven together until Milestone 2. | **Picked** |
| One thin real slice | Start in the browser, get a real sandbox and run a command. Proves the whole path early, but needs KVM, the relay and exec before anyone can close the milestone. | Rejected |
| Foundations only | Skeletons, tests, CI and images, and a real sandbox from the CLI, but nothing through the browser. Safest, with the least to show. | Rejected |

## 2. The team

**DECIDED** by Filip on 2026-11-19.

- **Filip:** `sandbox` and `platform`, as before.
- **Person 2 and Person 3** share `api` and `web`, split **by feature across both repos**, so one person owns each feature and its contract end to end. This replaces the split of [ARCHITECTURE §1](../ARCHITECTURE.md#1-team--ownership) (Person 2 on `api`, Person 3 on `web`).
- Milestone 1 has two such features, assigned when the issues are written:
  - **Sign-in and sessions:** the smaller one, which starts first.
  - **Live lab:** the bigger one, which builds on sessions.
- Person 2 and Person 3 work on Windows and run only against the fake sandbox, so nothing they run needs Linux or KVM. They're briefed from this plan and the issues.

## 3. Decisions made for this milestone

| Topic | Decision | Label |
|---|---|---|
| Sign-in | Name only, behind `IAuthProvider`. The name is the account: the same name signs in to the same account. A sturdier mechanism is planned later. | DECIDED |
| libvirt | `envmgr` writes domain XML and runs `virsh`, with no native bindings | DECIDED |
| Testing envmgr, harness and client together | A process provider runs the harness as a plain process, so PR CI tests the relay, `Hello`, exec and redials with no VM. Real sandboxes are tested by hand on the test VM. | DECIDED |
| `sandbox` releases | On every `feat` or `fix` merge, like `contracts`: the version comes from the PR title, and CI tags and publishes. `api` bumps `SandboxClient` by hand for now. | DECIDED |
| .NET tests | xUnit v3 | DECIDED |
| `api` database tests | A real Postgres through Testcontainers | DECIDED |
| `web` data | Fetched in the browser only. Pages are client components calling same-origin `/api` and `/ws`, and the Next server never calls `api`. | DECIDED |
| `web` styling | MUI | DECIDED |
| One origin in local dev | Caddy in the dev Compose, the same routes as production | DECIDED |
| The Live lab's first data | The `api` socket on the fake comes first, and `web` builds against it. One fake, in C#. | DECIDED |
| Scripts | Each repo keeps its scripts in `scripts/`. Tool configs, `.github/`, the Dockerfile and `platform`'s `deploy/`, `lint/` and `dev/` stay where they are. | DECIDED |
| Web tests | Vitest, with Playwright later | CALL |
| Real sandboxes | Tested on a Hetzner test VM in the tailnet, through the Sysbox provider, until the course VM arrives. Local machines run no VMs. | DECIDED |

**Not decided here, because Milestone 1 doesn't need them:** the deploy format (nothing deploys to the course VM yet), the LLM provider and the helper budget (the helper is later).

## 4. `sandbox` (Filip)

### What happens on `sbx create`, then `sbx exec --node w2 -- systemctl status k3s-agent`

1. `sbx` calls `envmgr`'s `CreateSandbox` over gRPC.
2. `QemuProvider` makes a linked clone of the template, a qcow2 overlay backed by it. It writes a cloud-init seed with the address, the sandbox ID and a new token, then defines and starts the domain `kl-sbx-<id>` with `virsh`.
3. In the VM, systemd starts Docker, then a unit starts `cp`, `w1` and `w2` from the node image with a Compose file in the template, then the harness, as user `harness` (CALL).
4. The harness dials `ws://10.67.0.1:7071/harness` and sends `Hello{sandbox_id, token, harness_version}`. `envmgr` checks the token.
5. `ClusterBootstrap` waits until the three nodes are Ready, then sends `ClusterStatus` with phase `READY`. `WatchSandbox` reports it.
6. `sbx exec` opens `Connect` for the sandbox and sends `ExecRequest` with `Target{node: "w2"}`. `envmgr` relays it. The harness runs `ssh w2 …` and streams `ExecOutput`, then `ExecExit`, back.

### Layout

```
src/
  KubernetesLearning.SandboxClient/       first: api builds on it
    ISandboxSession.cs
    EnvironmentManagerClient.cs           gRPC: create, destroy, get, list, watch, connect
    SandboxSession.cs                     one Connect stream: request_id matching, redial with backoff and jitter
    Fakes/FakeSandboxSession.cs           scripted cluster
    Fakes/Scripts/                        steady, rollout, crashloop, node-down
  KubernetesLearning.EnvManager/
    Program.cs                            Kestrel: gRPC on Grpc__Listen, the /harness WebSocket on Harness__Listen
    Grpc/EnvironmentManagerService.cs
    Relay/HarnessWebSocketEndpoint.cs     Hello and token check first, then frames
    Relay/HarnessRelay.cs                 pairs each harness with its Connect stream
    Lifecycle/SandboxRegistry.cs          what exists, from the provider; re-adoption after a restart
    Lifecycle/StateStore.cs               StateDir: token hashes and IP leases, one file per sandbox
    Providers/ISandboxProvider.cs
    Providers/Sysbox/SysboxProvider.cs    the test VM now, and the course VM's fallback
    Providers/Qemu/                       QemuProvider, Virsh, DomainXml, CloudInitWriter: after Milestone 1
    Providers/Process/ProcessProvider.cs  tests and quick local runs: the harness as a plain process
  KubernetesLearning.Harness/             Native AOT
    Program.cs, HarnessHost.cs            reads harness.env, dials with backoff, sends Hello
    Transport/{IHarnessTransport,WebSocketTransport}.cs
    FrameRouter.cs
    Handlers/ExecHandler.cs               the workstation, or a node through ssh
    Cluster/ClusterBootstrap.cs           nodes Ready, then ClusterStatus READY
  KubernetesLearning.Sbx/                 create | list | exec | watch | destroy
images/
  node/                                   Dockerfile: systemd, sshd, k3s with its airgap images
  workstation/                            the workstation container: learner and harness users, limits
  base/                                   Packer, QEMU builder: the sandbox VM template, after Milestone 1
scripts/                                  building the images, setting up the test VM
tests/
  SandboxClient.Tests/  Harness.Tests/  EnvManager.Tests/
  Integration.Tests/                      envmgr + harness + SandboxClient on the process provider
```

### `ISandboxSession` in Milestone 1

It starts small and grows with each feature. Adding members doesn't break `api`, because only `sandbox` implements the interface (CALL).

| Member | Purpose |
|---|---|
| `SandboxId` | The sandbox it's attached to |
| `State` | A stream of what the harness pushes: `TopologySnapshot`, `TopologyDiff`, `ClusterEvent`, `ClusterStatus` |
| `ExecAsync(target, argv, actor)` | Runs a command and returns its output and exit, or an `Error` |
| `RequestSnapshotAsync()` | Asks for a fresh snapshot |
| `LinkChanged` | Live or reconnecting, so `api` can show `SessionStatus{reconnecting}` |

Message types are the contracts' types. `api` creates sessions through a small factory, so Fake and Real modes swap with `Sandbox__Mode` (CALL).

### The fake

- `FakeSandboxSession` plays named scripts chosen with `Sandbox__FakeScript` (CALL):
  - `steady`: three nodes, a three-pod Deployment and a Service
  - `rollout`: v1 to v2, repeated
  - `crashloop`: a pod goes into CrashLoopBackOff and back
  - `node-down`: `w2` goes NotReady and its pods reschedule
- It sends a snapshot first, then revisioned diffs on a timer. Entity IDs are stable fake UIDs.
- Exec returns canned output, such as `fake: ran kubectl get pods`.
- `steady` ships first; the others follow as the Live lab needs them.

### `envmgr` in Milestone 1

- **gRPC:** `CreateSandbox`, `DestroySandbox`, `GetSandbox`, `ListSandboxes`, `WatchSandbox` and `Connect`. `Connect` names its sandbox in the `sandbox-id` metadata header. A new `Connect` for the same sandbox replaces the old one (CALL).
- **Tokens:** a token is minted when a sandbox is created and belongs to that sandbox until it's destroyed. Redials reuse it. The state dir keeps only its hash. A second harness connection for a sandbox that's already connected is refused (CALL).
- **Lifecycle:** create on request, destroy on request, and `Sandbox__MaxConcurrent` as a hard cap. On start, `envmgr` lists the `kl-sbx-*` domains: known ones are re-adopted and wait for their harness to redial, unknown ones are deleted. A failed create leaves no overlay, seed, lease or token behind.
- **Later milestones:** the warm pool, `Sandbox__MaxLifetime`, the RabbitMQ consumers and `SnapshotRequest` on reattach.

### The harness in Milestone 1

- Dials with backoff and jitter and sends `Hello`. It redials when `envmgr` restarts.
- **Exec:** on the workstation, as the `harness` user (CALL: which user the helper's commands run as is decided with the helper). On a node, through `ssh <node>` with the harness's own key.
- **`ClusterBootstrap`:** polls `kubectl get nodes` until all three are Ready, then sends `ClusterStatus` with phase `READY`, or `FAILED` with a message after a timeout.
- **Later milestones:** PTY, files, manifests and apply, checks, faults, watchers and topology.

### The node image and the template

- **Node image** (`images/node/`): Ubuntu with systemd, openssh-server and k3s. k3s's own images come from its airgap tarball, so nothing is pulled at runtime. `cp` runs the `k3s` server unit, and `w1` and `w2` run `k3s-agent`. The cluster is created at boot in Milestone 1. Baking it into the template is a later speed-up (CALL).
- **Template** (`images/base/`): Packer with the QEMU builder from an Ubuntu LTS cloud image (CALL: 24.04, if Sysbox supports it), built for x64 on the course VM once it has KVM (sandbox#18). It contains Docker, Sysbox, kubectl, the harness, the node image, the `learner` and `harness` users with the rights from ADR 0004 §3, and the units that start the nodes and the harness.
- **Workstation image** (`images/workstation/`): the workstation as a Sysbox container for the Sysbox provider, with the `learner` and `harness` users, the rights from ADR 0004 §3 and the limits. The template reuses its setup script later.
- **Sandbox network:** on the test VM, each session gets its own Docker network that reaches only `envmgr`'s harness endpoint (CALL).

### The test VM

- Filip's Hetzner cloud VM, in the tailnet, with Docker and Sysbox from `scripts/setup-test-vm.sh` (sandbox#11). It has no KVM, so it runs the Sysbox path ([ADR 0004 §5](../adr/0004-node-machines-in-the-sandbox.md#5-development-and-testing-call-revised-2026-11-19)).
- It's for the team's testing only. Its sandboxes share its kernel, so nothing else of value runs on it, and only SSH and Tailscale reach it.
- The node image is the first thing tested there (sandbox#12), because everything after it depends on Sysbox running systemd, sshd and k3s.

## 5. `api` (Person 2 and Person 3, by feature)

```
src/KubernetesLearning.Api/
  Program.cs                          EF, cookie auth, controllers, the socket, /healthz
  Formatting/ProtoJsonFormatter.cs    REST bodies as proto3 JSON (rest.proto)
  Persistence/AppDbContext.cs, Migrations/
  ── Sign-in and sessions ──
  Auth/IAuthProvider.cs, NameOnlyAuthProvider.cs
  Controllers/AuthController.cs       POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me
  Controllers/SessionsController.cs   POST, GET list, GET one, DELETE
  Sessions/SessionService.cs
  Provisioning/{ISandboxProvisioner,FakeProvisioner}.cs
  Persistence/Entities/{User,Session}.cs
  ── Live lab ──
  Realtime/SessionSocketEndpoint.cs   GET /ws/sessions/{id}
  Realtime/EventFanout.cs             seq, persist, then broadcast
  Realtime/TopologyCache.cs
  Sessions/{SessionRegistry,LiveSession}.cs
  Persistence/EventStore.cs, Entities/SessionEvent.cs
tests/Api.Tests/                      unit tests, and WebApplicationFactory tests on Testcontainers Postgres
```

### Sign-in and sessions

- **Sign-in:** `LoginRequest{display_name}` finds or creates the user and sets a cookie through ASP.NET Core cookie authentication. The cookie is `Secure` outside local dev, which runs on plain HTTP (CALL). `GET /api/auth/me` returns `User`, or 401.
- **Sessions:** `POST /api/sessions` with no `scenario_id` starts a blank cluster. A user has at most one active session: a second start returns 409 with `Error{CONFLICT}` (CALL). `DELETE` ends it with `SessionEndReason` `LEARNER`.
- **`FakeProvisioner`:** marks a new session `STARTING`, then `LIVE` about two seconds later, so the UI shows both (CALL). It asks `SessionRegistry` for a `LiveSession` holding a `FakeSandboxSession`.
- **Tables:** `users` and `sessions`, as in [ARCHITECTURE §4.1](../ARCHITECTURE.md#41-api--aspnet-core-net-10--person-2-person-3--filip). This feature lands the first migration.
- **Errors:** REST errors return `Error` as the body.

### Live lab

- **`LiveSession`:** one per live session. It reads `ISandboxSession.State` and turns each frame into a `ServerMessage` with actor `SYSTEM`, and `LinkChanged` into `SessionStatus`.
- **`EventFanout`:** gives each message the session's next `seq`, writes it to `session_events`, and only then sends it to every open socket of that session. One `api` instance, so the `seq` counter lives in `LiveSession` and starts from the stored maximum (CALL).
- **The socket:**
  - The cookie is checked on upgrade, and only the session's owner may connect. Anyone else gets close code 1008.
  - Frames are binary, one `ClientMessage` or `ServerMessage` each.
  - A fresh socket gets the current `SessionStatus`, then the latest stored `TopologySnapshot` and every message after it, in `seq` order. `TopologyCache` knows where that snapshot is (CALL).
  - `Resync{after_seq}` replays everything after `after_seq` from the store, then continues live.
  - Every other `ClientMessage` gets `Error{UNAVAILABLE, "not available yet"}` in Milestone 1 (CALL).
- **After an `api` restart:** a session still marked live gets a new `LiveSession` with a new fake when its first socket connects (CALL).
- **Order inside the feature:** first the socket with the fake broadcasting straight through, then persist-then-broadcast and `Resync`. The feature's second migration adds `session_events`, after Sign-in and sessions' first.

### Config

`ConnectionStrings__Db`, `Sandbox__Mode=Fake`, `Sandbox__FakeScript`, plus the existing `launchSettings.json` port 5149.

## 6. `web` (Person 2 and Person 3, by feature)

```
src/
  app/
    layout.tsx                    MUI providers, header with the signed-in name and sign out
    ── Sign-in and sessions ──
    login/page.tsx
    page.tsx                      home: start a blank cluster, resume or end your session
    ── Live lab ──
    session/[id]/page.tsx         the lab page: status banner and canvas
  theme.ts
  lib/
    api.ts                        same-origin /api; proto3 JSON into contracts types (protobuf-es)
    socket.ts                     binary frames through protobuf-es; reconnect, then Resync{after_seq}
  state/
    sessionStore.ts               SessionStatus and the last seq
    topologyReducer.ts            snapshot and diffs by revision; a gap triggers Resync
  components/
    topology/                     TopologyCanvas, NodeCard, PodChip, edges, layout.ts (elkjs)
    session/StatusBanner.tsx      starting, live, reconnecting, ended
```

- **Data:** every page that talks to `api` is a client component, and the Next server never calls `api` (DECIDED). So sign-in is checked in the browser: `GET /api/auth/me`, and a 401 sends you to `/login`.
- **MUI:** `AppRouterCacheProvider` from `@mui/material-nextjs` and a `ThemeProvider` in the root layout, as MUI's Next.js guide shows. The first web issue confirms it works with `cacheComponents` and standalone output.
- **State:** Zustand stores and pure reducers, so the same reducers serve replay later (CALL, as in ARCHITECTURE).
- **The canvas** follows the lab design: nodes as lanes holding pod chips, and Deployments, ReplicaSets and Services as boxes, with `OWNS`, `RUNS_ON` and `SELECTS` edges, laid out by elkjs. It draws only from snapshots and diffs.
- **Tests:** Vitest for the reducers and `lib/`, on small fixture messages. The Live lab can start with the reducer and its tests on fixtures while the `api` socket is being built.
- **Order between the features:** the `web` setup (MUI, the theme, the layout, `lib/api.ts` and Vitest) comes first, side by side with the `api` setup, and both features build on it.

## 7. `platform` (Filip)

```
.github/workflows/
  dotnet-ci.yml, node-ci.yml   + test steps: dotnet test (xUnit v3; Testcontainers uses the runner's Docker), vitest run
  release-version.yml          + the job that picks the version from the commit subject, moved out of proto-release
  sandbox-release.yml          + harness as Native AOT on x64 and arm64 runners, envmgr and sbx self-contained,
                                 a GitHub Release, and the SandboxClient package
  container-publish.yml        + api and web images on main (platform#19)
dev/
  docker-compose.dev.yml       + Postgres and Caddy (platform#5); RabbitMQ waits for Milestone 2 and its consumers
  Caddyfile.dev                + localhost:8080: / to next dev on 3000, /api and /ws to api on 5149
```

- `proto-release.yml` calls `release-version.yml` too, so both repos version the same way (CALL).
- The dev Compose reaches `next dev` and `api` on the host through `host.docker.internal`, which works on Windows and on the Mac (on Linux through `host-gateway`).
- `api` gets read access to the `SandboxClient` package (platform#24).
- platform#13, the Docker-in-Docker profile, is closed as obsolete (ADR 0004).
- The images have never been built, so `container-publish` is worth landing early, even though nothing deploys in this milestone.

## 8. Order of work

The setup and then the tracks run in parallel. Arrows are hard dependencies.

| Track | Order |
|---|---|
| **Filip** | 1. Dev Compose with Caddy, and CI test steps → 2. release versioning, `sandbox-release`, `SandboxClient` with the `steady` fake, and the package grant → 3. harness, `envmgr`, the relay and exec on the process provider, with integration tests and `sbx` → 4. the test VM, then the node image, the workstation image, node targets and the `SysboxProvider` → 5. re-adoption after restart. `container-publish` fits anywhere; the remaining fake scripts follow the Live lab. |
| **Setup** | Side by side, one person each, before the features: the `api` skeleton (EF, Postgres, proto JSON, `/healthz`, the test setup) and the `web` shell (MUI, theme, layout, `lib/api.ts`, Vitest). Then each person goes on to a feature, which spans both repos. |
| **Sign-in and sessions** | 1. name-only sign-in → 2. sessions and `FakeProvisioner` → 3. login and home. |
| **Live lab** | 1. `topologyReducer` with tests on fixtures → 2. the `api` socket and `LiveSession` on the fake, broadcasting straight through (needs Filip 2 and Sign-in 2) → 3. persist-then-broadcast and `Resync` → 4. `socket.ts`, `sessionStore` and the status banner → 5. the canvas. |

Filip's steps 1 and 2 unblock everyone, so they go first.

## 9. Not in Milestone 1

DECIDED with the shape in §1:

- RabbitMQ, `jobs.proto` and the queued state
- the terminal (PTY), files, manifests, the inspector and Apply
- scenarios: the catalog, the runner, checks, hints and reset
- the helper, the LLM and the token budget
- faults, watchers and real topology from a real cluster
- the warm pool, the idle reaper and lifetime limits
- deploying to the course VM, and with it the deploy format
- replay and the timeline

## 10. Done when

- [ ] On the test VM, `sbx create` gives a sandbox whose three nodes are Ready, `sbx exec` runs on the workstation and on each node, and `sbx destroy` leaves nothing behind.
- [ ] Restarting `envmgr` keeps running sandboxes: they're re-adopted, the harness redials, and `sbx exec` works again.
- [ ] PR CI runs the tests in `sandbox`, `api` and `web`, including envmgr, harness and `SandboxClient` together on the process provider.
- [ ] A merge to `sandbox` `main` publishes the binaries and `SandboxClient`, and `api` uses that package. A merge to `api` or `web` `main` publishes an image.
- [ ] On `localhost:8080`, on Windows and on the Mac: sign in with a name, start a blank cluster, watch the lab go from starting to live, and see the canvas draw the fake cluster and follow its script. A second tab shows the same thing. A reload catches up from the event log. Ending the session from home works.
- [ ] The docs describe what was built.

## 11. What this changes in the other docs

Done in one pass once this plan is accepted, with the rest of the [schema plan's §5](schema-v0.1.md#5-what-this-changes-elsewhere) follow-up:

- **ARCHITECTURE:**
  - §1: the team split by feature
  - §3.2 and §4.2–4.3: ADR 0004's node machines and providers
  - §4.1: manifests on demand and hints over the socket
  - §7: the trees from this plan, and `scripts/`
  - §8: local dev, the test VM, the architectures, and tests in CI
  - §9: the milestones renamed to Milestone N, with Milestone 1 pointing here
  - §10: risks 6 and 10
  - §11: the open questions
- **FEATURES** §1, §7, §8, §9 and §14.
- **ADR 0002 §4:** the scenario format (`title` and `subject` on checks, `optional` on steps, `summary` and `prerequisites` on scenarios).
- **ADR 0004:** the token wording in §3, which should say the token belongs to one sandbox for its whole life, as §4 of this plan does.
- **The sandbox diagram** in `generate.py`, and README's team, roadmap and setup sections.
- **In the code repos:** a `docs:` PR in `sandbox` for the node machines, and the team split, MUI and `scripts/` in each repo's `AGENTS.md`, `README.md` and `.github/copilot-instructions.md`.

## 12. Still open

- **KVM on the course VM** (platform#6), when it arrives.
- **Real RAM per sandbox** with the node containers (platform#17).
- **Who takes which feature,** decided when the issues are written.
- **Sysbox on the template's Ubuntu release**, checked when the template is built.
