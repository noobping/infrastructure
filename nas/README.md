# NAS

Create `/var/lib/containers/secrets/admin-password` before expecting the Uptime Kuma bootstrap to finish.

You can also set `/var/lib/containers/secrets/admin-username`; it defaults to `admin`.

This image no longer provisions FreeIPA, FreeRADIUS, or any other domain-controller services.

## Minecraft

Enter Bedrock

```sh
sudo podman exec -it systemd-bedrock /bin/bash
```

Enter Minecraft

```sh
sudo podman exec -it systemd-minecraft /bin/bash
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
