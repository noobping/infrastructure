# Encrypted secrets

`examples/` is never referenced by Kustomize. Copy each example into this
directory without the `.example` suffix, replace every placeholder, encrypt it
with SOPS, and add the encrypted filename to `kustomization.yaml`.

A committed secret is valid only when `sops --decrypt FILE` succeeds and the
Git diff contains `sops:` metadata plus encrypted values. Never commit the age
private key or a file that still contains `REPLACE_`.

