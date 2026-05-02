# Workflows

Common commands from the `public-infrastructure` repository:

```sh
ci images
ci ips
ci nas
ci opa
ci workstation
ci offline
ci offline-opa
ci butane
```

`images` builds and pushes IPS, NAS, OPA, and Workstation arch tags, then pushes manifest tags. `butane` only builds installer ISOs and checksums under `dist/iso`.
`offline` builds a x64-only Workstation ISO with the bootc image embedded under
`dist/iso/workstation-offline-x86_64.iso`; it starts `localhost:5000` when the local registry is not already responding.
`offline-opa` does the same for OPA and writes `dist/iso/opa-offline-x86_64.iso`.

Set `CI_REGISTRY_TLS_VERIFY=true` for a TLS registry. The default is `false` for an insecure local registry.

Set `CI_SIGN_IMAGES=1` to run `cosign sign` after each arch image push. By default these local builds are pushed unsigned.
