alias butane='podman run --rm -it \
    --userns=keep-id \
    --user $(id -u):$(id -g) \
    -v "$PWD:/work:Z" -w /work \
    quay.io/coreos/butane:release'