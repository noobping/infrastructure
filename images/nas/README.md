# NAS

Cockpit is at `https://nas.vm/` on port 443. The existing libvirt configuration
and services are unchanged.

## NFS

The NAS serves NFSv4 only on TCP 2049. `nfs/exports` limits every export to its
matching VM and uses synchronous writes. K3s application paths use
`no_root_squash`; shared-document and standalone-VM paths remain root-squashed,
and Jellyfin media is read-only. Build artifacts at
`nas.vm:/var/srv/ssd/artifacts` are publicly readable. Clients use hard NFS 4.2
mounts with `fsc`.

```sh
systemctl is-active nfs-server.service
sudo exportfs -v
ssh nick@k3s.vm 'findmnt -t nfs,nfs4 && systemctl is-active cachefilesd.service'
```

## CI

`ci-update.service` installs the latest verified x64 or arm64 binary at
`/var/srv/ssd/artifacts/ci`. `/usr/bin/ci` links to it, and the daily timer
replaces that target atomically. Link a repository to the same executable with:

```sh
ci install -m link
```

## Backups

`btrfs-backup.timer` runs weekly and retains three snapshots by default under
`/var/srv/hdd/backups/ssd`.

```sh
systemctl list-timers btrfs-backup.timer
sudo systemctl start --wait btrfs-backup.service
sudo journalctl -u btrfs-backup.service
```

The timer is crash-consistent: it does not quiesce guests or snapshot all
subvolumes atomically. Use the [VM backup order](../../vms/README.md#safety-and-backups)
when logical database dumps are required. The Caddy backup contains the local
CA private key; keep backups restricted.
