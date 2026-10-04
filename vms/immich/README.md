# Immich VM

Immich v3.2.4 runs in a dedicated Fedora CoreOS guest with 8 vCPUs, 16 GiB RAM,
and one 80 GiB root disk. CPU inference is enabled; no GPU is required. The
server, machine-learning service, PostgreSQL/VectorChord, and Valkey images
are pinned. The Quadlets adapt the [upstream release bundle](https://github.com/immich-app/immich/blob/v3.2.4/docker/docker-compose.yml).

## Storage

| Data | NAS or guest location | Container path |
| --- | --- | --- |
| Existing photos | NAS `/var/srv/photos`, read-only NFS | `/mnt/photos` |
| Uploads, previews, videos, database dumps | NAS `/var/lib/containers/immich/data`, writable NFS | `/data` |
| PostgreSQL | Guest local volume `immich-postgres` | `/var/lib/postgresql/data` |
| Downloaded ML models | Guest local volume `immich-model-cache` | `/cache` |

Both media volumes use NFS 4.2, `hard`, and `fsc`. The existing `photos` UID/GID
1005 owns the writable directory and runs the server. Exports are restricted to
`immich.vm` and retain root squashing. Existing originals are not copied, moved,
or made writable. They must be readable by UID/GID 1005; adjust only the required
read/traverse permissions if necessary, not ownership recursively.

The dedicated `podman-immich` bridge exposes only port 2283. Its DNS traffic is
allowed through the guest firewall, and its network is created after nftables
loads. If reloading nftables manually, run `sudo podman network reload --all`
afterward to restore Podman's forwarding rules.

PostgreSQL must stay on the guest disk, never NFS. The NAS already snapshots the
`photos` and `apps` subvolumes, covering both media locations. The VM disk itself
is not part of that backup: database dumps are essential.

For a library over 1 TB, measure actual SSD and backup-disk capacity before a
full scan. Generated media typically adds 10–20% of source size, with additional
space needed for phone uploads, snapshots, and growth. Monitor both the NAS and
guest free space; Immich's storage indicator does not cover the guest database.

## First deployment

1. Check available NAS memory and storage alongside the other guests. Confirm
   x86-64-v2 CPU support for Immich v3; the libvirt template uses host passthrough.
   Confirm `br0` and the `infrastructure-vms` storage pool are active.
2. Reserve MAC `52:54:00:00:00:34` for `immich.vm`. Point `photos.vm` at the
   existing K3s/Caddy address, not the Immich guest. Resolve `nas.vm`, `immich.vm`,
   and `photos.vm` from the appropriate hosts and phones.
3. Build/publish the signed Immich role and updated NAS image using the existing
   build pipeline. Install the matching containers signature trust policy/key
   before booting the guest. As with the other guests, that trust material is
   provisioned outside this repository; do not disable verification to bypass it.
   The image build selector is `just online::stable immich both` (see the root
   README for publication credentials and signing); guest Ignition is generated
   by `vm-deploy`, so there is no separate Immich installer ISO.
4. Boot the updated NAS image, then verify the photos filesystem is mounted,
   `/var/lib/containers/immich/data` is owned by 1005:1005, and both new exports
   appear in `sudo exportfs -v`. Apply the Caddy configuration and network policy
   through the existing Flux workflow.
5. From the repository root on the NAS, provision and then boot:

   ```sh
   sudo vm-deploy immich
   sudo virsh start immich
   ```

   The first boot rebases to the role image and reboots. Image pulls and initial
   model downloads require internet access. Provisioning is create-only and
   refuses to overwrite an existing domain or disk. Inventory enables autostart.

6. Check the guest:

   ```sh
   ssh nick@immich.vm 'sudo systemctl status immich-{server,database,redis,machine-learning}.service'
   ssh nick@immich.vm 'findmnt -t nfs,nfs4 -o SOURCE,TARGET,OPTIONS'
   ssh nick@immich.vm 'sudo podman ps --format "{{.Names}} {{.Status}}"'
   ```

   NFS mounting must succeed before the server can run; a failed mount must not
   fall back to a guest-local directory. Services retry startup after failures.
   The database password is generated once at `/var/lib/immich/database.env`
   with mode 0600. Do not delete this file while retaining the database volume.

7. Open `https://photos.vm`, create your admin account, and set up the phone app.
   Use the existing Caddy CA trust instructions in the cluster README. Install
   and trust its root CA on each device, then test uploads, downloads, and video
   playback in the actual mobile app. Immich documents limitations with custom
   certificates; a browser succeeding alone is insufficient. Do not disable TLS
   checks as a workaround. If the phone cannot trust the private CA, resolve that
   before relying on automatic uploads (a real domain with DNS-validated trusted
   TLS can still remain LAN-only).
8. In Administration → External Libraries, create a library owned by your
   account. Initially add one representative subdirectory beneath `/mnt/photos`.
   Enable the normal nightly scan; network shares do not reliably support file
   watching. Confirm smart search, face detection/recognition, and daily database
   backups are enabled. Retain the standard 14 daily dumps under `/data/backups`.
9. Test the sample before changing the import path to all of `/mnt/photos`.
   Never add `/data` as an external library. Select phone albums for automatic
   uploads. Each additional family member should have a separate account;
   external libraries have one owner, with albums/partner sharing configured in
   the app as needed.

Name detected people in Explore. For search by image, upload the reference into
your library, let smart-search indexing finish, and use **Find similar photos**.
This searches visual similarity; person grouping is the separate face-recognition
feature. Search text, albums, maps, and duplicate review use the standard UI.

## Backups and recovery

Immich's daily database dumps land on NFS under `/data/backups`. They contain
metadata, not originals. The weekly NAS snapshot timer is crash-consistent and
does not automatically quiesce guests. For an application-consistent snapshot,
include this VM in the [shared backup order](../README.md#safety-and-backups):

1. Run `/usr/libexec/infrastructure/backup-prepare` as root in the guest.
   It stops Immich writers, dumps PostgreSQL, checks the archive with
   `pg_restore --list`, and atomically stores
   `/data/backups/infrastructure/immich.dump` as UID 1005.
2. Run the NAS Btrfs backup while all prepared guests remain quiesced. Avoid
   changing external originals during this snapshot window.
3. Always run `/usr/libexec/infrastructure/backup-finish` as root in every
   prepared guest, even if the NAS backup fails. The server restarts only if it
   was previously active. A failed prepare attempts recovery automatically.

When running the snapshot from a Bash session on the NAS, protect Immich's
finish step with a trap. Prepare/finish the other active guests as described in
the shared backup order as well:

```sh
(
  set -e
  trap 'ssh nick@immich.vm sudo /usr/libexec/infrastructure/backup-finish' EXIT
  ssh nick@immich.vm sudo /usr/libexec/infrastructure/backup-prepare
  sudo systemctl start --wait btrfs-backup.service
)
```

The prepare hook leaves a persistent start guard. If the VM reboots or the
orchestrator stops between prepare and finish, complete/abort the snapshot and
run `backup-finish`; startup remains blocked until then. A failed finish retains
the marker so it can be retried. The two hooks serialize operations with a lock.

Restore into a fresh isolated VM using the **same pinned release** and writable
copies of matching `apps` and `photos` snapshots. Preserve `/data` and
`/mnt/photos` paths. Block normal server startup before first role boot, start
only `immich-database.service` and its dependencies, and restore the custom dump
into the fresh `immich` database:

```sh
# Stream the selected NAS snapshot's dump to the fresh database container:
sudo podman exec -i immich-database pg_restore \
  --username=postgres --dbname=immich --clean --if-exists \
  --no-owner --no-acl --single-transaction --exit-on-error < immich.dump
```

Unblock the server only after the restore succeeds and the matching media mounts
are ready. The fresh VM's generated database password can differ from the old
one: the dump uses the existing `postgres` role and does not restore its password.
Restore daily `.sql.gz` dumps using the release's upstream restore workflow
instead; they are not custom-format archives. Preserve accounts, people, albums,
and original file paths. Do not run the restored and original instances as
writers against the same media export.

## Validation and updates

`just check-vm` exercises credential persistence, backup failures/recovery, and
create-only provisioning. `just check-online` checks Immich build selection and
inventory-driven guest rendering. After pulling the pinned service images,
`bash vms/immich/test/runtime` runs a disposable local stack and verifies a real
upload/download, persistence across restart, and restoration of its database.
It binds only a random loopback port and removes its own containers/volumes on
exit. It uses local stand-in media volumes; live NFS and phone tests remain
necessary. Validate generated Quadlets and strict
Ignition before publishing. Perform these host checks before indexing everything:

- Reboot the guest and verify accounts, uploads, database, and model cache persist.
- Start with NFS unavailable; confirm server failure rather than local writes.
  Restore NFS and verify recovery.
- Verify a representative phone photo/video upload, external original checksum,
  face grouping, text search, and reference-image similarity search.
- Prepare a backup, snapshot, finish, and restore into an isolated instance.
  Confirm the same accounts, albums, people metadata, and media are accessible.
- Check free space and job queues while indexing. Start intensive processing
  outside Minecraft's busy hours; reduce job concurrency if it affects gameplay.

Update server and ML pins together from the same upstream release; update
PostgreSQL/Valkey only according to that release's bundle/migration instructions.
Keep phone clients compatible with the server. Back up before upgrades: rolling
back the OS image does not undo database migrations. No container auto-update is
enabled; role-image updates carry reviewed pins.
