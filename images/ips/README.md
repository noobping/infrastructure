# IPS

The image enables Suricata inline filtering and ClamAV on-access scanning.
ClamAV watches mutable data locations, updates signatures with `freshclam`,
and removes infected files directly instead of quarantining them.

Build the operating system:

```sh
podman build -t ghcr.io/noobping/ips:latest .
```

Test the bootable container:

```sh
podman run --rm -it \
  --entrypoint /bin/bash \
  ghcr.io/noobping/ips:latest
```
