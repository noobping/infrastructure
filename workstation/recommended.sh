#!/usr/bin/env bash
set -euo pipefail

DONE_FILE="$HOME/.config/recommended.done"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
LOG_FILE="$LOG_DIR/recommended.log"
WALLPAPER_URI="file:///usr/share/backgrounds/wallpaper.png"
PROFILE_ICON="/usr/share/pixmaps/faces/noobping.png"
PROFILE_LANGUAGE="nl_NL.UTF-8"
GEXT_IMAGE_DEFAULT="ghcr.io/noobping/gext:latest"
GEXT_IMAGE_FILE="/etc/recommended/gext-image"
GEXT_IMAGE="$GEXT_IMAGE_DEFAULT"
GEXT_PREPARED=0

mkdir -p "$HOME/.config" "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1

echo "[$(date --iso-8601=seconds)] starting recommended"

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

resolve_gext_image() {
  if [ -r "$GEXT_IMAGE_FILE" ]; then
    awk 'NF { print; exit }' "$GEXT_IMAGE_FILE"
    return
  fi

  printf '%s\n' "$GEXT_IMAGE_DEFAULT"
}

prepare_gext() {
  [ "$GEXT_PREPARED" -eq 0 ] || return 0
  command -v podman >/dev/null 2>&1 || return 1

  GEXT_IMAGE="$(resolve_gext_image)"

  if ! podman image exists "$GEXT_IMAGE" >/dev/null 2>&1; then
    podman pull "$GEXT_IMAGE" || return 1
  fi

  sync_podman_trust || return 1
  GEXT_PREPARED=1
}

gext() {
  prepare_gext || return 1

  podman run --rm \
    --userns=keep-id \
    --security-opt label=disable \
    -e DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID/bus" \
    -e XDG_RUNTIME_DIR="/run/user/$UID" \
    -v /run/user/$UID/bus:/run/user/$UID/bus \
    -v "$HOME:$HOME" \
    -w "$PWD" \
    "$GEXT_IMAGE" "$@"
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

apply_desktop_session_policy() {
  [ -f /etc/recommended/disable-lock-and-suspend ] || return 0

  gsettings set org.gnome.desktop.screensaver lock-enabled false
  gsettings set org.gnome.desktop.screensaver idle-activation-enabled false
  gsettings set org.gnome.desktop.screensaver lock-delay uint32 0
  gsettings set org.gnome.desktop.session idle-delay uint32 0
  gsettings set org.gnome.desktop.lockdown disable-lock-screen true
  gsettings set org.gnome.settings-daemon.plugins.power idle-dim false
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'
}

apply_desktop_session_policy || true

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

  if [ -x /usr/bin/ptyxis ]; then
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/']"
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
      name 'Terminal'
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
      command 'ptyxis --new-window'
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
      binding '<Control><Alt>t'
  fi

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
