![License](https://img.shields.io/badge/license-MIT-blue.svg)
[![Continuous](https://github.com/noobping/infrastructure/actions/workflows/continuous.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/continuous.yml)

# Infrastructure

Immutable Fedora CoreOS images and installers for workstations, storage nodes,
and VM guests. Just contains the build recipes; Pipeline connects them into
dependency graphs.

## Commands

```sh
just offline [selection] [architecture]

# selection:    all (default), workstation, sway, nas
# architecture: native (default), both, amd64, arm64
just offline workstation amd64
just offline amd64
```

Offline builds start or reuse a local registry and embed the matching OCI image
inside each installer. Architecture graphs run sequentially while independent
branches within a graph run in parallel.

## Publishing and build environment

Online builds default to `IMAGE_NAMESPACE=ghcr.io/noobping`. GitHub Actions
uses that namespace; GitLab CI overrides it with its project container
registry. Authenticate the container tools with `REGISTRY_USER` and
`REGISTRY_TOKEN`. Publishing to a non-local registry requires `PUBLISH=true`
and a clean checkout; `ALLOW_DIRTY=true` is available for an intentional
development build. Manifest signing uses Cosign's ambient keyless credentials
from GitHub or GitLab.com OIDC. Set `SIGN_IMAGES=false` for an unsigned or
self-managed test registry and `REGISTRY_TLS_VERIFY=false` for an insecure
local registry.

Image builds need host Podman and Buildah, plus Skopeo for split-runner manifest
publication, Cosign when signing is enabled, sufficient disk space, and
QEMU/binfmt when building a non-native architecture. Release uses an installed
GitHub CLI or Podman. Build execution refreshes upstream images, packages, and
Fedora CoreOS media, so it requires network access. “Offline” means the
resulting installer can install without a network connection. The ARM64 NAS
image and installer are supported; its bundled libvirt VM deployment remains
x86_64-only.
