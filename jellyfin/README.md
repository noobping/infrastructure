# Jellyfin VM

The Jellyfin container image is pinned by release and multi-architecture
manifest digest. No GPU is passed through. The VM state disk must use virtio
serial `jellyfin-data`; Ignition mounts it at
`/var/lib/containers/jellyfin`.

Music and books are read-only NFSv4 automounts from `nas.vm`. The container's
SELinux separation is disabled because relabeling NFS content is unsupported;
the media mounts remain read-only, nodev, nosuid, and noexec.

Jellyfin uses the dedicated guest network namespace directly (`Network=host`) so
UDP discovery and DLNA multicast reach the UniFi LAN. The guest nftables policy
still limits inbound traffic to the documented Jellyfin ports.

## Migrate Jellyfin state

The old NAS mounts `/var/lib/containers/jellyfin` directly as Jellyfin's
`/config`; the VM uses separate `config/` and `cache/` directories. Let the
guest complete its image rebase, then keep its empty instance stopped:

```sh
ssh nick@jellyfin.vm 'sudo systemctl mask --now jellyfin.service'
```

At cutover, stop the old instance and copy configuration separately from the
rebuildable cache while preserving numeric ownership, ACLs, and xattrs:

```sh
sudo systemctl stop jellyfin.service
sudo tar --acls --xattrs --numeric-owner --exclude=./cache \
  -C /var/lib/containers/jellyfin -cpf - . | \
  ssh nick@jellyfin.vm \
    'sudo tar --acls --xattrs --numeric-owner -C /var/lib/containers/jellyfin/config -xpf -'

sudo tar --acls --xattrs --numeric-owner \
  -C /var/lib/containers/jellyfin/cache -cpf - . | \
  ssh nick@jellyfin.vm \
    'sudo tar --acls --xattrs --numeric-owner -C /var/lib/containers/jellyfin/cache -xpf -'

ssh nick@jellyfin.vm \
  'sudo chown -R 1001:1001 /var/lib/containers/jellyfin/config /var/lib/containers/jellyfin/cache && sudo restorecon -RF /var/lib/containers/jellyfin'
```

The music and books themselves stay on the NAS and must not be copied. Confirm
the read-only NFS mounts before starting Jellyfin:

```sh
ssh nick@jellyfin.vm \
  'findmnt --target /var/srv/music && findmnt --target /var/srv/books && sudo systemctl unmask jellyfin.service && sudo systemctl start jellyfin.service'
```

Verify libraries, users, watch state, music/book playback, and LAN discovery,
then restart Jellyfin once and verify the state persists. For rollback, stop
and mask the guest service before unmasking the legacy NAS service. If settings
changed after cutover, copy the guest `config/` contents back into a clone of
the pre-cutover NAS snapshot before restarting the old instance; never run both
instances against one configuration tree.
