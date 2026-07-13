# NAS

## Host boundary

The physical NAS is deliberately a storage and virtualization host. It runs
Btrfs, NFSv4, backups, KVM/libvirt, NetworkManager, NUT, IPS, TuneD, SSH, and
native Cockpit. Application services run only in `k3s.vm`, `minecraft.vm`, or
`jellyfin.vm`.

The NAS image contains no application Quadlets and does not run Caddy,
Nextcloud, Paperless, Uptime Kuma, the registry, Minecraft, or Jellyfin. It also
does not provision FreeIPA, FreeRADIUS, or other domain-controller services.
Old `/var/lib/containers` data is retained only as a migration or rollback
source; it is not mounted or used by the steady-state host.

## Cockpit

Cockpit runs natively through `cockpit.socket`, not through Podman or Caddy.
Open `https://nas.vm:9090/`; the host firewall exposes TCP 9090 to the LAN.
SSH remains key-only, but Cockpit and the local console can use the unique local
password described below. The application names and HTTPS endpoints belong to
K3s Caddy, not the physical host.

The **Virtual Machines** page manages the system libvirt instance. The
**Podman containers** page manages rootless containers for the logged-in user;
switch Cockpit to administrative access to manage root-owned system containers.
Cockpit starts the appropriate local Podman API socket on demand, so no Podman
API is exposed on the network.

## Backups

`btrfs-backup.timer` runs weekly, with up to one hour of random delay. It
creates read-only snapshots of the SSD subvolumes and transfers them to
`/var/srv/hdd/backups/ssd` with `btrfs send/receive`. The newest matching
snapshot is used as the parent for an incremental transfer. Three weekly
snapshots are retained by default on both filesystems.

The steady-state set is `books`, `docs`, `git`, `music`, `photos`, `touhou`,
`videos`, and `vms`. The old `apps` and `caddy` subvolumes are deliberately
excluded after cutover. Caddy's CA and all application state now live on VM
state disks inside `vms`; that subvolume also contains libvirt definitions and
guest secrets, so access to the backup must remain restricted. `touhou` is
listed separately because a Btrfs snapshot does not recursively snapshot a
nested subvolume.

Application-consistent preparation is VM-only. The host exports the inventory
and libvirt XML, then calls each running managed guest's prepare hook through
QEMU Guest Agent. The K3s, Minecraft, and Jellyfin hooks prepare their own
databases and state and may leave writers quiesced. The host freezes and
suspends those guests only long enough to snapshot every source subvolume, then
resumes/thaws them and calls their idempotent finish hooks before the slower
send to HDD. The host does not inspect, pause, or back up local application
containers.

A missing or failing prepare, finish, resume, or thaw fails the job and triggers
cleanup retries rather than silently accepting an inconsistent copy. Guest
hooks run under `timeout(1)` with a one-hour default, receive TERM at the
deadline and KILL after another minute, and are polled for an additional grace
period. The host never invokes a guest finish hook while its prepare hook is
still terminating.

Run a backup immediately or inspect the schedule with:

```sh
sudo systemctl start btrfs-backup.service
systemctl list-timers btrfs-backup.timer
sudo journalctl -u btrfs-backup.service
```

The service accepts environment overrides named `BTRFS_BACKUP_SOURCE_ROOT`,
`BTRFS_BACKUP_SNAPSHOT_ROOT`, `BTRFS_BACKUP_DESTINATION_ROOT`,
`BTRFS_BACKUP_SUBVOLUMES`, `BTRFS_BACKUP_RETENTION`, and
`BTRFS_BACKUP_VM_DOMAINS`. Set them with a systemd drop-in only when
intentionally changing the storage or guest set.

## Final legacy application archive

Create one final archive while still booted into the old application-bearing
NAS deployment. First produce the application exports described in the
[`cluster`](../cluster/README.md), [`minecraft`](../minecraft/README.md), and
[`jellyfin`](../jellyfin/README.md) migration runbooks. Put Nextcloud into
maintenance mode, stop and mask every old writer, and run the old deployment's
weekly backup one last time:

