
![License](https://img.shields.io/badge/license-MIT-blue.svg)
[![Butane](https://github.com/noobping/infrastructure/actions/workflows/butane.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/butane.yml)
[![IPS](https://github.com/noobping/infrastructure/actions/workflows/ips.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/ips.yml)
[![Workstation](https://github.com/noobping/infrastructure/actions/workflows/workstation.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/workstation.yml)
[![Sway](https://github.com/noobping/infrastructure/actions/workflows/sway.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/sway.yml)
[![NAS](https://github.com/noobping/infrastructure/actions/workflows/nas.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/nas.yml)
[![VM images](https://github.com/noobping/infrastructure/actions/workflows/vms.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/vms.yml)
[![Validation](https://github.com/noobping/infrastructure/actions/workflows/validate.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/validate.yml)

# Infrastructure

Declarative infrastructure for workstations and servers.

This project delivers fully automated, immutable system images built on Fedora CoreOS (FCOS).  
From GNOME and Sway-based workstations to headless servers and storage nodes, the entire stack is defined as code using Butane, bootable containers, and CI/CD pipelines.

Nodes automatically configure themselves at first boot and continuously maintain their desired state.

## Stable NAS, independent workloads

The physical NAS changes only when storage, virtualization, networking, backup, or protection changes. Application updates are isolated to a role VM image or the Flux-managed K3s tree.

| Layer | Responsibility |
|---|---|
| Physical `nas.vm` | Btrfs, NFSv4, backups, KVM/libvirt, `br0`, Cockpit, NUT, TuneD `virtual-host`, and host IPS |
| `minecraft.vm` | Java and Bedrock servers |
| `jellyfin.vm` | Music and books, with direct LAN discovery and no GPU passthrough |
| `k3s.vm` | Single-node K3s, Flux, Caddy, Nextcloud, Euro-Office, Paperless, Uptime Kuma, and the registry |

Fedora CoreOS provides the immutable host and container plumbing, not a preconfigured Kubernetes control plane; the dedicated role image installs the pinned single-server K3s distribution.


## Start here

- [NAS host and backup behavior](nas/README.md)
- [VM inventory, bridge, provisioning, cutover, and rollback](vms/README.md)
- [K3s, Flux, SOPS, application migration, and service DNS](cluster/README.md)

## Verify deployment

```sh
skopeo inspect --format '{{ index .Labels "org.opencontainers.image.revision" }}' docker://ghcr.io/noobping/nas@sha256:<HASH FROM RPM OSTREE>
```
