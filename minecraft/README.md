# Minecraft VM

This role runs the Java (Paper) and Bedrock servers as root-managed Quadlets.
Both container images are pinned by release and multi-architecture manifest
digest. The VM state disk must use virtio serial `minecraft-data` and is
mounted at `/var/lib/containers/minecraft` by Ignition.

Java is exposed on TCP 25565 and Bedrock on UDP 19132/19133. Both
containers use the dedicated guest network directly so Suricata inspects their
LAN traffic. The guest firewall does not open RCON port 25575 to the LAN.

## Migrate the worlds

Rehearse this with a copy first. Let the new guest complete its image rebase,
then prevent its empty servers from restarting while data is copied:

```sh
ssh nick@minecraft.vm \
  'sudo systemctl mask --now minecraft.service bedrock.service'
```

At the maintenance window, flush and stop the old NAS servers. Do not let old
and new servers write the same worlds:

```sh
sudo podman exec systemd-minecraft rcon-cli save-all flush
sudo systemctl stop minecraft.service bedrock.service
sudo tar --acls --xattrs --numeric-owner \
  -C /var/lib/containers/minecraft -cpf - java bedrock | \
  ssh nick@minecraft.vm \
    'sudo tar --acls --xattrs --numeric-owner -C /var/lib/containers/minecraft -xpf -'
ssh nick@minecraft.vm \
  'sudo chown -R 1003:1003 /var/lib/containers/minecraft/java /var/lib/containers/minecraft/bedrock && sudo restorecon -RF /var/lib/containers/minecraft'
```

Start the guest copies only after the transfer succeeds:

```sh
ssh nick@minecraft.vm \
  'sudo systemctl unmask minecraft.service bedrock.service && sudo systemctl start minecraft.service bedrock.service'
```

Join both editions, verify the expected worlds and player data, make a test
change, restart both services, and verify the change persisted. For rollback,
stop and mask the guest services before unmasking the legacy NAS services. If
players wrote new state after cutover, copy the guest worlds back into a clone
of the pre-cutover snapshot before restarting the old servers; never merge two
live world trees.

## Weekly backup export

The NAS backup invokes `/usr/libexec/infrastructure/backup-prepare` through QEMU
Guest Agent before freezing the VM data disk. It briefly disables Java saves
and holds Bedrock saves, then atomically publishes the consistent world copy at
`/var/lib/containers/minecraft/backups/current`. A server that is already
stopped is copied without sending console commands, so the export still
contains both existing editions. Restore `java/world*` and `bedrock/worlds`
from that directory while both services are stopped.