```sh
sudo ./vms/bin/legacy-apps mask
./vms/bin/legacy-apps status
sudo systemctl start btrfs-backup.service
sudo journalctl -u btrfs-backup.service -b
sudo find /var/srv/hdd/backups/ssd/apps \
  /var/srv/hdd/backups/ssd/caddy -mindepth 1 -maxdepth 1 -type d -print
```

Record the common final timestamp and retain both received read-only snapshots.
The minimal image's normal backup set does not revisit or prune `apps` or
`caddy`, so this is a deliberate rollback archive rather than a continuing
backup stream. Do not delete the previous rpm-ostree deployment or these two
snapshot trees until migration acceptance is complete.

Useful legacy restore sources are:

- `/var/srv/hdd/backups/ssd/apps/<timestamp>/nextcloud`
- `/var/srv/hdd/backups/ssd/apps/<timestamp>/paperless`
- `/var/srv/hdd/backups/ssd/apps/<timestamp>/uptime-kuma`
- `/var/srv/hdd/backups/ssd/apps/<timestamp>/registry`
- `/var/srv/hdd/backups/ssd/apps/<timestamp>/jellyfin`
- `/var/srv/hdd/backups/ssd/apps/<timestamp>/minecraft/backups/current`
- `/var/srv/hdd/backups/ssd/caddy/<timestamp>/data`

For legacy Minecraft, restore `java/world*` and `bedrock/worlds` from the
canonical `backups/current` export while both servers are stopped. Other live
world paths in the old snapshot are not the canonical application-consistent
copy.

## Virtual-machine host

The NAS uses TuneD's `virtual-host` profile and prepares a libvirt directory
pool named `infrastructure-vms` at `/var/srv/ssd/vms`. That path is a dedicated
Btrfs subvolume with NOCOW set before any qcow2 or raw disk is created. Systemd
socket drop-ins restrict libvirt management to the `libvirt` group; sysusers
keeps the existing `nick` account in `libvirt`, while wheel polkit authorization
remains in place. Reconnect after deployment to refresh groups.

SSH is key-only. New NAS provisions lock the old reusable account password.
On an existing installation, run `passwd` once as `nick` to replace the old
local password with a unique one before using password-based console or Cockpit
login; the early SSH drop-in keeps that password unusable over SSH.

The LAN bridge is intentionally not created automatically during an image
deployment. Run `nas-vm-bridge status` and then `sudo nas-vm-bridge apply` in a
maintenance session after creating the UniFi reservations. The helper accepts
only one wired DHCP default route and uses a timed NetworkManager checkpoint
with gateway, DNS, registry, and SSH health checks.

The committed inventory, provisioning helper, stable MAC addresses, and full
cutover runbook live in [`../vms/README.md`](../vms/README.md).

## Host image updates and rollback

### Hold the legacy deployment before publication

Before merging the change that removes the application Quadlets, or before any
equivalent build publishes the host-only `nas:latest`, put the running legacy
NAS on an explicit update hold. Otherwise its daily timer can stage the minimal
image and the nightly power cycle can activate it before migration is ready:

```sh
sudo systemctl mask --now rpm-ostree-upgrade.timer
TAG=git-0123456789ab-img-abcdef012345 # current legacy NAS deployment
printf '%s\n' "ghcr.io/noobping/nas:${TAG}" \
  | sudo tee /etc/bootc-image-ref
rpm-ostree status
```

If `rpm-ostree status` already shows an unintended pending minimal deployment,
remove only that pending deployment and inspect the status again:

```sh
sudo rpm-ostree cleanup --pending
rpm-ostree status
```

Keep the timer masked through the final legacy archive, VM restore rehearsal,
and maintenance window. Stage the new signed image manually only after those
gates pass. Do not return the host to `latest` until cutover is accepted.

### Verified steady-state updates

