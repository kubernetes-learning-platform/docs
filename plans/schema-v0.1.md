# Schema plan: contracts v0.1

The plan for the first release of the Protobuf schema in `contracts` (contracts#5). It lists every message the system needs for the lab as designed, file by file, and what ships in `v0.1`. Once the `.proto` files exist, they are the source of truth and this plan is history.

**Status:** reviewed with Filip on 2026-11-19. Labels follow the docs rules: **DECIDED**, **DEFAULT**, **OPEN**, **CALL**.

**Inputs:** the lab interface design (18 screens, 2026-11-12), [FEATURES.md](../FEATURES.md), [ARCHITECTURE §4–6](../ARCHITECTURE.md#4-services-and-their-entry-points), [ADR 0002](../adr/0002-learner-driven-scenarios-and-scale-target.md), and curriculum notes that pair a short presentation with each lab.

---

## 1. Decisions this plan rests on

Made on 2026-11-19.

- **Cluster nodes are machines** (DECIDED, ADR 0004 to follow). The sandbox stays one VM per session, which needs KVM (platform#6). Inside it, Docker runs with the Sysbox runtime, and `cp`, `w1` and `w2` are Sysbox system containers running systemd, sshd and k3s. This replaces k3d, so `ssh w2`, `sudo systemctl stop k3s-agent` and `journalctl` are real commands. The sandbox VM itself is the workstation: it holds the learner's shell and the harness, so a fault on a node can't cut the session off. The learner has root inside the nodes only; on the VM they have no sudo and no Docker access.
- **Topology entities are generic** (DECIDED): one `Entity` message with a kind string, so new Kubernetes kinds need no schema change.
- **Manifests are fetched on demand** (DECIDED): the inspector asks for one resource's YAML. Snapshots and diffs don't carry YAML. This replaces FEATURES §8's "raw manifest attached to each graph entity".
- **Lessons are planned, built later** (DECIDED): a lesson will be a short presentation plus a scenario. Presentation content is files in the scenario folder that `web` renders, outside `contracts`. `v0.1` only adds what the catalog needs now: prerequisites and optional steps.
- **The helper budget is tokens** (DECIDED). `HelperState` carries the fraction left, and `web` draws it as a bar.
- **Smaller defaults** (DEFAULT, from the design review):
  - `SessionStatus` gains `failed` with a reason, the start time, the reconnect attempt and the time of the last state received.
  - `HelperState` gains `off`.
  - Every check result carries what it last observed, such as the HTTP status code.
  - `FaultMarked` carries a short description.
  - Every server message carries an actor (learner, helper, scenario or system), for the replay timeline.
  - Diffs carry a timestamp.
  - "Retry now" only reconnects the browser's own socket. No message asks `api` to redial `envmgr`; it already does that by itself.

## 2. Conventions

- **Package:** `kubernetes_learning.v1`, one file per boundary as in [ARCHITECTURE §5](../ARCHITECTURE.md#5-contracts). No `csharp_namespace` or other file options in `v0.1` (CALL), so C# gets `KubernetesLearning.V1` and the pre-1.0 rename touches only the package line.
- **Style:** `buf lint` STANDARD. Enums start with `<ENUM>_UNSPECIFIED = 0` and every value carries the enum's prefix, so `HelperPhase` has `HELPER_PHASE_IDLE`. Fields are snake_case.
- **Time:** `google.protobuf.Timestamp` and `google.protobuf.Duration` (CALL). Both protobuf-es and C# map them to native types.
- **IDs:** strings. Sessions, sandboxes, requests, questions and faults use UUIDs. A topology entity's ID is its Kubernetes UID. An edge's ID is `<type>:<from_id>:<to_id>`.
- **Requests and replies** carry a `request_id` chosen by the sender, so replies can be matched without ordering assumptions.
- **Growth:** `ClientMessage`, `ServerMessage` and `HarnessFrame` grow through their `oneof`. Optional fields use proto3 `optional` where "not set" differs from zero.
- **REST bodies** use the proto3 JSON mapping (CALL, unchanged).

The sketches below show fields and types. Field numbers come in the PR.

## 3. Files

### `common.proto`

```proto
message Error {
  ErrorCode code;
  string message;          // for people, safe to show in the UI
  bool retryable;
}

enum ErrorCode {           // INVALID_ARGUMENT, NOT_FOUND, CONFLICT, FORBIDDEN,
                           // UNAVAILABLE, BUDGET_EXHAUSTED, INTERNAL
}

enum Actor {               // LEARNER, HELPER, SCENARIO, SYSTEM
}
```

`FORBIDDEN` covers terminal input or Apply while the helper is acting. `UNAVAILABLE` covers the sandbox link being down.

### `topology.proto`

The state stream. The harness builds it from the Kubernetes API and from Docker events for the node containers.

```proto
message Entity {
  string id;                         // Kubernetes UID
  string kind;                       // "Pod", "Service", "Node", "HTTPRoute", ...
  string api_group;                  // empty for core, e.g. "gateway.networking.k8s.io"
  string namespace;                  // empty for cluster-scoped kinds
  string name;
  EntityStatus status;
  map<string, string> labels;
  map<string, string> selector;      // Services, Deployments, ReplicaSets
  repeated Fact facts;               // what the inspector's summary shows
}

message EntityStatus {
  Health health;                     // OK, PROGRESSING, WARNING, ERROR, UNKNOWN, TERMINATING
  string phase;                      // "Running", "Pending", "NotReady"
  string reason;                     // "CrashLoopBackOff", "ImagePullBackOff"
  optional uint32 ready;             // ready replicas or containers
  optional uint32 desired;
  uint32 restarts;
}

message Fact { string key; string value; }   // "Image", "Node IP", "Kubelet"

message Edge {
  string id;
  EdgeType type;                     // OWNS, RUNS_ON, ROUTES_TO, SELECTS, MOUNTS, USES
  string from_id;
  string to_id;                      // empty when the target doesn't exist
  string missing_target;             // "Service shop/web" when to_id is empty
  EdgeState state;                   // OK, NOT_READY, BROKEN
}

message TopologySnapshot {
  uint64 revision;
  google.protobuf.Timestamp at;
  repeated Entity entities;
  repeated Edge edges;
}

message TopologyDiff {
  uint64 from_revision;
  uint64 to_revision;
  google.protobuf.Timestamp at;
  repeated Entity upserted;
  repeated string removed_ids;
  repeated Edge edges_upserted;
  repeated string edges_removed;
}

message ClusterEvent {
  string id;
  google.protobuf.Timestamp at;
  string involved_id;
  bool warning;
  string reason;
  string message;
  uint32 count;
}

message TrafficSample {
  string service_id;
  google.protobuf.Timestamp at;
  map<string, uint32> hits_by_pod_id;
}

message Manifest {
  string entity_id;
  uint64 revision;                   // the topology revision it was read at
  string yaml;                       // managedFields stripped
}
```

- **Health drives the shape and glyph** in the design: a dot for OK, a ring for progressing, a cross for error, a minus for terminating. The words come from `phase` and `reason`.
- **Endpoints.** A `SELECTS` edge from a Service to a pod has state `OK` when the endpoint is ready and `NOT_READY` when it isn't. The design's third marker, "the selector does not match this pod", is drawn by `web` from the labels and selectors it already has, so no message carries it.
- **Missing targets.** An Ingress that routes to a Service that doesn't exist gets an edge with `missing_target` set and state `BROKEN`. The design draws it as a cross at an empty outline.
- **The namespace filter** is client-side. The topology always covers every namespace, so `web` can say "7 system pods hidden".
- **Status changes.** The "Running → CrashLoopBackOff, 8s ago" note comes from comparing a diff with the previous state, plus the diff's `at`.

### `view.proto`

The intent stream: where the learner should look. Only the helper's view tools produce it.

```proto
message ViewIntent {
  string id;
  oneof action {
    Focus focus;           // target_ids, fits them in view
    Highlight highlight;   // target_ids, entities or edges
    Annotate annotate;     // annotation_id, target_id, text
    ShowConfig show_config;// entity_id, opens the inspector
    Clear clear;           // ids; empty clears all helper markup
  }
}
```

The design's "Helper markup · 1 note" pill counts the live annotations, and its hide button is client-side.

### `harness.proto`

Frames between the harness and `envmgr`, relayed unchanged to `api`. One connection per sandbox, so frames carry no session ID.

```proto
message HarnessFrame {
  oneof body {
    Hello hello;                      // sandbox_id, token, harness_version
    SnapshotRequest snapshot_request;
    ClusterStatus cluster_status;     // BOOTING, NODES_UP, READY, FAILED + message

    ExecRequest exec;                 // request_id, target, argv, stdin, timeout, actor
    ExecOutput exec_output;           // request_id, stream (STDOUT | STDERR), data
    ExecExit exec_exit;               // request_id, exit_code, duration

    PtyOpen pty_open;                 // pty_id, cols, rows
    PtyInput pty_input;               // pty_id, data
    PtyOutput pty_output;             // pty_id, data
    PtyResize pty_resize;             // pty_id, cols, rows
    PtyClosed pty_closed;             // pty_id, exit_code

    FileWrite file_write;             // request_id, target, path, content, mode, archive
    FileRead file_read;               // request_id, target, path
    FileResult file_result;           // request_id, content, error

    ManifestRead manifest_read;       // request_id, entity_id
    ManifestResult manifest_result;   // request_id, manifest, error
    ApplyRequest apply;               // request_id, yaml, actor
    ApplyResult apply_result;         // request_id, repeated applied ("service/web configured"), error

    FaultRequest fault;               // request_id, Fault
    FaultResult fault_result;         // request_id, fault_id, target_ids, description, error
    RevertFault revert_fault;         // request_id, fault_id
    FaultReverted fault_reverted;     // request_id, fault_id, error

    CheckRequest check;               // request_id, repeated CheckSpec
    CheckResults check_results;       // request_id, repeated CheckResult

    TrafficStart traffic_start;       // request_id, service namespace + name
    TrafficStop traffic_stop;         // request_id

    TopologySnapshot snapshot;
    TopologyDiff diff;
    ClusterEvent cluster_event;
    TrafficSample traffic_sample;
  }
}

message Target {                      // where a command or file operation runs
  oneof machine {
    Workstation workstation;          // the sandbox VM
    string node;                      // "cp", "w1", "w2"
  }
}

message Fault {
  oneof kind {
    StopNode stop_node;               // node: stops its container
    StopService stop_service;         // node, unit: "k3s-agent"
    DeletePod delete_pod;             // pod_id
    Partition partition;              // node_a, node_b
    BadImage bad_image;               // deployment_id, container, image
  }
}

message CheckSpec {
  string id;
  string title;                       // "Service web exists in namespace shop"
  optional string subject_id;         // the entity the design draws the result at
  oneof kind {
    ResourceCheck resource;           // kind, namespace, name, json_path, equals
    HttpCheck http;                   // url, host, expected_status
    CommandCheck command;             // target, argv, expected_exit
  }
}

message CheckResult {
  string id;
  bool passed;
  string observed;                    // "503", "0 endpoints", "exit 1"
  string message;
}
```

- **Commands on a node** run through ssh from the workstation, as the harness's own user. The mirrored line is the real command, such as `agent$ ssh w2 sudo systemctl start k3s-agent`, so the learner sees exactly what they could type.
- **Faults are typed**, so each needs harness code anyway. `StopNode` stops the node's container; `StopService` stops a systemd unit inside it. Candidates for later: `FillDisk`, `ThrottleNetwork`, `BreakDns`.
- **`subject_id`** lets the design draw "GET / 503" where the request enters the cluster, at the Ingress.
- **Scenario files** reach the sandbox as one `FileWrite` with `archive` set, unpacked at the path.

### `envmgr.proto`

```proto
service EnvironmentManager {
  rpc CreateSandbox(CreateSandboxRequest) returns (CreateSandboxResponse);  // sandbox
  rpc DestroySandbox(DestroySandboxRequest) returns (DestroySandboxResponse);
  rpc GetSandbox(GetSandboxRequest) returns (GetSandboxResponse);           // sandbox
  rpc ListSandboxes(ListSandboxesRequest) returns (ListSandboxesResponse);
  rpc WatchSandbox(WatchSandboxRequest) returns (stream WatchSandboxResponse); // status
  rpc Connect(stream ConnectRequest) returns (stream ConnectResponse);      // frame
}

message Sandbox {
  string id;
  SandboxPhase phase;                 // BOOTING, READY, IN_USE, FAILED, DESTROYING
  string host;
  google.protobuf.Timestamp created_at;
  repeated string nodes;              // "cp", "w1", "w2"
}

message SandboxStatus {
  string sandbox_id;
  SandboxPhase phase;
  string message;
  google.protobuf.Timestamp at;
}
```

Each RPC has its own request and response message, as `buf lint` STANDARD requires, so `ConnectRequest` and `ConnectResponse` each wrap one `HarnessFrame`. `Connect` names its sandbox in the `sandbox-id` gRPC metadata header (CALL).

### `jobs.proto`

```proto
message ProvisionRequest { string request_id; string session_id; }

message ProvisionResult {
  string request_id;
  oneof outcome {
    Provisioned provisioned;          // sandbox_id, host
    Error failed;
  }
}

message TeardownRequest { string request_id; string session_id; string sandbox_id; }
```

Every sandbox is the same, so `ProvisionRequest` carries no scenario. `api` sends the scenario files once the sandbox is connected.

### `session.proto`

The browser socket. Every `ServerMessage` gets a `seq`, is persisted, then sent, so replay feeds the same messages back.

```proto
message ClientMessage {
  oneof body {
    ChatSend chat_send;               // text
    TerminalInput terminal_input;     // data
    TerminalResize terminal_resize;   // cols, rows
    ApplyManifest apply_manifest;     // request_id, yaml
    ManifestRequest manifest_request; // request_id, entity_id
    HelperStop helper_stop;
    AgentAnswer agent_answer;         // question_id, oneof (option_id | text)
    HintRequest hint_request;         // step_id
    ScenarioNext scenario_next;       // step_id
    StepReset step_reset;             // step_id
    Resync resync;                    // after_seq
  }
}

message ServerMessage {
  uint64 seq;
  google.protobuf.Timestamp at;
  Actor actor;
  oneof body {
    SessionStatus session_status;
    HelperState helper_state;
    ChatDelta chat_delta;             // message_id, text
    ChatMessage chat_message;         // message_id, actor, text
    ToolCallStarted tool_call_started;// call_id, tool, summary, command
    ToolCallFinished tool_call_finished; // call_id, ok, exit_code, error
    AgentQuestion agent_question;     // question_id, text, repeated Option (option_id, label)
    AgentQuestionClosed agent_question_closed; // question_id, answer_text
    TerminalOutput terminal_output;   // data, source (Actor)
    TopologySnapshot topology_snapshot;
    TopologyDiff topology_diff;
    ClusterEvent cluster_event;
    ViewIntent view_intent;
    FaultMarked fault_marked;         // fault_id, target_ids, description
    FaultReverted fault_reverted;     // fault_id
    TrafficSample traffic_sample;
    ScenarioProgress scenario_progress;
    HintRevealed hint_revealed;       // step_id, index, text
    ManifestResponse manifest_response; // request_id, manifest, error
    ApplyResult apply_result;         // request_id, repeated applied, error
    Error error;
  }
}

message SessionStatus {
  SessionPhase phase;                 // QUEUED, STARTING, LIVE, RECONNECTING, ENDED, FAILED
  optional uint32 queue_position;     // QUEUED
  StartingStep starting_step;         // WAITING_FOR_SANDBOX, CONNECTING, APPLYING_SCENARIO
  google.protobuf.Timestamp started_at;      // live since
  optional uint32 reconnect_attempt;  // RECONNECTING
  google.protobuf.Timestamp last_state_at;   // RECONNECTING: "showing the state from 14:02:11"
  Error failure;                      // FAILED: "w2 did not join the cluster in time"
  EndReason end_reason;               // LEARNER, IDLE, MAX_LIFETIME, START_OVER
}

message HelperState {
  HelperPhase phase;                  // IDLE, ACTING, WAITING, OFF
  float budget_left;                  // 0 to 1
  OffReason off_reason;               // BUDGET_USED, NOT_CONFIGURED
}

message ScenarioProgress {
  string scenario_id;
  string step_id;
  uint32 step_index;                  // "Step 2 of 2"
  uint32 step_count;
  bool step_optional;                 // a challenge step
  repeated CheckResult checks;
  bool step_passed;                   // shows Next
  uint32 hints_revealed;
  uint32 hint_count;
  bool scenario_complete;
}
```

- **Hints arrive over the socket** (CALL). `HintRequest` returns `HintRevealed`, so the count is real for "Hints used", and replay shows hints when they were opened. `GET /api/scenarios/{id}` stops sending hint text.
- **The starting steps** are what `api` can actually see. With the warm pool, the cluster is up before the session takes the sandbox, so the design's "nodes created, control plane ready" steps become one wait.
- **Apply and the terminal are refused while reconnecting**, with `UNAVAILABLE`, as the design shows ("Apply is paused while reconnecting").
- **`AgentQuestionClosed`** closes the card in every open tab and in replay, whether the answer came from an option, free text or a chat message.

### `rest.proto`

```proto
// Auth: the mechanism is OPEN. The design signs in with a name only.
message LoginRequest { string display_name; }
message User { string id; string display_name; }

// Sessions
message CreateSessionRequest { optional string scenario_id; }   // none: a blank cluster
message Session {
  string id;
  optional string scenario_id;
  SessionPhase phase;
  google.protobuf.Timestamp created_at;
  google.protobuf.Timestamp started_at;
  google.protobuf.Timestamp ended_at;
  uint32 checks_passed;               // the home screen's "1 of 2 checks"
  uint32 checks_total;
  SessionSummary summary;             // once the scenario is complete
}
message SessionSummary {
  google.protobuf.Duration duration;
  uint32 checks_passed;
  uint32 hints_used;
  uint32 helper_turns;
}
message ListSessionsResponse { repeated Session sessions; }

// Scenarios
message ScenarioSummary {
  string id;
  string title;
  Level level;                        // BEGINNER, INTERMEDIATE, ADVANCED
  string summary;                     // one line for the home screen
  repeated string prerequisites;      // scenario IDs
  ProgressStatus status;              // NOT_STARTED, IN_PROGRESS, COMPLETED
  bool helper_demonstrated;
}
message ScenarioDetail {
  ScenarioSummary summary;
  repeated StepInfo steps;            // id, goal, optional, hint_count, check titles
}
message ListScenariosResponse {
  repeated ScenarioSummary scenarios;
  uint32 completed_count;
}

// Replay
message EventBatch {
  repeated ServerMessage events;
  uint64 next_after_seq;
  bool end;
}
```

REST errors return `Error` as the body.

## 4. What ships in v0.1

`v0.1` is the first `feat:` release. It aims to be complete enough that `api` and `web` build the whole lab against real types, even where the behaviour comes later. Adding fields or `oneof` cases afterwards is a patch release; only changes to existing fields are breaking.

| File | In v0.1 | Later, added without a break |
|---|---|---|
| `common.proto` | All | More error codes |
| `topology.proto` | All, including `TrafficSample` | More edge types and states |
| `view.proto` | All | — |
| `harness.proto` | Hello, snapshot, exec, PTY, files, manifests, apply, checks, faults `StopNode`, `StopService`, `DeletePod`, `BadImage` | `Partition`, traffic, `ClusterStatus` details, more faults |
| `envmgr.proto` | All | — |
| `jobs.proto` | All | — |
| `session.proto` | All | More helper tool messages |
| `rest.proto` | All above | Presentations, quiz results, account settings |

## 5. What this changes elsewhere

To do once this plan is accepted, each in its own issue or commit:

- **ADR 0004:** node machines in the sandbox VM (k3s in Sysbox system containers, the VM as the workstation). Update ADR 0001 and 0003's status lines, FEATURES §1, §7, §9 and §14, ARCHITECTURE §4.2, §4.3, §7 and §8, the sandbox diagram, and the `sandbox` repo's docs.
- **FEATURES §8 and ARCHITECTURE §4.1:** manifests on demand; hints over the socket.
- **ADR 0002 §4, scenario format:** checks gain `title` and an optional `subject`, steps gain `optional`, and scenarios gain `summary` and `prerequisites`.
- **The design:** the node scenario fixes `k3s-agent`, not a kubelet unit, and Next on a passed step moves to the next step before the summary.

## 6. Still open

- **Auth mechanism** (OPEN). The design's name-only sign-in fits a Tailscale-only app; `LoginRequest` follows it until decided.
- **Budget size** (OPEN). The token number per session, and the global limit on concurrent turns.
- **Scenario count for the first milestone** (OPEN). The design shows 8; the plan says 3–5, and the curriculum notes suggest 3 complete ones first.
- **Presentations** (planned, DECIDED to build later). Their file format, and whether a quiz answer is recorded as progress.
