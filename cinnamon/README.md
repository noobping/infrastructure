# Cinnamon

Build the operating system:

```sh
podman build -t ghcr.io/noobping/cinnamon:latest .
```

Test the bootable container:

```sh
podman run --rm -it \
  --entrypoint /bin/bash \
  ghcr.io/noobping/cinnamon
```
