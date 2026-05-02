# OPA

Build the image:

```sh
podman build -t ghcr.io/noobping/opa:latest .
```

Run a shell in the image:

```sh
podman run --rm -it \
  --privileged \
  ghcr.io/noobping/opa
```

OPA is a lean Cinnamon desktop profile based on the IPS image. It keeps desktop hardware, printing, scanning, firewall, and system Flatpak support while leaving out AppImage helpers, virtualization, and development tooling.
