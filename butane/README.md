
# Butane

Build the butane files:

```sh
yq ea '. as $item ireduce ({}; . *+ $item)' butane/base.yml butane/setup.yml > butane/setup.bu
yq ea '. as $item ireduce ({}; . *+ $item)' butane/base.yml butane/updates.yml butane/workstation.yml > butane/workstation.bu
yq ea '. as $item ireduce ({}; . *+ $item)' butane/base.yml butane/updates.yml butane/workstation.yml > butane/sway.bu
yq ea '. as $item ireduce ({}; . *+ $item)' butane/base.yml butane/updates.yml butane/nas.yml > butane/nas.bu
for role in k3s minecraft jellyfin; do
    yq ea '. as $item ireduce ({}; . *+ $item)' \
        butane/base.yml butane/updates.yml butane/vm.yml \
        "butane/$role.yml" > "butane/$role.bu"
done
```

The Sway profile reuses `butane/workstation.yml`; render `__CI_BOOTC_IMAGE__` as `sway` for `sway.ign` and as `workstation` for `workstation.ign`.

Render placeholders:

```sh
CI_IMAGE_NAMESPACE=ghcr.io/noobping

render_butane() {
    input="$1"
    output="$2"
    bootc_image="$3"

    sed \
        -e "s#__CI_IMAGE_NAMESPACE__#${CI_IMAGE_NAMESPACE}#g" \
        -e "s#__CI_BOOTC_IMAGE__#${bootc_image}#g" \
        "$input" > "$output"
}

render_butane butane/setup.bu butane/setup.rendered.bu workstation
render_butane butane/workstation.bu butane/workstation.rendered.bu workstation
render_butane butane/sway.bu butane/sway.rendered.bu sway
render_butane butane/nas.bu butane/nas.rendered.bu nas
for role in k3s minecraft jellyfin; do
    render_butane "butane/$role.bu" "butane/$role.rendered.bu" "$role"
done
```

Build ignition file:

```sh
butane --pretty --strict --files-dir . butane/setup.rendered.bu > setup.ign
butane --pretty --strict --files-dir . butane/workstation.rendered.bu > workstation.ign
butane --pretty --strict --files-dir . butane/sway.rendered.bu > sway.ign
butane --pretty --strict --files-dir . butane/nas.rendered.bu > nas.ign
mkdir -p dist/ign
for role in k3s minecraft jellyfin; do
    butane --pretty --strict --files-dir . \
        "butane/$role.rendered.bu" > "dist/ign/$role.ign"
done
```

Download live ISO

```sh
podman run --rm -it \
    --userns=keep-id \
    --user $(id -u):$(id -g) \
    -v $PWD:/work:Z -w /work \
    quay.io/coreos/coreos-installer:release \
    download -s stable -a $(uname -m) -p metal -f iso -C /work --decompress
```

Build the customized ISO:

```sh
PROFILE=workstation

podman run --rm -it \
    --userns=keep-id \
    --user $(id -u):$(id -g) \
    -v $PWD:/work:Z -w /work \
    quay.io/coreos/coreos-installer:release \
    iso customize \
        --live-ignition setup.ign \
        --dest-ignition ${PROFILE}.ign \
        --pre-install butane/detect-device.sh \
        -o ${PROFILE}-$(uname -m).iso \
        $(ls -1 fedora-coreos-*-live-iso.$(uname -m).iso | tail -n1)
```
