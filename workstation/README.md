
# Workstation

Build the operating systyem:

```sh
podman build -t ghcr.io/noobping/workstation:latest .
```

Test the bootable container:

```sh
podman run --rm -it \
  --entrypoint /bin/bash \
  ghcr.io/noobping/workstation
```
