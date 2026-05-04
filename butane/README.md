
# Butane

Build the butane files:

```sh
yq ea '. as $item ireduce ({}; . *+ $item)' butane/base.yml butane/setup.yml > butane/setup.bu
yq ea '. as $item ireduce ({}; . *+ $item)' butane/base.yml butane/updates.yml butane/workstation.yml > butane/workstation.bu
yq ea '. as $item ireduce ({}; . *+ $item)' butane/base.yml butane/updates.yml butane/nas.yml > butane/nas.bu
```

Build ignition file:

```sh
butane --pretty --strict --files-dir . butane/setup.bu > setup.ign
butane --pretty --strict butane/workstation.bu > workstation.ign
butane --pretty --strict butane/nas.bu > nas.ign
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
