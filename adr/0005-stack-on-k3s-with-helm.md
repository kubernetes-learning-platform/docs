# ADR 0005: The stack runs as a Helm chart on single-node k3s

- **Status:** Proposed · 2026-11-20 · **DECIDED** by Filip: Helm on single-node k3s, k3s's bundled Traefik as the ingress, cert-manager for TLS, Postgres and RabbitMQ as StatefulSets with a nightly `pg_dump` to S3, and every detail below, reviewed the same day. Accepted once the three checks in §8 pass on the test machines.
- **Changes:** [ADR 0003](0003-course-vm-hosting.md) §5, which left the deploy format OPEN, and the parts of ADR 0003 that assumed Caddy in front of the stack: §2 (Caddy serves the domain), §6 (the deploy smoke-tests `/healthz` and restores the previous version) and §8 (Grafana served through Caddy). ADR 0003's one course VM, Tailscale-only access, DNS-01 certificate and private deploy repo still hold.
- **Builds on:** [ADR 0004](0004-node-machines-in-the-sandbox.md) (`envmgr` drives libvirt or Docker with Sysbox on the host), the secrets plan in platform#28, and the dev Compose from platform#5.

Labels: **DECIDED** by Filip · **OPEN** not decided.

---

## Context

- ADR 0003 §5 left the deploy format OPEN between Docker Compose and a Helm chart on single-node k3s, with four things to plan first: ingress and TLS, k3s's iptables next to the sandbox network, persistence and backup, and rolling forward and back.
- Nothing deploys in Milestone 1. The first deploy to the course VM comes with Milestone 2.
- `envmgr` needs `/dev/kvm` and libvirt, or Docker with Sysbox on the fallback path, so it stays a systemd unit on the host in any format.
- The product teaches Kubernetes. Running the stack on Kubernetes gives the team the same practice: probes, rollouts, Ingress, Secrets and volumes.
- Local dev already runs Postgres and Caddy through Compose (platform#5), with the routes `/` → `web` and `/api`, `/ws` → `api`.

## Decision

### 1. A Helm chart on single-node k3s (DECIDED)

| Where | What |
|---|---|
| **k3s, namespace `kubelab`** (DECIDED) | `web` and `api` as Deployments, Postgres and RabbitMQ as StatefulSets, from one chart |
| **k3s, packaged components** | Traefik (§2), cert-manager (§3), local-path volumes (§5) |
| **The host** | k3s itself, `envmgr` (systemd), Tailscale, libvirt or Docker with Sysbox, the self-hosted runner |

- The chart lives in `platform/deploy/helm/kubelab/`. The prod values that aren't secret live in the private deploy repo, next to the deploy workflow.
- `api` reaches `envmgr`'s gRPC port on the host from the pod network. The rule that `envmgr`'s gRPC port accepts only the stack becomes an nftables rule allowing only the pod CIDR (`10.42.0.0/16` by default).
- `envmgr` reaches RabbitMQ through the RabbitMQ Service's ClusterIP, which the host can route to. The Service gets a fixed ClusterIP, so `envmgr`'s config doesn't depend on cluster DNS.
- Sandboxes still reach only `envmgr`'s harness endpoint. They can't reach the pod network, the Services or RabbitMQ.

### 2. Ingress: k3s's bundled Traefik (DECIDED)

- The chart declares standard **Ingress** objects: `/` → `web`, `/api` and `/ws` → `api`, WebSockets included. These are the same routes as `platform/dev/Caddyfile.dev`, and a change to one changes the other in the same piece of work.
- Traefik is configured through a `HelmChartConfig` in k3s's manifests directory, never by editing k3s's own `traefik.yaml`.
- Local dev keeps Caddy in Compose. Three routes are easy to keep the same by rule, so production doesn't need Caddy for consistency.
- Ingress, not Gateway API, for now: it's the object the course teaches first, and Traefik supports both.

### 3. TLS: cert-manager with Cloudflare DNS-01 (DECIDED)

- A `ClusterIssuer` for Let's Encrypt solves **DNS-01** through Cloudflare, with the token from ADR 0003 §2, limited to DNS edits on one zone. The token comes from Parameter Store as a Secret (§6).
- A `Certificate` for our domain is stored as a Secret, which the Ingress uses. Certificates survive Traefik restarts.
- The DNS-only record still points at the VM's Tailscale address, so nothing has to reach the VM from the internet. The Caddy image with the Cloudflare module is no longer needed.

### 4. Only the Tailscale address serves the app (DECIDED)

- ADR 0003 §2's rule holds: the app answers only on the VM's Tailscale address.
- k3s's ServiceLB exposes Traefik through hostPorts, and hostPort traffic is DNAT'd before it reaches `ufw`'s INPUT rules, so a host firewall alone wouldn't stop the public address. So:
  - k3s runs with `--disable=servicelb`.
  - Traefik's ports 80 and 443 are hostPorts bound with `hostIP` to the Tailscale address, or Traefik runs with `hostNetwork` and its entry points bound to that address. Which one is chosen in the check in §8.
  - k3s starts after `tailscaled`, so the address exists when Traefik binds it.
- The k3s API (6443) and the kubelet (10250) stay closed to everything but the host and the pod network. The tailnet ACL still allows only SSH and the app's HTTPS port.

### 5. Postgres and RabbitMQ (DECIDED)

- Both run as StatefulSets with official images, on k3s's **local-path** volumes under `/var/lib/rancher/k3s/storage/`.
- **Postgres backup** (platform#29): a nightly CronJob runs `pg_dump` and uploads the dump to an S3 bucket in `eu-north-1`, the account's only region. Old dumps expire through a bucket lifecycle rule, 14 days.
- The upload needs an AWS credential on the VM, which platform#28's rule forbids. So there is one exception: an IAM user that can only `PutObject` under the backup prefix, with no read or delete, stored as a Secret.
- **RabbitMQ** keeps its queues on a volume and has no backup. It only holds provisioning and teardown jobs, so losing the volume loses only the jobs in flight.

### 6. Deploys (DECIDED, refines ADR 0003 §6)

- The deploy workflow in the private deploy repo still runs on the self-hosted runner, still takes the image SHAs, and still records deployments on `api` and `web` (platform#15, platform#16).
- Before the upgrade, it reads the stack's values from Parameter Store through GitHub OIDC (platform#45) and writes them as Kubernetes Secrets. For the stack, these Secrets replace the env files of platform#46. Ansible still writes env files for the host's own services, such as `envmgr`.
- Then `helm upgrade --install --atomic --wait --timeout 5m` sets the image tags. `/healthz` is `api`'s readiness probe, so a rollout that never becomes ready rolls back on its own. A final request through Traefik checks the whole path.
- `helm rollback` restores a previous release by hand.

### 7. The host (DECIDED)

- k3s is installed by an Ansible role, at a pinned version, from the playbook that's still being planned. Its flags are `--disable=servicelb` and `--write-kubeconfig-mode=600`.
- The `HelmChartConfig` for Traefik and the cert-manager install are files the role puts in k3s's manifests directory.
- **Capacity:** k3s, Traefik and cert-manager take about 1–1.5 GB, within ADR 0003 §9's 3–4 GB for the OS and the stack (estimate).

### 8. Checks before this is accepted (DECIDED)

1. **Tailscale-only serving.** With ServiceLB off and Traefik bound to the Tailscale address, the app answers there and not on any other address. On the Hetzner test VM.
2. **k3s next to libvirt.** Pods, Services and Ingress work while sandbox VMs run on the libvirt bridge, and the nftables rules still keep sandboxes to `envmgr`'s harness endpoint. On the QEMU test VM on the home server.
3. **k3s next to Docker on the Sysbox path.** Docker sets the `FORWARD` policy to DROP, which can break pod traffic. Pods and the Ingress keep working with Docker and Sysbox sessions running. On the Hetzner test VM.

### 9. Local dev doesn't change (DECIDED)

Compose with Caddy, as in platform#5, with `compose.yaml` in `api` and `web` including it. Nobody runs k3s locally.

## Consequences

**Better:**
- Deploys roll back on their own when the new version never becomes ready, instead of through a custom script.
- The team runs the stack the way the product teaches: probes, rollouts, Ingress, Secrets and volumes.
- Traefik and the local-path volumes come with k3s. The custom Caddy build goes away.
- Certificates are Kubernetes objects, renewed by cert-manager and kept across restarts.

**Costs:**
- k3s, Traefik and cert-manager to install, upgrade and debug on the course VM.
- Two proxies to know: Caddy in local dev and Traefik in production, with the routes kept the same by rule.
- k3s's networking shares the host with libvirt or Docker, which needs the checks in §8 and care with every firewall change.
- Binding to the Tailscale address needs more care than a single Caddy `bind` line.
- Backups need a narrow AWS credential on the VM, if the exception in §5 is accepted.

## Labels changed

| Item | Was | Now |
|---|---|---|
| Deploy format | Compose or a Helm chart on k3s (OPEN, ADR 0003) | A Helm chart on single-node k3s (DECIDED) |
| Production proxy | Caddy with the Cloudflare DNS module (DECIDED, ADR 0003) | k3s's bundled Traefik with Ingress objects (DECIDED) |
| Certificates | Caddy, through DNS-01 (DECIDED, ADR 0003) | cert-manager, through DNS-01 (DECIDED) |
| Postgres and RabbitMQ data | Not planned (platform#29) | StatefulSets on local-path volumes; nightly `pg_dump` to S3 (DECIDED) |
| Rolling back | The deploy restores the previous version after a failed smoke test (DECIDED, ADR 0003) | `helm upgrade --atomic` with readiness probes, `helm rollback` by hand (DECIDED) |
| The stack's secrets on the VM | Env files written by Ansible (platform#46) | Kubernetes Secrets written by the deploy workflow; env files only for host services (DECIDED) |
| Local dev | Compose with Caddy (DECIDED) | Unchanged |

## Alternatives considered

- **Docker Compose.** The simplest, and the same tool as local dev, but rolling back would be our own script, and the team wouldn't run the stack on Kubernetes. Rejected.
- **Caddy in the cluster.** The same Caddyfile style as local dev, as a Deployment with a ConfigMap. It isn't an ingress controller, so the chart would have no Ingress objects, Traefik would be turned off, and Caddy would still need a custom build. Rejected.
- **Traefik's built-in ACME.** One component fewer, but k3s's Traefik keeps no storage by default, so it would need a volume for its certificates or request new ones on every restart and risk Let's Encrypt's rate limits. Rejected.
- **CloudNativePG for Postgres.** Backups to S3, point-in-time restore and failover, which one node with a small database doesn't need yet. Rejected for now.

## Still OPEN

- The checks in §8, and with them how Traefik binds to the Tailscale address (§4).
- KVM on the course VM (platform#6), which decides whether §8's second or third check matters there.
