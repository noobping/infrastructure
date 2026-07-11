# NAS

Create `/var/lib/containers/secrets/admin-password` before expecting the Uptime Kuma bootstrap to finish.

You can also set `/var/lib/containers/secrets/admin-username`; it defaults to `admin`.

This image no longer provisions FreeIPA, FreeRADIUS, or any other domain-controller services.

## Backups

`btrfs-backup.timer` runs weekly, with up to one hour of random delay. It
creates read-only snapshots of the SSD subvolumes and transfers them to
`/var/srv/hdd/backups/ssd` with `btrfs send/receive`. The newest matching
snapshot is used as the parent for an incremental transfer. Three weekly
snapshots are retained by default on both filesystems.

The backed-up subvolumes are `apps`, `books`, `docs`, `git`, `music`, `photos`,
`touhou`, and `videos`. `touhou` is listed separately because a Btrfs snapshot
does not recursively snapshot nested subvolumes.

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

## Nextcloud

The container exposes `/var/srv/docs/shared` at the same path. Before adding
files, create the directory and grant Nextcloud's `www-data` user access:

```sh
sudo install -d -m 2770 -o docs -g docs /var/srv/docs/shared && sudo setfacl -m 'u:33:rwx,m::rwx,d:u::rwx,d:u:33:rwx,d:g::rwx,d:m::rwx,d:o::---' /var/srv/docs/shared
```

Then enable the bundled **External storage support** app and add an
administrator-managed **Local** storage named `/Shared` with configuration path
`/var/srv/docs/shared`.

## Paperless

The Paperless PostgreSQL and Redis backends run on a private container network.
Open `http://nas:8000`, or use the `http://nas/paperless` shortcut. The first
visit prompts you to create the superuser account. Port 8000 serves plain HTTP.

Paperless watches `/var/srv/docs/paperless/consume` for new documents. Its
document archive and exports are stored in:

- `/var/srv/docs/paperless/media`
- `/var/srv/docs/paperless/export`

Apache Tika and Gotenberg add consumption support for Word, Excel, PowerPoint,
OpenDocument (`.odt`, `.ods`, `.odp`), and email (`.eml`) files. These converter
services are internal and stateless, so they add no backup directories.

Application state and database data live below
`/var/lib/containers/paperless`. The prepare service creates these directories
and stable random secrets automatically. Create a consistent application export
before a backup with:

```sh
sudo podman exec paperless document_exporter ../export
```

Back up `/var/srv/docs/paperless` and
`/var/lib/containers/secrets/paperless`. The documents in `media` are stored
unencrypted. See the [official administration documentation](https://docs.paperless-ngx.com/administration/).

Check the complete stack after an image update with:

```sh
sudo systemctl status \
  paperless.service paperless-db.service paperless-redis.service \
  paperless-gotenberg.service paperless-tika.service

sudo journalctl -b \
  -u paperless.service -u paperless-db.service -u paperless-redis.service \
  -u paperless-gotenberg.service -u paperless-tika.service
```

## Minecraft

## Bedrock

Enter server console

```sh
sudo podman exec -it systemd-bedrock /bin/bash
```

Show allowlist

```sh
send-command allowlist list
```

Allow player

```sh
send-command allowlist add "YourGamertag"
```

OP player

```sh
send-command op "YourGamertag"
```

### Java

Enter server console

```sh
sudo podman exec -it systemd-minecraft rcon-cli
```

Show allowlist

```sh
whitelist list
```

Allow player

```sh
whitelist add "YourUsername"
```

OP player

```sh
op "YourUsername"
```
