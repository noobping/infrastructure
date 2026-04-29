#!/usr/bin/env bash
set -euo pipefail

DONE_FILE="$HOME/.config/recommended.done"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
LOG_FILE="$LOG_DIR/recommended.log"
WALLPAPER_URI="file:///usr/share/backgrounds/wallpaper.png"
PROFILE_ICON="/usr/share/pixmaps/faces/noobping.png"
PROFILE_LANGUAGE="nl_NL.UTF-8"
GNOME_EXTENSIONS=(
  appindicatorsupport@rgcjonas.gmail.com
  auto-activities@CleoMenezesJr.github.io
  category-sorted-app-grid@noobping.dev
  draw-on-gnome@daveprowse.github.io
  hotedge@jonathan.jdoda.ca
  in-picture@filiprund.cz
  reboottouefi@ubaygd.com
)

mkdir -p "$HOME/.config" "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1

echo "[$(date --iso-8601=seconds)] starting recommended"

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

  [ -f "$PROFILE_ICON" ] || return 0
  user_path="$(accountsservice_user_path)" || return 0
  [ -n "$user_path" ] || return 0

  gdbus call --system \
    --dest org.freedesktop.Accounts \
    --object-path "$user_path" \
    --method org.freedesktop.Accounts.User.SetIconFile \
    "$PROFILE_ICON" >/dev/null 2>&1 || true
}

set_profile_language() {
  local user_path

  user_path="$(accountsservice_user_path)" || return 0
  [ -n "$user_path" ] || return 0

  gdbus call --system \
    --dest org.freedesktop.Accounts \
    --object-path "$user_path" \
    --method org.freedesktop.Accounts.User.SetLanguage \
    "$PROFILE_LANGUAGE" >/dev/null 2>&1 || true
}

copy_skel_files() {
  [ -d /etc/skel ] || return 0

  cp -rn /etc/skel/. "$HOME"/
}

enable_gnome_extensions() {
  local extension
  local extensions_list="["

  for extension in "${GNOME_EXTENSIONS[@]}"; do
    extensions_list="${extensions_list}'${extension}', "
  done
  extensions_list="${extensions_list%, }]"

  gsettings set org.gnome.shell enabled-extensions "$extensions_list" || true
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

  if [ -x /usr/bin/ptyxis ]; then
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/']"
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
      name 'Terminal'
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
      command 'ptyxis --new-window'
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
      binding '<Control><Alt>t'
  fi

  gsettings set org.gnome.shell favorite-apps "['org.gnome.Nautilus.desktop', 'io.github.kolunmi.Bazaar.desktop', 'com.mattjakeman.ExtensionManager.desktop', 'org.gnome.Epiphany.desktop']"
  copy_skel_files
  enable_gnome_extensions

  git config --global pull.rebase false

  notify-send "Done" "Applied desktop defaults" || true

  touch "$DONE_FILE"
  echo "[$(date --iso-8601=seconds)] recommended finished successfully"
fi

exit 0
