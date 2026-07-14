# NAS virtual machines

The physical NAS keeps its existing libvirt services and host services. It owns
the Btrfs filesystems, NFSv4 server, LAN bridge, backups, and Cockpit at
`https://nas.vm/`. Nothing here masks or replaces the NAS libvirt setup.

Each guest has one qcow2 root disk. Application data is not stored on a second
libvirt disk:

- every Kubernetes PVC is a static NFS volume;
- Minecraft and Jellyfin use Quadlet named NFS volumes, not host-path binds;
- K3s keeps its runtime, containerd state, and SQLite control-plane database on
  the local VM root, while its backup artifacts are on NFS;
- `cachefilesd` and the `fsc` mount option provide a persistent read cache in
  every VM.

## Inventory and DNS

`inventory.json` contains the VM resources, root-disk size, stable MAC address,
and canonical Ignition file.

| Domain | UniFi name | MAC | vCPU | RAM | Root |
|---|---|---|---:|---:|---:|
| `k3s` | `k3s.vm` | `52:54:00:00:00:31` | 12 | 24 GiB | 40 GiB |
| `minecraft` | `minecraft.vm` | `52:54:00:00:00:32` | 8 | 12 GiB | 40 GiB |
| `jellyfin` | `jellyfin.vm` | `52:54:00:00:00:33` | 4 | 8 GiB | 40 GiB |

Create DHCP reservations for those MACs. The NAS and all guests must resolve
these local names before NFS-backed workloads start:

| Record | Reserved address |
|---|---|
| `nas.vm` | Physical NAS |
| `k3s.vm`, `apps.vm`, `nextcloud.vm`, `office.vm`, `paperless.vm`, `status.vm`, `registry.vm`, `music.vm` | K3s VM |
| `minecraft.vm` | Minecraft VM |
| `jellyfin.vm` | Jellyfin VM |

The exports in `nas/nfs/exports` grant access only to the matching VM names.
K3s gets root access only to its isolated application and backup exports.
Shared documents and the VM-role exports remain root-squashed; music and books
are read-only. For NFS, the firewall adds only TCP port 2049.

## Existing libvirt storage and bridge

The provisioner deliberately does not rewrite libvirt configuration. Its
`storage_pool.name` must name an existing active pool, and `storage_pool.path`
must be that pool's Btrfs subvolume. Create the subvolume once if needed, then
verify the existing pool target is `/var/srv/ssd/vms`:

```sh
sudo btrfs subvolume create /var/srv/ssd/vms
sudo virsh pool-info infrastructure-vms
sudo virsh pool-dumpxml infrastructure-vms
```

The provisioner creates the `base`, `config`, `disks`, and `ignition`
directories inside that subvolume. It only refreshes the named pool; it never
defines or rewrites it.

Inspect and apply the existing bridge helper from a stable SSH or local-console
session:

```sh
/usr/libexec/infrastructure/nas-vm-bridge status
sudo /usr/libexec/infrastructure/nas-vm-bridge apply
ip -4 route
nmcli connection show --active
sudo virt-host-validate
```

Every guest interface uses the existing `br0`; there is no libvirt NAT
dependency.

## Render role Ignition

Use the canonical Butane fragments; do not edit generated Ignition:

```sh
mkdir -p dist/ign
for role in k3s minecraft jellyfin; do
  yq ea '. as $item ireduce ({}; . *+ $item)' \
    butane/base.yml butane/updates.yml butane/vm.yml \
    "butane/$role.yml" > "butane/$role.bu"
  sed -e "s#__CI_IMAGE_NAMESPACE__#ghcr.io/noobping#g" \
    -e "s#__CI_BOOTC_IMAGE__#$role#g" \
    "butane/$role.bu" > "butane/$role.rendered.bu"
  podman run --rm -v "$PWD:/work:Z" -w /work \
    quay.io/coreos/butane:release --pretty --strict --files-dir . \
    "butane/$role.rendered.bu" > "dist/ign/$role.ign"
done
```

The Butane workflow publishes the same three files in its `vm-ignition`
artifact. On first boot, each guest directly rebases to its role's
`ghcr.io/noobping/<role>:latest` image and reboots once.

## Provision and verify

