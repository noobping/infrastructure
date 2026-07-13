# K3s VM

This image embeds K3s `v1.36.1+k3s1` from the signed upstream release and
verifies its architecture-specific checksum. It also installs the pinned
CoreOS K3s SELinux policy RPM and starts K3s with SELinux enforcement enabled.

The verified binary is installed directly as immutable `/usr/bin/k3s`.
`k3s.service` restores the policy labels on writable K3s state before starting
the server; no runtime installer or wrapper is involved.

The VM state disk must use virtio serial `k3s-data`; Ignition mounts it at
`/var/lib/rancher/k3s`. The single server uses the standard pod and service
CIDRs, keeps ServiceLB and local-path storage, and disables only bundled
Traefik so Caddy can own ports 80 and 443.

Override `K3S_VERSION` only together with a reviewed upstream checksum file.
The SELinux RPM release, version, and SHA-256 are separate build arguments so
Renovate can update them deliberately.

## Application-consistent backup

The host invokes `backup-prepare` through QEMU Guest Agent. It suspends the
Flux Kustomization and Nextcloud CronJobs, closes Caddy ingress, runs the
Paperless exporter, scales every state-writing Deployment to zero, and only
then writes PostgreSQL dumps, a consistent K3s SQLite copy, the Flux age
Secret, and the Caddy CA archive. Workloads remain quiesced until the host has
snapshotted both the NFS-backed `docs` subvolume and the VM state disk.

After thawing the guest, the host invokes the idempotent `backup-finish` hook,
which restores the exact prior replicas, CronJob suspension flags, and Flux
suspension state. The quiesce state is stored on the K3s data disk so failure
cleanup and a restored raw VM snapshot can recover it. After restoring such a
snapshot, run this once before accepting traffic:

```sh
sudo /usr/libexec/infrastructure/backup-finish
```

Then verify that all recorded Deployments and CronJobs have their previous
replica and suspension state and that Flux reconciliation is healthy.
