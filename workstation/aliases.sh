if ! [[ "$PATH" =~ "$HOME/AppImages:" ]]; then
    PATH="$HOME/AppImages:$PATH"
fi
export PATH

alias appimage-builder='podman run --rm -it \
    -v $(pwd):/project:Z \
    -w /project \
    appimagecrafters/appimage-builder:latest appimage-builder --skip-test'

alias butane='podman run --rm -it \
    --userns=keep-id \
    --user $(id -u):$(id -g) \
    -v "$PWD:/work:Z" -w /work \
    quay.io/coreos/butane:release'

alias yq='podman run --rm -i \
  --userns=keep-id \
  --user $(id -u):$(id -g) \
  -v "$PWD:/work:Z" -w /work \
  docker.io/mikefarah/yq:latest'

alias flatpak-builder="flatpak run org.flatpak.Builder"
alias zola="flatpak run org.getzola.zola"

alias gext='podman run --rm \
  --userns=keep-id \
  --security-opt label=disable \
  -e DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID/bus" \
  -e XDG_RUNTIME_DIR="/run/user/$UID" \
  -v /run/user/$UID/bus:/run/user/$UID/bus \
  -v $HOME:$HOME \
  -w $PWD \
  ghcr.io/noobping/gext "$@"'
