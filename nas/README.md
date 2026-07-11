# NAS

Create `/var/lib/containers/secrets/admin-password` before expecting the Uptime Kuma bootstrap to finish.

You can also set `/var/lib/containers/secrets/admin-username`; it defaults to `admin`.

This image no longer provisions FreeIPA, FreeRADIUS, or any other domain-controller services.

## Minecraft

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

### Java

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
