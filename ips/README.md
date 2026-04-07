# IPS

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
