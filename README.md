
# Desktop ignition

Build the butane files:

```sh
yq ea '. as $item ireduce ({}; . *+ $item)' base.yml setup.yml > setup.bu
yq ea '. as $item ireduce ({}; . *+ $item)' base.yml workstation.yml > workstation.bu
```

Build ignition file:

```sh
butane --pretty --strict --files-dir . setup.bu > setup.ign
butane --pretty --strict workstation.bu > workstation.ign
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

Build customized ISO:

```sh
podman run --rm -it \
    --userns=keep-id \
    --user $(id -u):$(id -g) \
    -v $PWD:/work:Z -w /work \
    quay.io/coreos/coreos-installer:release \
    iso customize \
        --live-ignition setup.ign \
        --dest-ignition workstation.ign \
        --pre-install detect-device.sh \
        -o workstation-$(uname -m).iso \
        $(ls -1 fedora-coreos-*-live-iso.$(uname -m).iso | tail -n1)
```
