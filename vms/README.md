# NAS virtual machines

This directory is the host-side contract for the three KVM guests. The physical
NAS remains responsible for Btrfs, NFSv4, libvirt, the LAN bridge, NUT, IPS,
weekly backups, and native Cockpit at `https://nas.vm:9090/`. The new NAS image
contains no application Quadlets: K3s, Minecraft, and Jellyfin state and writers
live only in their respective VMs. Legacy Quadlets exist only in the previous
rpm-ostree deployment retained for rollback.

## Inventory

`inventory.json` is authoritative for VM resources, role image references,
stable MAC addresses, state-disk serials, and NFS mounts.

| Domain | UniFi name | MAC | vCPU | RAM | Root | Minimum state |
|---|---|---|---:|---:|---:|---:|
| `k3s` | `k3s.vm` | `52:54:00:00:00:31` | 12 | 24 GiB | 40 GiB | 250 GiB |
| `minecraft` | `minecraft.vm` | `52:54:00:00:00:32` | 8 | 12 GiB | 40 GiB | 100 GiB |
| `jellyfin` | `jellyfin.vm` | `52:54:00:00:00:33` | 4 | 8 GiB | 40 GiB | 50 GiB |

The provisioner measures each role's existing source directories and creates a
sparse raw state disk sized to 150% of current usage or the stated minimum,
whichever is larger. Update the committed minimum before provisioning if you
want more guaranteed headroom.

## UniFi prerequisites

Create DHCP reservations for all three MACs before starting guests. Preserve the
physical NIC's current NAS reservation; the bridge clones that MAC so the NAS
keeps its address.

The `.vm` suffix is intentionally used as a private UniFi DNS suffix even
though it is not a standards-reserved home-network domain.

Create these local records:

| Record | Reserved address |
|---|---|
| `nas.vm` | Physical NAS |
| `k3s.vm`, `apps.vm`, `nextcloud.vm`, `office.vm`, `paperless.vm`, `status.vm`, `registry.vm`, `music.vm` | K3s VM |
| `minecraft.vm` | Minecraft VM |
| `jellyfin.vm` | Jellyfin VM |

The NFS service resolves `k3s.vm` and `jellyfin.vm` when it builds its
firewall rule. It intentionally fails closed until both reservations resolve.
Exports retain root squashing; music and books are read-only.

## Prepare the host bridge

Deploy and reboot into the NAS image first. Verify storage and tuning:

```sh
systemctl status vm-storage-prepare.service tuned.service \
  libvirtd.service libvirt-guests.service
systemctl is-enabled \
  libvirtd.socket libvirtd-ro.socket libvirtd-admin.socket
systemctl is-enabled virtlockd.service virtlogd.service
systemctl is-enabled virtqemud.service virtqemud.socket | grep -Fx disabled
grep -E '^(ON_SHUTDOWN|PARALLEL_SHUTDOWN)=' \
  /etc/sysconfig/libvirt-guests
tuned-adm active
sudo virt-host-validate
sudo virsh net-info default
if ip link show virbr0; then exit 1; fi
```

`libvirt-guests.service` shuts all three guests down in parallel (up to five
minutes) instead of managed-saving them, so staged guest deployments activate
at the nightly host power cycle. Reconnect your login session after the first
deployment so the new `libvirt` group membership is active. Its unit drop-in
orders it after the NFS server and VM storage preparation; systemd reverses that
order at shutdown, so guests finish stopping before exports or disks become
unavailable.

Inspect, then apply the bridge from a stable SSH or local-console session:

```sh
nas-vm-bridge status
sudo nas-vm-bridge apply
```

The helper refuses static addressing, Wi-Fi, and ambiguous default routes. It
uses a NetworkManager checkpoint covering all devices, performs gateway, DNS,
GHCR, and SSH checks, then asks for confirmation. Bridge/port autoconnect is
made persistent only after the confirmed checkpoint returns and health passes
again. If SSH disappears or confirmation times out, NetworkManager restores the
previous profile.

Afterwards confirm the NAS retained its reservation:

```sh
ip -4 route
nmcli connection show --active
nas-vm-bridge status
```

## Render role Ignition

Use the canonical role Butane fragments; do not hand-edit generated Ignition:

