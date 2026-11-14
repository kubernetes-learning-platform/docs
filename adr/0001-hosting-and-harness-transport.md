# ADR 0001: Hosting over a WireGuard mesh, Proxmox sandboxes, WebSocket-only harness

- **Status:** Accepted · 2026-11-04 · **DECIDED** by Filip. **Superseded** for hosting by [ADR 0003](0003-course-vm-hosting.md) on 2026-11-14: §1 (the WireGuard mesh), §2 (Proxmox sandboxes), §3 (`envmgr` on the Proxmox host) and the OpenTofu and Packer plans in §5 no longer apply. §4 (the WebSocket-only harness) and the reconcile loop in §5 still hold.
- **Changes:** the single-host deployment and the vsock transport from [PROJECT-BRIEF](../PROJECT-BRIEF.md) §1, §4, §5 and §10, and the matching parts of [ARCHITECTURE](../ARCHITECTURE.md) as of 2026-11-02.

---

## Context

The plan assumed one Linux + KVM machine running everything: the Compose stack, `envmgr`, and microVMs (Firecracker or Cloud Hypervisor) whose harness talks to `envmgr` over vsock.

What the team actually has, and needs:

- A **small Hetzner cloud server** that is always on, and a **spare PC at home** that can run Proxmox VE and has the RAM for 3–4 GB sandbox VMs.
- The demo is presented from **Filip's laptop**.
- vsock caused two of the listed technical risks (no `AddressFamily.Vsock` in .NET, and `/dev/vhost-vsock` device access), and Proxmox has no vsock setting.
- The Docker provider already needed a harness WebSocket with a per-sandbox token, so a second transport existed anyway.

## Decision

### 1. Three machines on one WireGuard mesh (DECIDED)

| Machine | Runs | Mesh address (CALL) | Reachable from the internet |
|---|---|---|---|
| **Hetzner box** | Docker Compose: Caddy, `web`, `api`, Postgres | `10.66.0.1` | WireGuard (UDP 51820) and SSH only |
| **Proxmox box** (home server PC) | Proxmox VE, `envmgr`, the sandbox VMs | `10.66.0.2` | Nothing. It dials out to the Hetzner box. |
| **Demo laptop** | The browser on the projector | `10.66.0.3` | Nothing. It dials out to the Hetzner box. |

