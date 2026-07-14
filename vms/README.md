# NAS virtual machines

The provisioner keeps the NAS's existing libvirt services, bridge, storage
pool, NFS server, and host services. It does not mask or replace them.

Each guest has one qcow2 root disk. Application persistence is on NFS:

- every Kubernetes claim is a static NFS volume;
- Minecraft and Jellyfin use Quadlet NFS volumes, not host-path binds;
- K3s runtime, containerd state, and SQLite stay on the VM root disk;
- every guest uses `cachefilesd` and the NFS `fsc` option.

`inventory.json` is authoritative for resources, MAC addresses, autostart, and
Ignition paths.

## Prerequisites

- Reserve the inventory MAC addresses and make `nas.vm`, `k3s.vm`,
  `minecraft.vm`, and `jellyfin.vm` resolvable before starting NFS workloads.
- The existing `infrastructure-vms` pool must be active at
  `/var/srv/ssd/vms`.
- The existing `br0` bridge must be ready.
- Render `dist/ign/{k3s,minecraft,jellyfin}.ign` using the
  [Butane instructions](../butane/README.md) or the workflow artifact.

```sh
sudo virsh pool-info infrastructure-vms
sudo virsh pool-dumpxml infrastructure-vms
/usr/libexec/infrastructure/nas-vm-bridge status
```

## Provision

```sh
sudo ./vms/bin/provision --all
for vm in k3s minecraft jellyfin; do
  sudo virsh domblklist "$vm" --details
done
sudo virsh autostart --disable jellyfin
```

Each domain must show one guest disk. Start K3s and Minecraft only after NFS is
available and any legacy writer using the same paths is stopped. Jellyfin stays
non-autostarted while the NAS Jellyfin service is retained.

```sh
sudo virsh start k3s
sudo virsh start minecraft
```

Verify cached NFS mounts after first boot:

```sh
for host in k3s.vm minecraft.vm; do
  ssh "nick@$host" \
    'systemctl is-active cachefilesd.service && findmnt -t nfs,nfs4 -o SOURCE,TARGET,OPTIONS'
done
ssh nick@k3s.vm 'sudo k3s kubectl get pv,pvc -A'
```

Mounts must include NFS 4.2, `hard`, and `fsc`; all 17 cluster claims must be
`Bound`, with no local-path claims.

## Updates

Guest Ignition uses `ostree-image-signed` and tracks each role's `:latest`
image. Before first boot, install a matching containers policy/public key and
publish signed role manifests; that trust material is not currently in this
repository. The normal daily `rpm-ostree` timer follows the same channel.

```sh
sudo systemctl start rpm-ostree-upgrade.service
rpm-ostree status
```

To hold a rollback, disable the update units before rebooting and re-enable
them only when returning to the latest channel:

```sh
sudo systemctl disable --now rpm-ostree-upgrade.timer rpm-ostree-upgrade.service
sudo rpm-ostree rollback
sudo systemctl reboot

# After returning to the latest channel:
sudo systemctl enable --now rpm-ostree-upgrade.timer rpm-ostree-upgrade.service
```

## Safety and backups

Never run a guest and a legacy NAS service against the same writable export.
Before booting a legacy deployment, shut down affected guests, clear any
managed-save state, and disable their autostart. Follow the role runbooks for
Jellyfin and Minecraft.

The existing libvirt shutdown policy is unchanged. Verify it stops guests
before NFS and the backing filesystems disappear during NAS shutdown.

For an application-consistent snapshot:

1. Run `sudo /usr/libexec/infrastructure/backup-prepare` on every active guest.
2. Run `sudo systemctl start --wait btrfs-backup.service` once on the NAS.
3. Run `sudo /usr/libexec/infrastructure/backup-finish` on every prepared guest,
   even when the NAS backup fails.

The [K3s](k3s/README.md), [Minecraft](minecraft/README.md), and
[Jellyfin](jellyfin/README.md) notes describe role-specific behavior.
