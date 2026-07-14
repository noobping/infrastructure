# NAS

`btrfs-backup.timer` runs weekly, with up to one hour of random delay. It
creates read-only snapshots of the SSD subvolumes and transfers them to
`/var/srv/hdd/backups/ssd` with `btrfs send/receive`. The newest matching
snapshot is used as the parent for an incremental transfer. Three weekly
snapshots are retained by default on both filesystems.

The backed-up subvolumes are `apps`, `books`, `caddy`, `docs`, `git`, `music`,
`photos`, `touhou`, and `videos`. `caddy` preserves the local certificate
authority, including its private key, so access to the backup must remain
restricted. `touhou` is listed separately because a Btrfs snapshot does not
recursively snapshot nested subvolumes.

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