- The Hetzner box is the only peer with a public endpoint. The other two connect out to it with `PersistentKeepalive`, so neither the home network nor the demo venue needs port forwarding.
- **Nothing is public.** Caddy listens only on the mesh address. Graders try the app from a device on the mesh.
- More peers (teammates, a graders' laptop) get their own address in `10.66.0.0/24`.

### 2. Sandboxes are Proxmox VMs (DECIDED)

- `ProxmoxProvider` replaces `VmmProvider`. Each sandbox is a **linked clone** of a VM template built by Packer, placed in the `kl-sandboxes` resource pool on an isolated bridge.
- cloud-init gives each clone its IP address and writes the harness settings (sandbox id, one-time token, envmgr URL).
- Proxmox runs the VMs, so they survive `envmgr` restarts without per-VM systemd units. `envmgr` re-adopts them by listing the pool.

### 3. envmgr runs as a systemd service on the Proxmox host (CALL)

- The host is the mesh peer, so `api` reaches `envmgr` without extra routing.
- It calls the Proxmox API on `localhost` with a token limited to the sandbox pool. **The token never leaves the box.**
- It can write cloud-init snippets straight to host storage.
- It no longer needs `/dev/kvm`, `/dev/net/tun` or host network plumbing: Proxmox does all of that.

### 4. The harness only speaks WebSocket (DECIDED)

- vsock is dropped for every provider. The harness dials `envmgr`'s WebSocket endpoint and sends `Hello{sandboxId, token, version}`.
- On Proxmox, the endpoint listens on the host's address on the isolated sandbox bridge. Static firewall rules make it the **only** thing a sandbox can reach: no internet, no home LAN, no mesh, no other sandboxes.
- The Docker provider uses the same endpoint, handshake and token, passed as env vars.

### 5. IaC for long-lived infrastructure, a reconcile loop for sandboxes (CALL)

- **OpenTofu** in `platform/infra/`: the Hetzner server and its cloud firewall (`hcloud` provider), and on Proxmox the sandbox bridge, resource pool, `envmgr`'s user, role and API token, and an LXC for a self-hosted CI runner (`bpg/proxmox` provider).
- **Packer** in `sandbox/images/base/` builds the Proxmox VM template.
- **Sandboxes are not IaC.** `envmgr` runs one reconcile loop: the desired state is `WarmPool__Size` idle sandboxes plus the ones in use, the actual state is the VMs in the pool, and it clones or deletes until they match. It also deletes VMs past `Sandbox__MaxLifetime` and VMs it has no record of.

## Consequences

**Better:**
- `envmgr` loses its hardest host code: systemd units per VM, taps, bridge and nftables management, re-adoption from a state directory. It keeps only tokens and IP leases on disk.
- Technical risks 3 (vsock in .NET) and 4 (`DeviceAllow=/dev/vhost-vsock`) are gone.
- If the Hetzner box is compromised, the attacker reaches only `envmgr`'s narrow gRPC API, not Proxmox.
- Replays are served from Postgres on the Hetzner box, so the recorded fallback still plays when the Proxmox box is unreachable.
- Both machines can be rebuilt from the repos.
- Auth can stay light, because nothing is public.

**Costs:**
- The `api` ↔ `envmgr` link crosses the internet and will drop. `api` must reconnect and reload the topology ([ARCHITECTURE flow 10](../ARCHITECTURE.md#6-key-flows)).
- The demo depends on home power and internet, and on the venue allowing outbound UDP for WireGuard.
- `envmgr` runs on the Proxmox host and is the one thing a sandbox can reach. Users get a real bash in the VM, so a bug in the harness endpoint is a host bug.
- Caddy is published only on the mesh address, so Docker must start after WireGuard.
- Browsers only treat HTTPS pages as secure contexts (clipboard, `crypto.randomUUID`), so the mesh still needs HTTPS: Caddy's internal CA, trusted once on the demo laptop (CALL).
- GitHub-hosted runners can't reach Proxmox, so `vm-image.yml` needs a self-hosted runner on the Proxmox box.

## Labels changed

| Item | Was | Now |
|---|---|---|
| Deployment | Single host, one team member's PC (DECIDED) | Hetzner box + Proxmox box + demo laptop on a WireGuard mesh (DECIDED) |
| Demo network | LAN only (DECIDED 2026-11-02) | Mesh only (DECIDED) |
| Demo host OS | OPEN | Proxmox VE on the home server PC (DECIDED) |
| VMM | Firecracker vs Cloud Hypervisor (OPEN) | Proxmox VE, i.e. QEMU/KVM (DECIDED) |
| Harness transport | vsock for VMs, WebSocket for Docker (DECIDED) | WebSocket for every provider (DECIDED) |
| Isolation | No network path from the VM; vsock only (DECIDED) | Isolated bridge; `envmgr`'s harness endpoint is the only reachable address (DECIDED) |
| VMs survive envmgr restarts | Own systemd unit per VM (DECIDED) | Still DECIDED; Proxmox runs the VMs instead |
| VM image tooling | mkosi vs Packer (OPEN) | Packer with the Proxmox builder (CALL) |
| api ↔ envmgr | gRPC over a unix socket | gRPC over the mesh, plain HTTP/2 on `10.66.0.2:7070`, accepted only from `10.66.0.1` (CALL) |
| Harness ↔ api relay | Recommended in the brief §5 (CALL) | Unchanged, now over WebSocket and the mesh |

## Alternatives considered

- **envmgr on the Hetzner box, calling Proxmox remotely.** The Proxmox token would leave home, and harness connections would still need a relay at home. Rejected.
- **envmgr in an LXC on the Proxmox box.** Better containment, but it needs its own mesh peer or routing, and a bind mount to write cloud-init snippets. Deferred: revisit if `envmgr`'s harness endpoint grows.
- **vsock on Proxmox through raw QEMU `args`.** Possible, but only through root-only raw arguments that Proxmox doesn't manage. Rejected.
- **Public internet with real auth.** The mesh already exists for the `api` ↔ `envmgr` link, and adding the demo laptop as a peer is cheaper than hardening auth. Rejected.
- **Terraform or Pulumi per sandbox.** A state file per session, a plan/apply cycle on every create, and stale state whenever the reaper or a crash deletes a VM. Rejected in favour of `envmgr`'s reconcile loop.
