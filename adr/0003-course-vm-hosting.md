# ADR 0003: One course-provided VM runs the stack and the sandboxes

- **Status:** Accepted · 2026-11-12 · **DECIDED** by Filip. The sandbox type stays **OPEN** until nested virtualization is checked on the VM.
- **Changes:** the machine plan in [ADR 0001](0001-hosting-and-harness-transport.md) (stack on a Hetzner box, sandboxes as Proxmox VMs on a PC at home) and the Proxmox provider. ADR 0001's harness transport and isolation rules stay, and so does all of [ADR 0002](0002-learner-driven-scenarios-and-scale-target.md).

Labels: **DECIDED** by Filip · **CALL** chosen while writing this, change freely · **OPEN** not decided.

---

## Context

- The course provides the team **one VM: 16 vCPU, 32 GB RAM, full root access.**
- ADR 0001 split the system across two machines joined over the internet. Its two biggest risks came from that split: the `api` ↔ `envmgr` link drops (risk 3), and the demo depends on home power and internet (risk 4).
- Not known yet: whether the VM supports **nested virtualization** (`/dev/kvm`), its OS, and what its network allows (incoming connections, outbound UDP for WireGuard).

## Decision

### 1. The course VM is the main machine (DECIDED)

It runs everything the demo needs:

| What | How |
|---|---|
| The stack | Docker Compose: Caddy, `web`, `api`, Postgres, RabbitMQ |
| `envmgr` | systemd service, as before |
| The sandboxes | One per session, of the type chosen in §2 |

`api` reaches `envmgr` on the same machine, so **the internet link between them is gone**. The reconnect logic from flow 10 stays, because `envmgr` can still restart, but it stops being the main demo-day risk.

### 2. The sandbox type depends on KVM (OPEN until checked)

| | KVM available (preferred) | No KVM |
|---|---|---|
| **Sandbox** | A small VM per learner, run with QEMU/libvirt by a new `QemuProvider` | A container per learner running Docker + k3d, under the **Sysbox** runtime instead of `--privileged` |
| **Copies** | Linked clones: qcow2 files backed by one template image | One container image, copied on write |
| **Identity** | cloud-init (NoCloud) writes the address and the one-time token | Env vars, as in the Docker provider today |
| **Image build** | Packer with the QEMU builder, on the course VM | A container image build |
| **Isolation** | Own kernel per learner, as in ADR 0001 | Shared kernel with the course VM; Sysbox maps container root to an unprivileged user |
| **Fits in 32 GB** (estimate) | About 6–8 sandboxes | About 10–12 sandboxes |

Both keep the rule from ADR 0001: a sandbox's network reaches **only** `envmgr`'s harness endpoint.

**Rejected: installing Proxmox on the course VM.** `envmgr` would barely change, but Proxmox replaces the kernel and the network setup of a remote machine you can only reach over SSH, where one bad network change locks you out.

### 3. Build order (CALL)

1. **The Docker provider first.** It's already the first step of M1, it runs on the course VM with or without KVM, and it's what development on Macs uses.
2. **Ask for nested virtualization now,** before the VM is handed over. It's usually one setting for whoever runs the hypervisor.
3. **Check the VM** (`/dev/kvm`, `grep -cE 'vmx|svm' /proc/cpuinfo`, `systemd-detect-virt`) and record the result in this ADR.
4. **Then** build the `QemuProvider` if KVM is there. If not, harden the Docker provider with Sysbox, after a short spike confirming Sysbox runs k3d.

### 4. The other machines become optional (CALL)

| Machine | New role |
|---|---|
| **Hetzner box** | Only the WireGuard hub, and only if the course VM can't accept incoming connections. The course VM dials out to it, as the home PC would have. |
| **Home PC** | A backup demo host, or a second sandbox host later through the queue |
| **Demo laptop** | Unchanged: the browser, on the mesh |

### 5. Capacity (CALL)

- About **3–4 GB** for the OS and the stack, leaving about **28 GB** for sandboxes.
- `Sandbox__MaxConcurrent` is set from the real per-sandbox RAM measured in M1.
- CPU isn't the limit: 16 cores cover idle clusters, and capping parallel boots handles a rush of starts.
- **The 30-sandbox design target is unchanged.** More capacity means more sandbox hosts, each one another consumer of the queue.

### 6. CI and infrastructure code (CALL)

- The self-hosted runner moves to the course VM, for image builds and deploys. Everything else stays on GitHub-hosted runners.
- OpenTofu loses its Proxmox part. It keeps the Hetzner part only if Hetzner stays as the hub.
- The course VM isn't ours to create, so it's set up by an install script in `platform/deploy/` instead of OpenTofu.

## What doesn't change

- `api`, `web`, the harness, `contracts`, RabbitMQ, scenarios and the helper.
- The harness speaks WebSocket and opens with `Hello{sandboxId, token, version}`.
- Nothing is public: the app stays on the WireGuard mesh.
- Sandboxes are created by `envmgr`'s reconcile loop, not by infrastructure code.

## Consequences

**Better:**
- No internet link between `api` and `envmgr`, and no dependency on home power or internet on demo day.
- The whole Proxmox setup goes: the home box configuration, its OpenTofu code, the runner LXC and the Proxmox token.
- One machine to deploy, monitor and debug.

**Costs:**
- New provider code: the `QemuProvider`, or a Sysbox spike plus hardening.
- Nested VMs boot slower than VMs on bare metal.
- 32 GB caps the demo at roughly 6–12 sandboxes.
- The stack and the sandboxes share a machine. On the container path, a sandbox escape could reach the stack, so Sysbox is required there, and moving the stack back to Hetzner remains an option.
- The demo now depends on the course VM's network, whose rules aren't known yet.

## Labels changed

| Item | Was | Now |
|---|---|---|
| Stack host | Hetzner box (DECIDED, ADR 0001) | The course VM (DECIDED) |
| Sandbox host | Proxmox box at home (DECIDED, ADR 0001) | The course VM (DECIDED) |
| VMM | Proxmox VE, i.e. QEMU/KVM (DECIDED) | QEMU/libvirt if KVM is available, otherwise Sysbox containers (OPEN) |
| VM image tooling | Packer with the Proxmox builder (CALL) | Packer with the QEMU builder, or a container image (CALL) |
| `api` ↔ `envmgr` | gRPC over the WireGuard mesh (CALL) | gRPC on the same machine (CALL) |
| Hetzner box | The stack | Optional WireGuard hub (CALL) |
| Home PC | Sandbox host | Optional backup or second sandbox host (CALL) |
| Infrastructure code | OpenTofu for Hetzner and Proxmox (CALL) | An install script for the course VM, plus OpenTofu for Hetzner if kept (CALL) |
| Self-hosted runner | LXC on the Proxmox box (CALL) | The course VM (CALL) |

## Still OPEN

- Nested virtualization on the course VM, which decides §2.
- The VM's OS, whether it accepts incoming connections, and whether outbound UDP works for WireGuard. If it doesn't, the mesh needs a fallback.
- Whether Sysbox runs k3d, if the container path is needed.
- Real RAM per sandbox, measured in M1.

ARCHITECTURE, FEATURES and the READMEs get updated once the KVM check settles §2.