```sh
mkdir -p dist/ign
for role in k3s minecraft jellyfin; do
  yq ea '. as $item ireduce ({}; . *+ $item)' \
    butane/base.yml butane/vm.yml "butane/$role.yml" > "butane/$role.bu"
  sed -e "s#__CI_IMAGE_NAMESPACE__#ghcr.io/noobping#g" \
    -e "s#__CI_BOOTC_IMAGE__#$role#g" \
    "butane/$role.bu" > "butane/$role.rendered.bu"
  podman run --rm -v "$PWD:/work:Z" -w /work \
    quay.io/coreos/butane:release --pretty --strict --files-dir . \
    "butane/$role.rendered.bu" > "dist/ign/$role.ign"
done
```

The Butane workflow also publishes these three files in its `vm-ignition`
artifact. The provisioner validates the inventory image against the role's
`ghcr.io/noobping` path, writes it to `/etc/bootc-image-ref`, and adds the
inventory's NFS automounts. The shared first-boot service performs the verified
rebase; role Ignition owns the remaining guest state.

## Provision

The provisioner downloads and verifies the signed stable FCOS QEMU qcow2 with
`coreos-installer`, creates qcow2 root overlays and NOCOW sparse raw state
disks under `/var/srv/ssd/vms`, always validates the augmented Ignition,
validates XML when its validator is installed, defines each domain, and enables
libvirt autostart. It never replaces an existing domain or disk.

```sh
sudo ./vms/bin/provision --all
sudo virsh domiflist k3s
sudo virsh domblklist k3s --details
sudo virsh start k3s
sudo virsh start minecraft
sudo virsh start jellyfin
```

Use `--start` with provisioning only after UniFi reservations, NFS, and the
role images are ready. Every domain interface source must be `br0`; there is
no libvirt NAT dependency.

Verify first boot and the image rebase:

```sh
sudo virsh console k3s
sudo virsh qemu-agent-command k3s '{"execute":"guest-ping"}'
ssh nick@k3s.vm rpm-ostree status
ssh nick@k3s.vm findmnt /var/lib/rancher/k3s
ssh nick@jellyfin.vm findmnt /var/srv/music /var/srv/books
ssh nick@jellyfin.vm findmnt -T /var/srv/music/touhou
ssh nick@jellyfin.vm test -r /var/srv/music/touhou
for domain in k3s minecraft jellyfin; do
  ssh "nick@${domain}.vm" getsebool virt_qemu_ga_read_nonsecurity_files \
    | grep -q -- '--> on$'
  sudo virsh domfsfreeze "$domain"
  sudo virsh domfsthaw "$domain"
done
```

Do not enable the weekly backup until the boolean check and a real freeze/thaw
cycle succeed for every guest.

## Guest image updates

Each guest's daily `rpm-ostree-upgrade.timer` reads its role's channel from
`/etc/bootc-image-ref`. The service accepts only a keyless signature issued to
this repository's `vms.yml` workflow on `refs/heads/main`, extracts the one
verified manifest digest, and stages that immutable digest. VM images are not
published from another branch. The graceful host shutdown described above lets
the normal nightly NAS power cycle activate the staged deployment.

```sh
# Run inside the guest: stage latest and activate it at the next reboot.
sudo systemctl start rpm-ostree-upgrade.service
rpm-ostree status
sudo systemctl reboot

# Return to the previous deployment once.
sudo rpm-ostree rollback
rpm-ostree status
sudo systemctl reboot
```

For a persistent rollback, replace the example value with an immutable tag from
the image workflow:

```sh
TAG=git-0123456789ab-img-abcdef012345
printf '%s\n' "ghcr.io/noobping/k3s:${TAG}" | sudo tee /etc/bootc-image-ref
sudo systemctl start rpm-ostree-upgrade.service
rpm-ostree status
sudo systemctl reboot
```

Use the `minecraft` or `jellyfin` repository path instead when operating
that role. The same identity verification is required for immutable tags. The
tracked immutable tag prevents the daily timer from replacing the rollback.
Return to the reviewed automatic channel explicitly:

```sh
printf '%s\n' 'ghcr.io/noobping/k3s:latest' | sudo tee /etc/bootc-image-ref
sudo systemctl start rpm-ostree-upgrade.service
rpm-ostree status
```

## Backups

The weekly host job invokes `/usr/libexec/infrastructure/backup-prepare` in each
running guest through QEMU Guest Agent. A guest hook prepares that VM's
application-consistent exports and may leave its writers quiesced. The host has
no local application containers to prepare or pause; it freezes and suspends the
guests while creating the source snapshots.

After all snapshots exist, the host resumes/thaws workloads and invokes the
idempotent `/usr/libexec/infrastructure/backup-finish` hook in every prepared
guest before performing the slower HDD sends. The `vms` subvolume and generated
libvirt XML are included with retention three. The steady-state host set is
`books docs git music photos touhou videos vms`; legacy `apps` and `caddy` are
excluded and retained only in the final pre-cutover archive.

