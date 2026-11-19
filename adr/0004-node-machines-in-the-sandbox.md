# ADR 0004: Cluster nodes are machines inside the sandbox VM

- **Status:** Accepted · 2026-11-19 · **DECIDED** by Filip: the node machines, the workstation, the learner's rights, and the fallback without KVM. Local development on the Mac is a **CALL** until nested virtualization is checked there. Which path the course VM runs stays **OPEN** until platform#6.
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
- **The token** works once and identifies one sandbox. Even if a learner got it, they could only pose as their own sandbox and fake their own progress.
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
| **Provider** | `QemuProvider` | `SysboxProvider` (CALL) |

- **The accepted risk:** every session shares the course VM's kernel with the other sessions and the stack, as ADR 0003 §3 already said for the container path. A kernel exploit from a node would reach the course VM.
- The harness in the workstation container must not get the course VM's Docker socket, which would make it root there. So in the fallback, `envmgr` stops node containers and reports their Docker events for the harness (CALL).
- The isolation rule doesn't change: a session's network reaches only `envmgr`'s harness endpoint.

### 5. Local development on the Mac (CALL, not checked yet)

- Lima's documentation says `nestedVirtualization: true` with `vmType: vz` works on Apple M3 or later with macOS 15 or later, and gives the Linux guest `/dev/kvm`. Filip's Mac is an Apple M5 on macOS 27 with 16 GB.
- So a Lima VM runs `envmgr` with the **QemuProvider** and one sandbox VM with its Sysbox nodes inside: the same stack as the course VM.
- That needs an **arm64 sandbox template and node image**, so both build for x64 and arm64 (CALL). The course VM uses the x64 ones.
- RAM: about 8 GB for the Lima VM, holding one sandbox VM of about 4 GB (CALL, to be measured).
- The rest of the team works on Windows against `FakeSandboxSession`, so nothing they run needs Linux or KVM.
- The Docker provider (Docker-in-Docker with k3d) is dropped. It was the Mac's dev path and the base of the old fallback, and both are replaced. The DinD Compose profile (platform#13) no longer applies.

## Consequences

**Better:**
- `ssh`, `systemctl`, `journalctl` and real node faults work, so node scenarios teach what operators actually do.
- Tighter inside the sandbox than k3d: root in a node is no longer root on the VM.
- A fault on any node can't cut the session off, because the shell and the harness live on the workstation.
- The node image and the scenarios are the same on both paths, so platform#6 changes only the provider.
- Local development runs the real provider instead of a separate Docker provider.

**Costs:**
- A Sysbox install and a node image join the template, and the template builds for two architectures.
- The harness learns targets: it runs node commands through ssh and watches the node containers.
- Two providers to write: `QemuProvider` now, `SysboxProvider` only if platform#6 needs it.
- Lima nested virtualization is unchecked, and nested VMs boot slower.

## Labels changed

| Item | Was | Now |
|---|---|---|
| Cluster inside the sandbox | k3d: k3s in privileged containers (CALL) | Sysbox system containers with systemd, sshd and k3s (DECIDED) |
| Where the learner's shell and the harness run | Inside the sandbox, next to k3d | On the VM, the workstation (DECIDED) |
| The learner's rights | Not stated | No sudo and no `docker` group on the VM; root inside the nodes only (DECIDED) |
| The node fault | `kill_node` stops a container | `StopNode` stops a container; `StopService` stops a unit (DECIDED, contracts `v0.1`) |
| Without KVM | A Docker + k3d container per session under Sysbox (OPEN, ADR 0003) | Sysbox nodes and a Sysbox workstation container on the course VM (DECIDED) |
| Providers | `DockerProvider`, `QemuProvider` | `QemuProvider`, `SysboxProvider` (CALL) |
| Mac development | `envmgr` with the Docker provider and privileged DinD (CALL) | A Lima VM with nested virtualization running the QEMU provider (CALL) |
| Template architectures | x64 only (CALL) | x64 and arm64 (CALL) |

## Alternatives considered

- **Keep k3d.** No systemd or sshd in the nodes, and privileged nodes. Rejected.
- **A QEMU VM per node.** Each node fully real, with its own kernel, but a session becomes four VMs: more RAM, slower boots, and a warm pool of VM groups. One VM per session stays easier to explain. Rejected.
- **kubeadm instead of k3s.** A separate `kubelet` unit, closer to most clusters, but about 1.5 GB more RAM per session. Rejected.
- **Kata Containers.** Needs KVM too, and with KVM, plain VMs are simpler. Rejected.
- **The harness on `cp`.** A fault on `cp` would cut the session off. Rejected.

## Still OPEN

- KVM on the course VM (platform#6), which decides whether the course VM runs §1–3 or §4.
- Nested virtualization in Lima on the Mac, which decides §5.
- Real RAM per sandbox with the node containers (platform#17).
