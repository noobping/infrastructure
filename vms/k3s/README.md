# K3s VM

This image embeds K3s `v1.36.1+k3s1` from the upstream release and verifies its
architecture-specific checksum. It also installs the pinned CoreOS K3s SELinux
policy RPM and runs K3s with SELinux enforcement enabled.

K3s keeps its live runtime under `/var/lib/rancher/k3s` on the VM's root disk.
Containerd snapshots, kubelet state, and the single-server SQLite control-plane
database must not be placed on NFS. Application persistence is separate: all 17
cluster claims are statically bound to the NFS exports in
`cluster/storage/nfs-volumes.yaml`. The `backups` child is the only nested NFS
mount and is backed by the NAS's `/var/lib/containers/k3s-backups` directory.

The VM base starts `cachefilesd` before K3s. Every NFS PV requests `fsc`, NFS
4.2, and a hard mount. The bundled `local-storage` provisioner and Traefik are
disabled; ServiceLB remains enabled so Caddy can own ports 80 and 443.

Override `K3S_VERSION` only together with reviewed architecture checksums. The
SELinux RPM release, version, and SHA-256 are separate build arguments so they
can be updated deliberately.

## Backups

`backup-prepare` stops the application Deployments, then takes PostgreSQL
logical dumps, a consistent SQLite backup, the Flux age Secret, and the Caddy
CA. PostgreSQL and Redis StatefulSets remain running; PostgreSQL must stay up to
produce its dumps. The hook leaves the recorded Deployments stopped until
`backup-finish` restores their previous state.

The output is already on NFS and is included in the NAS `apps` snapshot. The
NAS timer does not call the guest hooks automatically, so run this sequence from
an administration machine. This mount always uses `nas.vm`, even if the cluster
PV setting uses an IP address, so that name must resolve in the guest:

```sh
ssh nick@k3s.vm \
  'sudo systemctl start var-lib-rancher-k3s-backups.mount && findmnt -T /var/lib/rancher/k3s/backups'
ssh nick@k3s.vm 'sudo /usr/libexec/infrastructure/backup-prepare'
ssh nick@nas.vm 'sudo systemctl start btrfs-backup.service'
ssh nick@k3s.vm 'sudo /usr/libexec/infrastructure/backup-finish'
```

Always run `backup-finish`, even if the NAS backup command fails. PostgreSQL
data directories use hard NFS mounts and synchronous exports, but their live
snapshots are only crash-consistent; the logical dumps are the canonical
restore source. The Flux Secret copy is root-only, not encrypted by this hook,
so keep a separately encrypted offline copy.
