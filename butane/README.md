# Butane

The source fragments in this directory define three host profiles and five
VM guests. Workstation and Sway share `workstation.yml`; their rendered
`__BOOTC_IMAGE__` values select the final image.

From the repository root, build every image, render and validate every
Ignition config, and create the AMD64 and ARM64 host installers with:

```sh
just offline both
```

Omit `both` to build only the host architecture.

Generated Butane files are written to `dist/butane`, Ignition files to
`dist/ign`, and NAS, Workstation, and Sway ISOs to `dist/iso`. Each ISO embeds
its matching OCI image and checksum so installation can fall back when the
configured registry is unavailable.

The online media Pipeline renders the same profiles for both supported
architectures without embedding images. GitHub invokes those same
architecture-specific Pipeline targets on native runners.
