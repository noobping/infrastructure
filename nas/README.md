# NAS

Cockpit is available at `https://nas.vm/` on port 443. The existing libvirt
configuration and services are unchanged.

## NFS

`nfs-server.service` serves NFSv4 only. The exports in `nfs/exports` are scoped
to `k3s.vm`, `minecraft.vm`, or `jellyfin.vm`; the firewall opens TCP 2049.
Application state uses synchronous exports. Only the isolated K3s application
paths and its root-only backup path use `no_root_squash`; several container
entrypoints must initialize ownership. Shared documents and VM-role paths remain
root-squashed, and the Jellyfin media exports are read-only.

The matching clients use NFS 4.2 hard mounts with `fsc`. Verify both ends after
deployment:

```sh
systemctl status nfs-server.service
sudo exportfs -v
ssh nick@k3s.vm 'systemctl is-active cachefilesd.service'
```

## Backups

`btrfs-backup.timer` runs weekly, with up to one hour of random delay. It
creates read-only snapshots of the SSD subvolumes and transfers them to
`/var/srv/hdd/backups/ssd` with `btrfs send/receive`. The newest matching
snapshot is used as the parent for an incremental transfer. Three weekly
snapshots are retained by default on both filesystems.

The backed-up subvolumes are `apps`, `books`, `caddy`, `docs`, `git`, `music`,
`photos`, `touhou`, and `videos`. `caddy` preserves the local certificate
authority, including its private key, so access to the backup must remain
restricted. `touhou` is listed separately because a Btrfs snapshot does not
recursively snapshot nested subvolumes. K3s backup artifacts are exported at
`/var/lib/containers/k3s-backups`, so the `apps` snapshot includes them.

Each Btrfs subvolume snapshot is atomic, but the loop is not atomic across all
subvolumes and does not quiesce guests. The ordinary timer is therefore a
crash-consistent filesystem backup. Use the K3s prepare/finish hooks around a
manual run when logical database dumps are required.

Run a backup immediately or inspect the schedule with:

```sh
sudo systemctl start btrfs-backup.service
systemctl list-timers btrfs-backup.timer
sudo journalctl -u btrfs-backup.service
```

The service accepts environment overrides named `BTRFS_BACKUP_SOURCE_ROOT`,
`BTRFS_BACKUP_SNAPSHOT_ROOT`, `BTRFS_BACKUP_DESTINATION_ROOT`,
`BTRFS_BACKUP_SUBVOLUMES`, and `BTRFS_BACKUP_RETENTION`. Set them with a systemd
drop-in if the storage layout or retention policy changes.
