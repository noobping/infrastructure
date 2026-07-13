# Butane

`base.yml` owns the settings shared by every machine: the tracked bootc image,
the verified first-boot rebase, and the verified daily update timer. Host
profiles merge it with one role fragment; guests also merge `vm.yml`.

The workflow is the canonical builder. For a local host build, choose the role
fragment and image name (Sway uses `FRAGMENT=workstation BOOTC_IMAGE=sway`):

```sh
PROFILE=nas FRAGMENT=nas BOOTC_IMAGE=nas
yq ea '. as $item ireduce ({}; . *+ $item)' \
  butane/base.yml "butane/$FRAGMENT.yml" > "butane/$PROFILE.bu"
sed -e 's#__CI_IMAGE_NAMESPACE__#ghcr.io/noobping#g' \
  -e "s#__CI_BOOTC_IMAGE__#$BOOTC_IMAGE#g" \
  "butane/$PROFILE.bu" > "butane/$PROFILE.rendered.bu"
podman run --rm -v "$PWD:/work:Z" -w /work quay.io/coreos/butane:release \
  --pretty --strict --files-dir . "butane/$PROFILE.rendered.bu" > "$PROFILE.ign"
```

Create an installer ISO from the verified upstream FCOS ISO:

```sh
podman run --rm --userns=keep-id --user "$(id -u):$(id -g)" \
  -v "$PWD:/work:Z" -w /work quay.io/coreos/coreos-installer:release \
  download -s stable -a "$(uname -m)" -p metal -f iso -C /work --decompress

podman run --rm --userns=keep-id --user "$(id -u):$(id -g)" \
  -v "$PWD:/work:Z" -w /work quay.io/coreos/coreos-installer:release \
  iso customize --dest-ignition "$PROFILE.ign" \
  --pre-install butane/detect-device.sh -o "$PROFILE-$(uname -m).iso" \
  "$(ls -1 fedora-coreos-*-live-iso."$(uname -m)".iso | tail -n1)"
```

The pre-install hook selects the smallest non-removable local disk and writes
the installer destination configuration. No separate live Ignition is needed.

## VM profiles

Render each guest with its role as `BOOTC_IMAGE`:

```sh
mkdir -p dist/ign
for role in minecraft jellyfin k3s; do
  yq ea '. as $item ireduce ({}; . *+ $item)' \
    butane/base.yml butane/vm.yml "butane/$role.yml" > "butane/$role.bu"
  sed -e 's#__CI_IMAGE_NAMESPACE__#ghcr.io/noobping#g' \
    -e "s#__CI_BOOTC_IMAGE__#$role#g" \
    "butane/$role.bu" > "butane/$role.rendered.bu"
  podman run --rm -v "$PWD:/work:Z" -w /work quay.io/coreos/butane:release \
    --pretty --strict --files-dir . "butane/$role.rendered.bu" \
    > "dist/ign/$role.ign"
done
```

The generic first-boot service reads `/etc/bootc-image-ref`, verifies the role
image, rebases to its immutable digest, and reboots. The same verifier stages
later updates. The role fragments only define guest-specific storage and
services.

Attach each state disk with the serial expected by its profile:

| Profile | Virtio serial | Guest mount |
|---|---|---|
| Minecraft | `minecraft-data` | `/var/lib/containers/minecraft` |
| Jellyfin | `jellyfin-data` | `/var/lib/containers/jellyfin` |
| K3s | `k3s-data` | `/var/lib/rancher/k3s` |

The provisioner downloads and verifies the upstream FCOS QEMU qcow2 before
attaching the rendered Ignition.
