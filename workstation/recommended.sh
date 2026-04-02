#!/usr/bin/env bash
set -euo pipefail

DONE_FILE="$HOME/.config/recommended.done"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
LOG_FILE="$LOG_DIR/recommended.log"
WALLPAPER_URI="file:///usr/share/backgrounds/nick-wallpaper.png"
PROFILE_ICON="/usr/share/pixmaps/faces/nick.png"
PROFILE_LANGUAGE="nl_NL.UTF-8"

mkdir -p "$HOME/.config" "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1

echo "[$(date --iso-8601=seconds)] starting recommended"

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

set_profile_icon() {
  local user_path

  [ -f "$PROFILE_ICON" ] || return 0
  command -v gdbus >/dev/null 2>&1 || return 0

  user_path="$(
    gdbus call --system \
      --dest org.freedesktop.Accounts \
      --object-path /org/freedesktop/Accounts \
      --method org.freedesktop.Accounts.FindUserByName "$USER" 2>/dev/null \
      | sed -n "s/.*'\([^']*\)'.*/\1/p"
  )"
  [ -n "$user_path" ] || return 0

  gdbus call --system \
    --dest org.freedesktop.Accounts \
    --object-path "$user_path" \
    --method org.freedesktop.Accounts.User.SetIconFile \
    "$PROFILE_ICON" >/dev/null 2>&1 || true
}

set_profile_language() {
  local user_path

  command -v gdbus >/dev/null 2>&1 || return 0

  user_path="$(
    gdbus call --system \
      --dest org.freedesktop.Accounts \
      --object-path /org/freedesktop/Accounts \
      --method org.freedesktop.Accounts.FindUserByName "$USER" 2>/dev/null \
      | sed -n "s/.*'\([^']*\)'.*/\1/p"
  )"
  [ -n "$user_path" ] || return 0

  gdbus call --system \
    --dest org.freedesktop.Accounts \
    --object-path "$user_path" \
    --method org.freedesktop.Accounts.User.SetLanguage \
    "$PROFILE_LANGUAGE" >/dev/null 2>&1 || true
}

if [ ! -f "$DONE_FILE" ]; then
  echo "Applying recommendations..."

  gsettings set org.gnome.desktop.background picture-uri "$WALLPAPER_URI"
  gsettings set org.gnome.desktop.background picture-uri-dark "$WALLPAPER_URI"
  gsettings set org.gnome.desktop.background picture-options 'zoom'
  gsettings set org.gnome.desktop.screensaver picture-uri "$WALLPAPER_URI"
  gsettings set org.gnome.desktop.interface accent-color 'green'
  gsettings set org.gnome.system.locale region "$PROFILE_LANGUAGE"
  set_profile_icon || true
  set_profile_language || true

  gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/']"
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
    name 'Terminal'
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
    command 'ptyxis --new-window'
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
    binding '<Control><Alt>t'

  if [ -f /etc/recommended/settings.dconf ]; then
    dconf load /org/gnome/shell/extensions/ < /etc/recommended/settings.dconf
  fi

  echo "Installing GNOME extensions..."
  notify-send "Installing GNOME extensions..." "Applying recommended extensions and desktop defaults" || true

  extensions_failed=0
  while IFS= read -r ext; do
    [[ -z "$ext" || "$ext" =~ ^# ]] && continue
    if ! gext install "$ext"; then
      echo "Failed to install extension: $ext" >&2
      extensions_failed=1
    fi
  done < /etc/recommended/extensions

  while IFS= read -r ext; do
    [[ -z "$ext" || "$ext" =~ ^# ]] && continue
    if ! gext enable "$ext"; then
      echo "Failed to enable extension: $ext" >&2
      extensions_failed=1
    fi
  done < /etc/recommended/extensions

  systemctl --user restart gnome-shell-extension-prefs.service 2>/dev/null || true
  systemctl --user restart gnome-shell.service 2>/dev/null || true

  busctl --user call org.gnome.Shell /org/gnome/Shell org.gnome.Shell Eval s 'Main.extensionManager._loadExtensions(); "ok";' >/dev/null 2>&1 || true

  if [ "$extensions_failed" -ne 0 ]; then
    echo "[$(date --iso-8601=seconds)] recommended finished with extension errors"
    exit 1
  fi

  gsettings set org.gnome.shell favorite-apps "['org.gnome.Nautilus.desktop', 'io.github.kolunmi.Bazaar.desktop', 'com.mattjakeman.ExtensionManager.desktop', 'org.gnome.Epiphany.desktop']"
  notify-send "Done" "Applied recommended extensions and desktop defaults" || true

  touch "$DONE_FILE"
  echo "[$(date --iso-8601=seconds)] recommended finished successfully"
fi

exit 0
