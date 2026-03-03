#!/usr/bin/env bash
set -euo pipefail

DONE_FILE="$HOME/.config/recommended.done"

gext() {
  podman run --rm \
    --userns=keep-id \
    --security-opt label=disable \
    -e DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID/bus" \
    -e XDG_RUNTIME_DIR="/run/user/$UID" \
    -v /run/user/$UID/bus:/run/user/$UID/bus \
    -v "$HOME:$HOME" \
    -w "$PWD" \
    ghcr.io/noobping/gext "$@"
}

if [ ! -f "$DONE_FILE" ]; then
  gsettings set org.gnome.shell favorite-apps "['org.gnome.Nautilus.desktop', 'io.github.kolunmi.Bazaar.desktop', 'com.mattjakeman.ExtensionManager.desktop', 'org.gnome.Epiphany.desktop']"

  gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/']"
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
    name 'Terminal'
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
    command 'ptyxis --new-window'
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
    binding '<Control><Alt>t'

  awk '!/^\s*($|#)/' /etc/recommended/extensions | xargs -r -n1 gext install
  awk '!/^\s*($|#)/' /etc/recommended/extensions | xargs -r -n1 gext enable

  systemctl --user restart gnome-shell-extension-prefs.service 2>/dev/null || true
  systemctl --user restart gnome-shell.service 2>/dev/null || true

  busctl --user call org.gnome.Shell /org/gnome/Shell org.gnome.Shell Eval s 'Main.extensionManager._loadExtensions(); "ok";' >/dev/null 2>&1 || true

  touch "$DONE_FILE"
fi

exit 0