# VM base

`vm` is the reusable bootc image for KVM guests. It derives from the full
`ips` image, so ClamAV on-access scanning (including immediate removal) and
Suricata remain enabled in every guest. The guest nftables hooks inspect LAN
traffic while bypassing loopback and Podman/K3s internal interfaces.

The image adds the QEMU guest agent, verifies that an NFS client is available,
and selects TuneD's `virtual-guest` profile. Before the guest agent starts, a
fail-closed oneshot persistently enables the SELinux
`virt_qemu_ga_read_nonsecurity_files` boolean required for host-initiated
filesystem freeze/thaw. The image also installs a SHA256-pinned Cosign verifier.
First boot and daily updates accept only images signed by this repository's
`vms.yml` workflow on `refs/heads/main` through GitHub's OIDC issuer, extract the
verified manifest digest, and pass only that immutable digest to rpm-ostree. VM
images are therefore published only from `main`.

Build it locally with:

```sh
podman build \
  --build-arg IMAGE_NAMESPACE=ghcr.io/noobping \
  --build-arg TAG=latest \
  -t ghcr.io/noobping/vm:latest vms/vm
```

CI builds both architectures from `latest@<verified-manifest-digest>`, so every
architecture uses the same Cosign-verified immutable IPS parent even while the
child architecture images are being assembled.