The provisioner downloads the stable FCOS QEMU image, creates one qcow2 overlay
per VM, validates Ignition and the domain XML, defines the domain, and applies
the inventory's autostart setting. It never replaces an existing domain or
disk. K3s and Minecraft autostart; Jellyfin deliberately does not while the NAS
Jellyfin service is retained.

```sh
sudo ./vms/bin/provision --all
sudo virsh domblklist k3s --details
sudo virsh domblklist minecraft --details
sudo virsh domblklist jellyfin --details
sudo virsh autostart --disable jellyfin
```

The last command also corrects a Jellyfin domain defined before this inventory
change. Each disk list should contain only one guest disk. Use `--start` only
after DNS, the NFS server, and the role images are ready. If a retained NAS
service and its VM replacement use the same data, stop the old writer before
starting the guest; never run both copies against one export.

If K3s or Minecraft is provisioned before the current NAS deployment is
running, immediately disable that domain's autostart. Re-enable it only after
NFS is available and the corresponding legacy host writer is absent.

This series leaves the existing libvirt shutdown policy untouched. Before
depending on the NAS's nightly poweroff, verify that the host's existing setup
shuts running guests cleanly before NFS and the backing filesystems stop.

After first boot:

```sh
for host in k3s.vm minecraft.vm jellyfin.vm; do
  ssh "nick@$host" 'systemctl is-active cachefilesd.service && getsebool virt_use_nfs'
done

ssh nick@minecraft.vm \
  'sudo podman volume inspect systemd-minecraft-java systemd-minecraft-bedrock'
ssh nick@jellyfin.vm \
  'sudo podman volume inspect systemd-jellyfin-config systemd-jellyfin-cache systemd-jellyfin-music systemd-jellyfin-books'
ssh nick@k3s.vm 'sudo k3s kubectl get pv,pvc -A'
```

Check `/proc/mounts` in each guest for `vers=4.2`, `hard`, and `fsc`. On K3s,
all 17 PVs must be bound and no `local-path` claim should remain.

## Updates

The first-boot rebase tracks the role's `:latest` tag. The standard daily
`rpm-ostree upgrade` timer follows that same channel; there is no custom update
helper, digest file, or immutable-tag workflow.

```sh
sudo systemctl start rpm-ostree-upgrade.service
rpm-ostree status
```

To hold a rollback without masking services, disable the normal update units,
then re-enable them after review:

```sh
sudo systemctl disable --now rpm-ostree-upgrade.timer rpm-ostree-upgrade.service
sudo rpm-ostree rollback
sudo systemctl reboot

sudo systemctl enable --now rpm-ostree-upgrade.timer rpm-ostree-upgrade.service
```

## Cutover and backups

Minecraft and Jellyfin point at the existing NAS directories, so they need no
second data copy. Jellyfin is intentionally a manual trial while its NAS
Quadlet remains enabled: stop the host service, start the non-autostarted guest,
and verify the named volumes. Before any NAS shutdown or reboot, cleanly shut
down the trial guest, confirm `virsh domstate jellyfin` reports `shut off`, and
confirm `virsh dominfo jellyfin` reports `Managed save: no`. Remove stale
managed-save state before rebooting if necessary; disabling domain autostart
does not override the existing libvirt save/resume policy. The retained host
service can then return at boot. Do not enable Jellyfin guest autostart while
that host Quadlet remains enabled. Rollback is the same operation in reverse:
stop the guest before starting the retained host service. `music.vm` continues
to proxy to the retained NAS service; use `jellyfin.vm` directly during a VM
trial.

Minecraft autostarts on the current NAS deployment. Before booting a retained
legacy deployment whose Minecraft services use the same worlds, shut down the
guest and disable its domain autostart. Stop the legacy writers before returning
to the current deployment, then re-enable the guest's intended autostart.

The NAS backup snapshots the `apps`, `caddy`, `docs`, `music`, and `books`
subvolumes that contain the NFS exports. Each subvolume snapshot is
crash-consistent, but the sequence is not one atomic snapshot across all five.
The K3s hooks place logical dumps and recovery material on the NFS-backed
`k3s-backups` path inside `apps`. Use those hooks for an explicitly coordinated
backup; the normal NAS timer does not invoke guest hooks automatically.
