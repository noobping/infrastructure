# IPS

Build the Suricata container image:

```sh
podman build -t ghcr.io/noobping/ips:latest .
```

Sync rules with the container image:

```sh
podman run --rm --network=host \
  -e SURICATA_SYNC_ONLY=1 \
  -v /var/lib/suricata:/var/lib/suricata:Z \
  -v /var/log/suricata:/var/log/suricata:Z \
  ghcr.io/noobping/ips:latest
```

Run it the same way Quadlet will:

```sh
podman run --rm --network=host \
  --cap-add=NET_ADMIN --cap-add=NET_RAW \
  -v /var/lib/suricata:/var/lib/suricata:Z \
  -v /var/log/suricata:/var/log/suricata:Z \
  ghcr.io/noobping/ips:latest
```
