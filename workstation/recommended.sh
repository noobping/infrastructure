#!/usr/bin/env bash
set -euo pipefail

DONE_FILE="$HOME/.config/recommended.done"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
LOG_FILE="$LOG_DIR/recommended.log"
WALLPAPER_URI="file:///usr/share/backgrounds/wallpaper.png"
PROFILE_ICON="/usr/share/pixmaps/faces/noobping.png"
PROFILE_LANGUAGE="nl_NL.UTF-8"
EXTENSIONS_DIR="$HOME/.local/share/gnome-shell/extensions"

mkdir -p "$HOME/.config" "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1

log() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*"
}

set_gsetting() {
  gsettings set "$@" || true
}

log "starting recommended"

if [[ -f "$DONE_FILE" ]]; then
  log "recommended already applied"
  exit 0
fi

accountsservice_user_path() {
  command -v gdbus >/dev/null 2>&1 || return 1

  gdbus call --system \
    --dest org.freedesktop.Accounts \
    --object-path /org/freedesktop/Accounts \
    --method org.freedesktop.Accounts.FindUserByName "$USER" 2>/dev/null \
    | sed -n "s/.*'\([^']*\)'.*/\1/p"
}

set_profile_icon() {
  local user_path

  [[ -f "$PROFILE_ICON" ]] || return 0
  user_path="$(accountsservice_user_path)" || return 0
  [[ -n "$user_path" ]] || return 0

  gdbus call --system \
    --dest org.freedesktop.Accounts \
    --object-path "$user_path" \
    --method org.freedesktop.Accounts.User.SetIconFile \
    "$PROFILE_ICON" >/dev/null 2>&1 || true
}

set_profile_language() {
  local user_path

  user_path="$(accountsservice_user_path)" || return 0
  [[ -n "$user_path" ]] || return 0

  gdbus call --system \
    --dest org.freedesktop.Accounts \
    --object-path "$user_path" \
    --method org.freedesktop.Accounts.User.SetLanguage \
    "$PROFILE_LANGUAGE" >/dev/null 2>&1 || true
}

enable_gnome_extensions() {
  local extension
  local extension_id
  local extensions_list="["

  [[ -d "$EXTENSIONS_DIR" ]] || return 0

  shopt -s nullglob
  for extension in "$EXTENSIONS_DIR"/*; do
    [[ -d "$extension" ]] || continue
    extension_id="${extension##*/}"
    extensions_list="${extensions_list}'${extension_id}', "
  done
  shopt -u nullglob

  extensions_list="${extensions_list%, }]"

  set_gsetting org.gnome.shell enabled-extensions "$extensions_list"
}

configure_terminal_shortcut() {
  local base="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"
  local schema="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$base"

  [[ -x /usr/bin/ptyxis ]] || return 0

  set_gsetting org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['$base']"
  set_gsetting "$schema" name 'Terminal'
  set_gsetting "$schema" command 'ptyxis --new-window'
  set_gsetting "$schema" binding '<Control><Alt>t'
}

log "applying desktop defaults"

set_gsetting org.gnome.desktop.background picture-uri "$WALLPAPER_URI"
set_gsetting org.gnome.desktop.background picture-uri-dark "$WALLPAPER_URI"
set_gsetting org.gnome.desktop.background picture-options 'zoom'
set_gsetting org.gnome.desktop.screensaver picture-uri "$WALLPAPER_URI"
set_gsetting org.gnome.desktop.interface accent-color 'green'
set_gsetting org.gnome.desktop.interface gtk-enable-primary-paste true
set_gsetting org.gnome.system.locale region "$PROFILE_LANGUAGE"

set_profile_icon
set_profile_language
configure_terminal_shortcut
enable_gnome_extensions

set_gsetting org.gnome.shell favorite-apps "['org.gnome.Nautilus.desktop', 'io.github.kolunmi.Bazaar.desktop', 'com.mattjakeman.ExtensionManager.desktop', 'org.gnome.Epiphany.desktop']"

if command -v git >/dev/null 2>&1; then
  git config --global pull.rebase false || true
fi

notify-send "Done" "Applied desktop defaults" || true

touch "$DONE_FILE"
log "recommended finished successfully"

exit 0
