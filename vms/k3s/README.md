# K3s VM

K3s keeps its runtime, containerd state, and SQLite control-plane database on
the VM root disk. All 17 application claims use hard NFS 4.2 mounts with
FS-Cache. The bundled local-storage provisioner is disabled.

Only `/var/lib/rancher/k3s/backups` is an NFS mount inside the K3s state tree.
Verify it and the claims after boot:

```sh
ssh nick@k3s.vm \
  'findmnt -T /var/lib/rancher/k3s/backups && sudo k3s kubectl get pv,pvc -A'
```

## Backup

Follow the [shared backup order](../README.md#safety-and-backups). The prepare
hook writes PostgreSQL dumps and recovery material to the NFS backup mount.
PostgreSQL dumps are the restore source; live NFS database snapshots are only
crash-consistent. The backup contains a root-only but unencrypted copy of the
Flux age Secret, so keep a separate encrypted offline copy of the age key.
