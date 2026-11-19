# ADR 0004: Cluster nodes are machines inside the sandbox VM

- **Status:** Accepted · 2026-11-19 · **DECIDED** by Filip: the node machines, the workstation, the learner's rights, and the fallback without KVM. Which path the course VM runs stays **OPEN** until platform#6. **Revised** the same day: §5 now tests real sandboxes on a Hetzner test VM through the Sysbox provider, instead of Lima on the Mac (CALL).
- **Changes:** the k3d cluster inside each sandbox ([ADR 0002](0002-learner-driven-scenarios-and-scale-target.md), [ARCHITECTURE §4.2–4.3](../ARCHITECTURE.md#42-envmgr--net-10-self-contained-daemon-on-the-course-vm--filip), [FEATURES §1](../FEATURES.md#1-your-own-real-cluster-in-one-click)), and the no-KVM column of [ADR 0003 §3](0003-course-vm-hosting.md#3-the-sandbox-type-depends-on-kvm-open-until-checked) with its build order in §4. The KVM column of ADR 0003 §3 still holds: one QEMU/libvirt VM per session. The Docker provider of [ADR 0001](0001-hosting-and-harness-transport.md) is dropped.
- **Builds on:** contracts `v0.1`, which already models nodes as machines (`Target`, `StopNode`, `StopService`), from the [schema plan](../plans/schema-v0.1.md).

Labels: **DECIDED** by Filip · **CALL** chosen while writing this, change freely · **OPEN** not decided.

---

## Context

- Each sandbox ran **k3d**: the three nodes were bare k3s processes in privileged Docker containers. A node had no systemd and no sshd, so `ssh w2`, `systemctl` and `journalctl` didn't exist. Node troubleshooting is core to a DevOps course, and the lab design's node scenario needs exactly those commands.
- k3d nodes are privileged, so anyone who reached a node was effectively root on the sandbox.
- Sysbox's documentation says a Sysbox system container runs systemd, sshd and Kubernetes without `--privileged`, using user namespaces, and behaves much like a small VM.
- Without KVM, ADR 0003 planned a Docker + k3d container per session. That path inherits both problems above.

## Decision

### 1. Nodes are Sysbox system containers (DECIDED)

- `cp`, `w1` and `w2` are system containers under the Sysbox runtime, inside the sandbox VM's Docker.
- Each runs **systemd** as init, **sshd**, and **k3s**: the `k3s` server unit on `cp`, the `k3s-agent` unit on `w1` and `w2`. The kubelet runs inside those units, so the node scenario stops and fixes `k3s-agent`.
- Each node has its own hostname and a static address on a Docker network inside the VM (CALL). The workstation resolves them through `/etc/hosts` (CALL).
- The node image is built from `sandbox/images/node/` (CALL) and baked into the sandbox template. Scenario images reach every node's containerd from one read-only copy in the template, through k3s's image import directory (CALL). Nothing is pulled at runtime, as before.
- Node containers get memory and CPU limits (CALL: sized when RAM is measured, platform#17).

### 2. The sandbox VM is the workstation (DECIDED)

- The learner's shell and the harness run on the VM itself, not on a node. Stopping a node, its k3s unit or its network can't cut the session off.
- This is how operations work in practice: you ssh out to the machines from an admin box.
- The learner's kubeconfig points at `cp`. `ssh cp`, `ssh w1` and `ssh w2` work from the learner's shell with a key the template installs (CALL), and `sudo` works inside each node.
- The harness runs a command on a node through ssh from the workstation, as its own user. The mirrored line is the real command, such as `agent$ ssh w2 sudo systemctl start k3s-agent`.
- `StopNode` stops a node's container. `StopService` stops a systemd unit inside a node. Both go through the `FaultLedger` with their undo action.

### 3. Who can do what inside the sandbox (DECIDED)

| Who | Rights |
|---|---|
| **The learner** | A normal user on the VM, with **no sudo** and **not in the `docker` group**. Root only inside the nodes, through ssh and sudo there. Docker access on the VM would make them root on it and undo the user namespaces. |
| **The harness** | Its own user. The token file `/etc/kubernetes-learning/harness.env` is owned by that user and readable only by it (`0600`), so the learner can't stop the harness or read the token. The harness needs Docker access on the VM to watch and stop node containers (CALL). |
| **A node** | Root inside a node is an unprivileged user on the VM, because of Sysbox's user namespaces. |

- **Limits:** memory and CPU caps on the node containers and on the learner's processes, including a process limit, so a fork bomb or a full disk takes down only that session's VM (CALL: through a systemd slice for the learner and Docker limits for the nodes).
- **Network:** the VM listens on nothing. Nodes can reach the VM's own address, so traffic from the node network that leaves the VM is dropped (CALL); only the harness talks to `envmgr`. The harness endpoint stays tiny and rejects anything before a valid `Hello` anyway.
- **The token** belongs to one sandbox for its whole life: the harness reuses it when it redials, and it dies with the sandbox. Even if a learner got it, they could only pose as their own sandbox and fake their own progress.
- **Patching:** the kernel, Docker and Sysbox are updated by rebuilding the template. A kernel exploit from a node gives root on that one VM, which KVM still contains.

What stays the same: the VM is the boundary that protects the course VM, the stack and other sessions. No secrets enter the sandbox, the LLM key stays in `api`, sandboxes have no internet, and the app is reachable only over Tailscale.

### 4. Without KVM (DECIDED as the fallback)

If platform#6 finds no `/dev/kvm` on the course VM, only the outer layer changes:

| | With KVM (the plan) | Without KVM (the fallback) |
|---|---|---|
| **The session's boundary** | A QEMU/libvirt VM, a linked clone of the template | Its own Docker network on the course VM |
| **The workstation** | The VM | A Sysbox system container, the learner's shell plus the harness |
| **The nodes** | Sysbox containers in the VM's Docker | The same node image, as Sysbox containers in the course VM's Docker |
| **Identity** | cloud-init writes the token | Env vars on the workstation container |
| **Provider** | `QemuProvider` | `SysboxProvider` (CALL), which is also the test VM's provider (§5) |

- **The accepted risk:** every session shares the course VM's kernel with the other sessions and the stack, as ADR 0003 §3 already said for the container path. A kernel exploit from a node would reach the course VM.
- The harness in the workstation container must not get the course VM's Docker socket, which would make it root there. So in the fallback, `envmgr` stops node containers and reports their Docker events for the harness (CALL).
- The isolation rule doesn't change: a session's network reaches only `envmgr`'s harness endpoint.

### 5. Development and testing (CALL, revised 2026-11-19)

- **Local machines stay light.** They run Docker Desktop for Postgres and Caddy, the .NET 10 SDK and Node, and no VMs. `envmgr` and the harness run as plain processes through the process provider for quick tests, and `api` runs against `FakeSandboxSession`.
- **Real sandboxes run on a test VM:** a Hetzner cloud server of Filip's, in the tailnet, until the course VM arrives. Hetzner Cloud has no nested virtualization (checked 2026-11-19: no `/dev/kvm`), so the test VM runs the Sysbox path of §4, which is the course VM's fallback anyway. The node image, the harness and the relay are the same on both paths.
- **So the `SysboxProvider` comes first.** A real sandbox exists before the course VM does.
- **The QEMU path is tested on a small home Proxmox server** of Filip's: bare metal with KVM and nested virtualization on, 4 cores and 8 GB. An Ubuntu VM there, with the host CPU type, runs libvirt and `envmgr`, so sandbox VMs nest inside it as they would on the course VM, one at a time. The `QemuProvider` and the qcow2 template are built and tested there, and used on the course VM if platform#6 finds KVM.
- **The test VM is for the team's testing only,** never for learners or the demo. Its sandboxes share its kernel, so nothing else of value runs on it, and only SSH and Tailscale reach it. The home server isn't a CI runner: self-hosted runners serve only private repos, and the runner stays on the course VM (platform#14). It isn't hosting: ADR 0003's one course VM still runs the stack and the demo.
- **Considered first and dropped:** a Lima VM with nested virtualization on the Mac (`vmType: vz`, Apple M3 or later). It would take about 8 GB of a 16 GB Mac and an arm64 template, and it was never checked.
- The Docker provider (Docker-in-Docker with k3d) is dropped. It was the Mac's dev path and the base of the old fallback, and both are replaced. The DinD Compose profile (platform#13) no longer applies.

## Consequences

**Better:**
- `ssh`, `systemctl`, `journalctl` and real node faults work, so node scenarios teach what operators actually do.
- Tighter inside the sandbox than k3d: root in a node is no longer root on the VM.
- A fault on any node can't cut the session off, because the shell and the harness live on the workstation.
- The node image and the scenarios are the same on both paths, so platform#6 changes only the provider.
- Real sandboxes are tested on a cheap test VM with the real fallback provider, and local machines run no VMs.

**Costs:**
- A Sysbox install, a node image and a workstation image join the build.
- The harness learns targets: it runs node commands through ssh and watches the node containers.
- Two providers to write: `SysboxProvider` first, for the test VM and the fallback, then `QemuProvider` once the course VM has KVM.
- The QEMU path is tested on a small home server, one sandbox at a time, and nested VMs boot slower.

## Labels changed

| Item | Was | Now |
|---|---|---|
| Cluster inside the sandbox | k3d: k3s in privileged containers (CALL) | Sysbox system containers with systemd, sshd and k3s (DECIDED) |
| Where the learner's shell and the harness run | Inside the sandbox, next to k3d | On the VM, the workstation (DECIDED) |
| The learner's rights | Not stated | No sudo and no `docker` group on the VM; root inside the nodes only (DECIDED) |
| The node fault | `kill_node` stops a container | `StopNode` stops a container; `StopService` stops a unit (DECIDED, contracts `v0.1`) |
| Without KVM | A Docker + k3d container per session under Sysbox (OPEN, ADR 0003) | Sysbox nodes and a Sysbox workstation container on the course VM (DECIDED) |
| Providers | `DockerProvider`, `QemuProvider` | `QemuProvider`, `SysboxProvider` (CALL) |
| Development and testing | `envmgr` with the Docker provider and privileged DinD on the Mac (CALL) | Plain processes locally; real sandboxes on a Hetzner test VM through the `SysboxProvider` (CALL) |

## Alternatives considered

- **Keep k3d.** No systemd or sshd in the nodes, and privileged nodes. Rejected.
- **A QEMU VM per node.** Each node fully real, with its own kernel, but a session becomes four VMs: more RAM, slower boots, and a warm pool of VM groups. One VM per session stays easier to explain. Rejected.
- **kubeadm instead of k3s.** A separate `kubelet` unit, closer to most clusters, but about 1.5 GB more RAM per session. Rejected.
- **Kata Containers.** Needs KVM too, and with KVM, plain VMs are simpler. Rejected.
- **The harness on `cp`.** A fault on `cp` would cut the session off. Rejected.

## Still OPEN

- KVM on the course VM (platform#6), which decides whether the course VM runs §1–3 or §4.
- Real RAM per sandbox with the node containers (platform#17).