The daily update service reads `/etc/bootc-image-ref`, accepts only a keyless
signature from this repository's `nas.yml` workflow on `refs/heads/main`, and
stages the exact verified manifest digest. The nightly power cycle activates a
staged deployment after `libvirt-guests.service` has shut down the guests.

The NAS image ships the verifier, pinned Cosign binary, and a vendor systemd
drop-in under immutable `/usr`, so an existing NAS adopts verified updates
through its next normal image deployment without rerunning Ignition. A tmpfiles
rule seeds only a missing tracked reference and preserves an administrator's
immutable pin.

An existing NAS must bootstrap that migration once: before this new image has
booted, its embedded verifier does not exist yet. On a trusted admin workstation,
verify a reviewed immutable NAS tag, require one digest, and rebase the old host
to that exact digest:

```sh
REPOSITORY=ghcr.io/noobping/nas
TAG=git-0123456789ab-img-abcdef012345
DIGEST="$(cosign verify --output=json \
  --certificate-identity=https://github.com/noobping/infrastructure/.github/workflows/nas.yml@refs/heads/main \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com \
  "${REPOSITORY}:${TAG}" \
  | jq -er '[.[].critical.image["docker-manifest-digest"]
      | select(test("^sha256:[0-9a-f]{64}$"))]
    | unique | if length == 1 then .[0] else error("expected one digest") end')"
ssh -t nick@nas.vm sudo rpm-ostree rebase \
  "ostree-image-signed:docker://${REPOSITORY}@${DIGEST}"
ssh -t nick@nas.vm sudo systemctl reboot
```

The signed transport also evaluates `/etc/containers/policy.json`. Fedora
CoreOS currently ships a permissive default policy, so authentication during
this bootstrap still comes from Cosign verifying that exact digest immediately
beforehand. All later transitions use the embedded verifier and pass its exact
verified digest to `ostree-image-signed`.

Stage the current signed `latest` channel manually and inspect both deployments:

```sh
sudo systemctl start rpm-ostree-upgrade.service
rpm-ostree status
```

For an immediate rollback to the previous local deployment, prevent the update
timer from staging the rejected channel again, select the previous deployment,
and reboot:

```sh
sudo systemctl mask --now rpm-ostree-upgrade.timer
sudo rpm-ostree rollback
sudo systemctl reboot
```

To stage a reviewed immutable rollback image instead, copy its complete tag from
the successful NAS workflow output. The verifier still checks the workflow
identity before rebasing:

```sh
TAG=git-0123456789ab-img-abcdef012345
printf '%s\n' "ghcr.io/noobping/nas:${TAG}" \
  | sudo tee /etc/bootc-image-ref
sudo systemctl start rpm-ostree-upgrade.service
rpm-ostree status
sudo systemctl reboot
```

After validating a repaired mutable channel, resume automatic updates:

```sh
printf '%s\n' 'ghcr.io/noobping/nas:latest' \
  | sudo tee /etc/bootc-image-ref
sudo systemctl unmask --now rpm-ostree-upgrade.timer
sudo systemctl start rpm-ostree-upgrade.service
```

## NFSv4 VM exports

Only NFSv4 over TCP 2049 is enabled. A boot-time helper derives the client names
from `/etc/exports.d/vm-data.exports`, resolves them through UniFi DNS, and
builds a narrow nftables rule. It fails closed if a reservation is missing.
The exports keep root squashing enabled; music and books are read-only, while
the K3s document paths are writable. `crossmnt` exposes the nested Touhou Btrfs
mount read-only with the music export.

## Application services

The physical NAS has no application runtime. Operate web applications through
[`cluster/`](../cluster/README.md), Minecraft through
[`minecraft/`](../minecraft/README.md), and Jellyfin through
[`jellyfin/`](../jellyfin/README.md).

`nas.vm` names only the physical host and native Cockpit is available at
`https://nas.vm:9090/`. Application DNS, TLS, administration, migration, and
restore procedures belong to the role runbooks above.
