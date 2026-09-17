# NAS

Cockpit is at `https://nas.vm/` on port 443. The existing libvirt configuration
and services are unchanged.

## Host policy

The restricted `infrastructure-policy.service` Quadlet renders NUT files from
`/etc/ups/nut.env`, then asks the native NUT units to restart. Its policy rootfs
is embedded in the NAS image, so it works offline and rolls back with bootc.

```sh
sudo systemctl start infrastructure-policy.service
sudo journalctl -u infrastructure-policy.service -b
```

Btrfs subvolume preparation, NFS mounts, backups, and operational containers
remain native host units; the policy container is not privileged to perform
those operations.

## NFS

The NAS serves NFSv4 and NFSv3 for Nautilus. `nfs/exports` limits every export
to its matching VM and uses synchronous writes. K3s application paths use
`no_root_squash`; shared-document and standalone-VM paths remain root-squashed,
and Jellyfin media is read-only. Build artifacts at
`nas.vm:/var/srv/ssd/artifacts` are publicly readable. VM clients use hard NFS
4.2 mounts with `fsc`.

```sh
systemctl is-active nfs-server.service
sudo exportfs -v
ssh nick@k3s.vm 'findmnt -t nfs,nfs4 && systemctl is-active cachefilesd.service'
```

## Pipeline

Interactive shells expose `pipeline` through
`ghcr.io/noobping/pipeline:continuous`. The launcher temporarily extracts
Pipeline and its bundled Just binary, then runs them on the host so build
recipes can use host Podman and Buildah. Nothing is permanently installed. It
uses a cached image by default; set `PIPELINE_PULL=newer` to update or
`PIPELINE_PULL=never` to require a cached image.

Install self-contained hooks in a normal or bare repository with:

```sh
common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
install -d "$common_dir/pipeline"
cat > "$common_dir/pipeline/config.yml" <<'EOF'
version: 1
hooks:
  incoming: trusted
  trusted-ref: HEAD
EOF
pipeline add --copy
```

`--copy` places Pipeline and Just in the repository, so hooks do not depend on
the temporary launcher. Install them after a bare repository's default branch
exists. The trusted policy keeps hook definitions on the current default branch
instead of accepting replacements from the push being checked.

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
