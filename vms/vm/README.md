# VM base

`vm` is the reusable bootc image for KVM guests. It derives from the full
`ips` image, so ClamAV on-access scanning (including immediate removal) and
Suricata remain enabled in every guest. The guest nftables hooks inspect LAN
traffic while bypassing loopback and Podman/K3s internal interfaces.

The image adds the QEMU guest agent, verifies that an NFS client is available,
enables `cachefilesd` for persistent NFS read caching, and selects TuneD's
`virtual-guest` profile. A small SELinux oneshot permits confined workloads to
use NFS. Before the guest agent starts, a separate fail-closed oneshot enables
the `virt_qemu_ga_read_nonsecurity_files` boolean required for host-initiated
filesystem freeze/thaw. FS-Cache runs freely with at least 60% free space,
starts culling below 50%, and stops new cache writes below 40%, leaving room for
local guest runtime state. Guest Ignition performs a direct rpm-ostree rebase to
the role's `:latest` image, then the standard update timer follows that channel.
The image needs no separate update helper or verifier.

Build it locally with:

```sh
podman build \
  --build-arg IMAGE_NAMESPACE=ghcr.io/noobping \
  --build-arg TAG=latest \
  -t ghcr.io/noobping/vm:latest vms/vm
```

CI builds both architectures from `ips:latest`, publishes `vm:latest`, and then
builds and publishes each role's `:latest` multi-architecture manifest.
