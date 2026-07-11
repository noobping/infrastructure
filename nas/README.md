# NAS

Create `/var/lib/containers/secrets/admin-password` before expecting the Uptime Kuma bootstrap to finish.

You can also set `/var/lib/containers/secrets/admin-username`; it defaults to `admin`.

This image no longer provisions FreeIPA, FreeRADIUS, or any other domain-controller services.

## Minecraft

### Bedrock

Enter console

```sh
sudo podman exec -it systemd-bedrock /bin/bash
```

Show allowlist

```sh
sudo podman exec systemd-bedrock send-command allowlist list
```

Allow player

```sh
sudo podman exec systemd-bedrock send-command allowlist add "YourGamertag"
```

OP player

```sh
sudo podman exec systemd-bedrock send-command op "YourGamertag"
```

### Java

Enter console

```sh
sudo podman exec -it systemd-minecraft /bin/bash
```

Show allowlist

```sh
sudo podman exec systemd-minecraft send-command allowlist list
```

Allow player

```sh
sudo podman exec systemd-minecraft send-command allowlist add "YourGamertag"
```

OP player

```sh
sudo podman exec systemd-minecraft send-command op "YourGamertag"
```
