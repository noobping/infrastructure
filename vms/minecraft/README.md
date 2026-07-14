# Minecraft VM

This role runs the Java (Paper) and Bedrock servers as root-managed Quadlets.
Both container images are pinned by release and multi-architecture manifest
digest. Two Quadlet named volumes mount the existing NAS `java` and `bedrock`
directories over NFSv4.2 with FS-Cache; no application directory is bound from
the guest filesystem.

Java is exposed on TCP 25565 and Bedrock on UDP 19132/19133. Both
containers use the dedicated guest network directly so Suricata inspects their
LAN traffic. The guest firewall does not open RCON port 25575 to the LAN.

## Bedrock

Enter server console

```sh
sudo podman exec -it systemd-bedrock /bin/bash
```

Show allowlist

```sh
send-command allowlist list
```

Allow player

```sh
send-command allowlist add "YourGamertag"
```

OP player

```sh
send-command op "YourGamertag"
```

## Java

Enter server console

```sh
sudo podman exec -it systemd-minecraft rcon-cli
```

Show allowlist

```sh
whitelist list
```

Allow player

```sh
whitelist add "YourUsername"
```

OP player

```sh
op "YourUsername"
```

## Migrate the worlds

The guest and legacy NAS services use the same NAS directories, so there is no
data copy. Keep the guest powered off until the maintenance window. Then flush
and stop the old NAS servers before first booting the guest:

```sh
sudo podman exec systemd-minecraft rcon-cli save-all flush
sudo systemctl stop minecraft.service bedrock.service
sudo virsh start minecraft
```

The guest rebases and reboots once; its enabled services then start normally.
Inspect the named volumes after it returns:

```sh
ssh nick@minecraft.vm \
  'sudo podman volume inspect systemd-minecraft-java systemd-minecraft-bedrock'
```

Join both editions, verify the expected worlds and player data, make a test
change, restart both services, and verify the change persisted. For rollback,
stop the guest services before starting the legacy NAS services. Never run both
sets of writers against these shared directories.
