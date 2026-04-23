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

sync_podman_trust() {
  [ -x /usr/libexec/infrastructure/fapolicyd-podman-sync ] || return 0
  command -v pkexec >/dev/null 2>&1 || return 0
  command -v systemctl >/dev/null 2>&1 || return 0

  if ! systemctl is-enabled --quiet fapolicyd.service && \
     ! systemctl is-active --quiet fapolicyd.service; then
    return 0
  fi

  pkexec /usr/libexec/infrastructure/fapolicyd-podman-sync "$UID" "$HOME"
}

gext_image_ref() {
  if [ -r /etc/recommended/gext-image ]; then
    awk 'NF { print; exit }' /etc/recommended/gext-image
    return
  fi

  printf '%s\n' 'ghcr.io/noobping/gext:latest'
}

gext() {
  local image

  image="$(gext_image_ref)"

  if ! podman image exists "$image" >/dev/null 2>&1; then
    podman pull "$image"
  fi

  sync_podman_trust || return 1

  podman run --rm \
    --userns=keep-id \
    --security-opt label=disable \
    -e DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID/bus" \
    -e XDG_RUNTIME_DIR="/run/user/$UID" \
    -v /run/user/$UID/bus:/run/user/$UID/bus \
    -v "$HOME:$HOME" \
    -w "$PWD" \
    "$image" "$@"
}
