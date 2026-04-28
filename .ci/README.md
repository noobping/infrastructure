# Workflows

Common commands from the `public-infrastructure` repository:

```sh
ci images
ci ips
ci nas
ci workstation
ci butane
```

`images` builds and pushes IPS, NAS, and Workstation arch tags, then pushes manifest tags. `butane` only builds installer ISOs and checksums under `dist/iso`.

Set `CI_REGISTRY_TLS_VERIFY=true` for a TLS registry. The default is `false` for an insecure local registry.

Set `CI_SIGN_IMAGES=1` to run `cosign sign` after each arch image push. By default these local builds are pushed unsigned.
