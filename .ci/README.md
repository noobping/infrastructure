# CI workflows

```sh
ci build
ci images
ci butane
ci offline
```

`build` checks and builds the CI tool. `images` builds and pushes the IPS,
hardware, and VM images. `butane` renders installer ISOs and VM Ignition files.
`offline` builds the x64 Workstation ISO with its image embedded.

Image workflows default to `localhost:5000/noobping` with TLS verification off.
Set `CI_IMAGE_NAMESPACE`, `CI_REGISTRY_TLS_VERIFY=true`, and optionally
`CI_SIGN_IMAGES=1` for another registry and signed manifests.