All role images must provide both hooks before the first post-cutover backup.
A missing/failing prepare, finish, resume, or thaw fails the backup. The host
EXIT trap retries resume/thaw and finish after partial failures. Do not disable
the guest hooks after applications begin accepting writes in the VMs.

Run and inspect a rehearsal before cutover:

```sh
sudo systemctl start btrfs-backup.service
sudo journalctl -u btrfs-backup.service -b
sudo btrfs subvolume list /var/srv/hdd/backups/ssd
```

## Cutover safety

### Hold the legacy host image first

Before merging or otherwise publishing the NAS change that removes application
Quadlets, pin the current application-bearing immutable tag and mask the live
NAS update timer. A newly published host-only `nas:latest` must not be staged by
the daily timer or activated by the nightly reboot before migration is ready:

```sh
sudo systemctl mask --now rpm-ostree-upgrade.timer
TAG=git-0123456789ab-img-abcdef012345 # current legacy NAS deployment
printf '%s\n' "ghcr.io/noobping/nas:${TAG}" | sudo tee /etc/bootc-image-ref
rpm-ostree status
```

Keep this hold until the final archive and restore rehearsal have succeeded.
If an unintended pending deployment already exists, follow the cleanup check in
[the NAS update runbook](../nas/README.md#hold-the-legacy-deployment-before-publication).

### Final migration and archive

Do not run old and migrated copies of a writable application against the same
data. Rehearse with copied data first. At cutover, enable Nextcloud maintenance
mode, create the database/application exports in the role runbooks, then stop
and mask every legacy writer while still booted into the old NAS deployment:

```sh
sudo ./vms/bin/legacy-apps mask
./vms/bin/legacy-apps status
```

Every listed unit must be inactive and masked. Masking is required because a
plain stop lets the old Quadlet generator recreate services on reboot. The
helper does not include Cockpit; the new image provides native Cockpit on port
9090 and contains none of these application Quadlets.

Before the final copy, grant UID 33 access to existing shared documents and add
inheritable ACLs to every existing directory:

```sh
sudo setfacl -R -m 'u:33:rwX,m::rwX' /var/srv/docs/shared
sudo find /var/srv/docs/shared -type d -exec \
  setfacl -m 'd:u::rwx,d:u:33:rwx,d:g::rwx,d:m::rwx,d:o::---' {} +
```

Run the old deployment backup one final time after its writers stop. Record and
retain the common received `apps/<timestamp>` and `caddy/<timestamp>` snapshot
trees as the legacy rollback archive. The new steady-state backup excludes both
subvolumes. See [the archive procedure](../nas/README.md#final-legacy-application-archive).

Only then perform the final state sync, manually stage the signed minimal NAS
deployment, reboot, and start the VMs and Flux workloads. Prove Nextcloud can
write the root-squashed NFS export as `www-data` (UID 33):

```sh
kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- \
  su -s /bin/sh -c \
  'test "$(id -u)" = 33 &&
   touch /var/srv/docs/shared/.nextcloud-acl-test &&
   rm /var/srv/docs/shared/.nextcloud-acl-test' www-data
```

Change service DNS only after all application checks succeed. Keep the host
update timer masked until the cutover is accepted.

### Rollback after cutover

Rollback is an ordered outage, not just a host image switch:

1. Stop all new writers first. Suspend Flux, put applications in maintenance
   mode, flush/export any post-cutover state, and cleanly stop the K3s,
   Minecraft, and Jellyfin guests. Follow each role runbook; never leave a VM
   writer active while starting its legacy counterpart.
2. Restore UniFi service DNS to the physical NAS. Restore or reconcile the
   captured post-cutover changes into writable clones of the final legacy
   `apps` and `caddy` data. Never write into the received read-only snapshots.
3. On the NAS, keep updates masked, verify that the previous deployment is the
   application-bearing legacy image, select it, and reboot:

   ```sh
   sudo systemctl mask --now rpm-ostree-upgrade.timer
   rpm-ostree status
   sudo rpm-ostree rollback
   sudo systemctl reboot
   ```

4. After the reboot, confirm the legacy Quadlet files are present and only then
   remove their persistent masks and start them:

   ```sh
   test -f /etc/containers/systemd/nextcloud.container
   sudo ./vms/bin/legacy-apps restore
   ./vms/bin/legacy-apps status
   ```

The restore helper intentionally refuses to run in the minimal image. Keep the
legacy deployment, final archive, and original NetworkManager uplink profile
until the migration and rollback drill are accepted.
