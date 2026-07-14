# Jellyfin VM

The Jellyfin container image is pinned by release and multi-architecture
manifest digest. No GPU is passed through. Quadlet named volumes mount the
existing configuration, cache, music, and books directories directly from the
NAS over NFSv4.2 with FS-Cache; no application directory is bound from the
guest filesystem.

Music and books are read-only. The container's SELinux separation is disabled
because relabeling NFS content is unsupported; every NFS volume remains nodev,
nosuid, and noexec.

Jellyfin uses the dedicated guest network namespace directly (`Network=host`) so
UDP discovery and DLNA multicast reach the UniFi LAN. The guest nftables policy
still limits inbound traffic to the documented Jellyfin ports.

## Migrate Jellyfin state

The old NAS service and the guest use the same NAS configuration and cache
directories, so there is no data copy. Keep the guest powered off until
cutover, then stop the old instance before first booting the guest. Never let
both instances write the shared configuration:

```sh
sudo systemctl stop jellyfin.service
sudo virsh start jellyfin
```

The guest rebases and reboots once; its enabled service then starts normally.
Inspect the named volumes after it returns:

```sh
ssh nick@jellyfin.vm \
  'sudo podman volume inspect systemd-jellyfin-config systemd-jellyfin-cache systemd-jellyfin-music systemd-jellyfin-books'
```

Verify libraries, users, watch state, music/book playback, and LAN discovery,
then restart Jellyfin once and verify the state persists. For rollback, stop
the guest service before starting the legacy NAS service; never run both
instances against one configuration tree.
