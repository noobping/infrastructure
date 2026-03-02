#!/usr/bin/env bash
set -euo pipefail

DONE_FILE="$HOME/.config/recommended.done"
VENV_DIR="$HOME/.local/gext"
GEXT="$VENV_DIR/bin/gext"
PIP="$VENV_DIR/bin/pip"

if [ ! -f "$DONE_FILE" ]; then
  gsettings set org.gnome.shell favorite-apps "['org.gnome.Nautilus.desktop', 'io.github.kolunmi.Bazaar.desktop', 'com.mattjakeman.ExtensionManager.desktop', 'org.gnome.Epiphany.desktop']"

  gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/']"
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
    name 'Terminal'
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
    command 'ptyxis --new-window'
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
    binding '<Control><Alt>t'

  python3 -m venv "$VENV_DIR"
  "$PIP" install --no-cache-dir --upgrade pip
  "$PIP" install --no-cache-dir gnome-extensions-cli

  ln -s "$GEXT" "$HOME/.local/bin/gext"

  awk '!/^\s*($|#)/' /etc/recommended/extensions | xargs -r -n1 "$GEXT" install
  awk '!/^\s*($|#)/' /etc/recommended/extensions | xargs -r -n1 "$GEXT" enable

  systemctl --user restart gnome-shell-extension-prefs.service 2>/dev/null || true
  systemctl --user restart gnome-shell.service 2>/dev/null || true

  busct`l --user call org.gnome.Shell /org/gnome/Shell org.gnome.Shell Eval s \
    'Main.extensionManager._loadExtensions(); "ok";' \
    >/dev/null 2>&1 || true

  touch "$DONE_FILE"
fi

exit 0