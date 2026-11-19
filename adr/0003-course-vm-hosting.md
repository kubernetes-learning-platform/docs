# ADR 0003: One course-provided VM, reached over Tailscale

- **Status:** Accepted · 2026-11-12, revised 2026-11-14 · **DECIDED** by Filip. The sandbox type stays **OPEN** until nested virtualization is checked on the VM (platform#6). The deploy format is **OPEN**.
- **Changed by:** [ADR 0004](0004-node-machines-in-the-sandbox.md), 2026-11-19. The cluster inside a sandbox is Sysbox node machines instead of k3d, the no-KVM column of §3 becomes Sysbox nodes with a workstation container on the course VM, and §4's build order no longer starts with a Docker provider. The KVM column of §3 still holds.
- **Supersedes:** the hosting parts of [ADR 0001](0001-hosting-and-harness-transport.md): the three machines on a WireGuard mesh (§1), Proxmox sandboxes (§2), `envmgr` on the Proxmox host (§3) and the OpenTofu and Packer plans (§5). ADR 0001's WebSocket-only harness (§4) and `envmgr`'s reconcile loop (§5) still hold.
- **Changes:** the machine details in [ADR 0002](0002-learner-driven-scenarios-and-scale-target.md) (the Hetzner box, the home PC, RabbitMQ on the mesh address). The rest of ADR 0002 holds.

Labels: **DECIDED** by Filip · **CALL** chosen while writing this, change freely · **OPEN** not decided.

---

## Context

- The course provides the team **one VM: 16 vCPU, 32 GB RAM, full root access.**
- ADR 0001 split the system across two machines joined over the internet. Its two biggest risks came from that split: the `api` ↔ `envmgr` link drops, and the demo depends on home power and internet.
- Not known yet: whether the VM supports **nested virtualization** (`/dev/kvm`) and its OS.

## Decision

### 1. The course VM runs everything (DECIDED)

| What | How |
|---|---|
| `web`, `api`, Postgres, RabbitMQ, Caddy | The stack, in the deploy format from §5 |
| `envmgr` | A systemd service on the VM itself, as before. It needs `/dev/kvm` and libvirt, so it stays outside the stack in every deploy format. |
| The sandboxes | One per session, of the type chosen in §3 |

`api` reaches `envmgr` on the same machine, so **the internet link between them is gone**. The reconnect logic from flow 10 stays, because `envmgr` can still restart, but it stops being the main demo-day risk.

The Hetzner box and the home PC are no longer part of the plan.

### 2. Access over Tailscale, served on our own domain (DECIDED)

- The VM joins a **Tailscale** tailnet with key expiry turned off. Two-factor authentication and device approval are on for the tailnet (platform#9).
- A tailnet ACL allows only SSH and the app's HTTPS port on the VM. **No port is open to the internet.**
- The demo laptop, the team and the graders reach the app from devices in the tailnet.
- **Caddy** serves the app on our Cloudflare domain with a real certificate (platform#12):
  - a Caddy image built with the Cloudflare DNS module
  - a Cloudflare token limited to DNS edits on one zone
  - a DNS-only record pointing at the VM's Tailscale address
  - Caddy listens only on the Tailscale address and gets its certificate through the **DNS-01** challenge, so nothing has to reach it from the internet
- The name resolves publicly, but the address it points to is reachable only inside the tailnet.
- A real certificate makes the page a secure context (clipboard, `crypto.randomUUID`) without trusting a private CA on every device.

### 3. The sandbox type depends on KVM (OPEN until checked)

| | KVM available (preferred) | No KVM |
|---|---|---|
| **Sandbox** | A small VM per learner, run with QEMU/libvirt by a new `QemuProvider` | A container per learner running Docker + k3d, under the **Sysbox** runtime instead of `--privileged` |
| **Copies** | Linked clones: qcow2 files backed by one template image | One container image, copied on write |
| **Identity** | cloud-init (NoCloud) writes the address and the one-time token | Env vars, as in the Docker provider today |
| **Image build** | Packer with the QEMU builder, run by the sandbox-template workflow on the VM (platform#21) | A container image build |
| **Network** | An isolated libvirt bridge with no route to the internet or the host network. nftables rules let a sandbox reach only `envmgr`'s harness endpoint (platform#10). | The same rule, applied to the container network |
| **Isolation** | Own kernel per learner, as in ADR 0001 | Shared kernel with the VM; Sysbox maps container root to an unprivileged user |
| **Fits in 32 GB** (estimate) | About 6–8 sandboxes | About 10–12 sandboxes |

Both keep the rule from ADR 0001: a sandbox's network reaches **only** `envmgr`'s harness endpoint.

**Rejected: installing Proxmox on the course VM.** `envmgr` would barely change, but Proxmox replaces the kernel and the network setup of a remote machine you can only reach over SSH, where one bad network change locks you out.

### 4. Build order (CALL)

1. **The Docker provider first.** It's already the first step of M1, it runs on the VM with or without KVM, and it's what development on Macs uses.
2. **Check the VM** (`ls -l /dev/kvm`, `grep -cE 'vmx|svm' /proc/cpuinfo`, `systemd-detect-virt`) and record the result in platform#6 and in this ADR.
3. **Then** build the `QemuProvider` if KVM is there. If not, harden the Docker provider with Sysbox, after a short spike confirming Sysbox runs k3d.

### 5. Deploy format (OPEN)

Docker Compose is not a requirement. Two options are on the table, and neither is chosen:

| | Docker Compose | Helm chart on single-node k3s |
|---|---|---|
| **Runs** | `web`, `api`, Postgres, RabbitMQ, Caddy | `web`, `api`, Postgres, RabbitMQ, plus ingress |
| **`envmgr`** | systemd unit on the host | systemd unit on the host |
| **Local dev** | The same tool | Compose stays for local dev either way |

Before either is written, these need a plan:

- ingress and TLS: Caddy in front, or Traefik with cert-manager and DNS-01
- k3s's iptables rules next to the libvirt bridge and the nftables sandbox isolation
- persistence and backup for Postgres (platform#29) and RabbitMQ
- how the deploy workflow in §6 rolls a version forward and back

This gets settled in a revision of this ADR.

### 6. Deploys (DECIDED)

- `api` and `web` images are built on every merge to `main` and pushed to GHCR, tagged with the commit SHA (platform#19).
- A **private deploy repo** has a manual `workflow_dispatch` workflow that takes the image SHAs to deploy (platform#15). It updates the stack, smoke-tests `/healthz`, and restores the previous version if the test fails. Only Filip can start it.
- It runs on a **self-hosted runner on the VM** (platform#14), as its own user, with its own label, registered only to private repos. The same runner builds the sandbox template, which needs KVM. The code repos are public and can't use this runner, so the deploy repo starts that build too.
- Each deploy records a deployment and its status on `api` and `web` through a GitHub App, so both repos show the commit running in `production` (platform#16).
- Everything else in CI stays on GitHub-hosted runners.

### 7. No infrastructure code (CALL)

- The course VM isn't ours to create, so there is no OpenTofu. An install script in `platform/deploy/vm/` sets up the base system, Tailscale and libvirt (platform#8 to #10).
- Sandboxes are created by `envmgr`'s reconcile loop, not by infrastructure code, as in ADR 0001.

### 8. Observability while testing (CALL)

Prometheus, Grafana, Loki and a log collector run on the VM without publishing any port. Grafana is served through Caddy, so the Tailscale ACL needs no extra port. Harness logs reach Loki through `envmgr`, since a sandbox can reach nothing else (platform#18).

### 9. Capacity (CALL)

- About **3–4 GB** for the OS and the stack, leaving about **28 GB** for sandboxes.
- `Sandbox__MaxConcurrent` is set from the real per-sandbox RAM measured on the VM (platform#17).
- CPU isn't the limit: 16 cores cover idle clusters, and capping parallel boots handles a rush of starts.
- **The 30-sandbox design target is unchanged.** More capacity means more sandbox hosts, each one another consumer of the queue.

## What doesn't change

- `api`, `web`, the harness, `contracts`, RabbitMQ, scenarios and the helper.
- The harness speaks WebSocket and opens with `Hello{sandboxId, token, version}`.
- Nothing is public.

## Consequences

**Better:**
- No internet link between `api` and `envmgr`, and no dependency on home power or internet on demo day.
- No machine of ours needs a public endpoint: Tailscale handles NAT traversal, so the WireGuard hub goes too.
- A real certificate replaces Caddy's internal CA.
- The whole Proxmox setup goes: the home box configuration, its OpenTofu code, the runner LXC and the Proxmox token.
- One machine to deploy, monitor and debug.

**Costs:**
- New provider code: the `QemuProvider`, or a Sysbox spike plus hardening.
- Nested VMs boot slower than VMs on bare metal.
- 32 GB caps the demo at roughly 6–12 sandboxes.
- The stack and the sandboxes share a machine. On the container path, a sandbox escape could reach the stack, so Sysbox is required there.
- The demo depends on the course VM and on Tailscale's coordination service.
- Services that bind to the Tailscale address must start after Tailscale.

## Labels changed

| Item | Was | Now |
|---|---|---|
| Stack host | Hetzner box (DECIDED, ADR 0001) | The course VM (DECIDED) |
| Sandbox host | Proxmox box at home (DECIDED, ADR 0001) | The course VM (DECIDED) |
| Network | WireGuard mesh with a Hetzner hub (DECIDED, ADR 0001) | Tailscale tailnet (DECIDED) |
| HTTPS | Caddy's internal CA, trusted on the demo laptop (CALL) | Our Cloudflare domain, certificate through DNS-01 (DECIDED) |
| VMM | Proxmox VE, i.e. QEMU/KVM (DECIDED) | QEMU/libvirt if KVM is available, otherwise Sysbox containers (OPEN) |
| VM image tooling | Packer with the Proxmox builder (CALL) | Packer with the QEMU builder, or a container image (CALL) |
| `api` ↔ `envmgr` | gRPC over the WireGuard mesh (CALL) | gRPC on the same machine (CALL) |
| Deploy format | Docker Compose (DECIDED, ADR 0001) | Compose or a Helm chart on k3s (OPEN) |
| Deploys | Not planned | Manual `workflow_dispatch` from a private deploy repo, on a self-hosted runner (DECIDED) |
| Infrastructure code | OpenTofu for Hetzner and Proxmox (CALL) | An install script for the VM (CALL) |
| Self-hosted runner | LXC on the Proxmox box (CALL) | The course VM (CALL) |
| Hetzner box, home PC | Stack host, sandbox host | Not used |

## Alternatives considered

- **Keep the Hetzner box as a WireGuard hub.** Only needed if the VM can't accept connections. Tailscale reaches the VM from anywhere without a hub. Rejected.
- **Make the app public with real auth.** More to harden, and nothing in the demo needs it. Rejected, as in ADR 0001.
- **Proxmox on the course VM.** See §3. Rejected.

## Still OPEN

- Nested virtualization on the VM, which decides §3.
- The VM's OS.
- Whether Sysbox runs k3d, if the container path is needed.
- The deploy format in §5.
- Real RAM per sandbox, measured on the VM.
