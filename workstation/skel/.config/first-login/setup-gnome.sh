#!/usr/bin/env bash
set -e

BASE="$HOME/.config/first-login"
dconf load /org/gnome/shell/extensions/ < "$BASE/gnome-extensions-settings.dconf"
# dconf load /org/gnome/shell/ < "$BASE/gnome-shell-settings.dconf"

gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings \
"['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/']"

gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
name 'Terminal'

gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
command 'ptyxis --new-window'

gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ \
binding '<Control><Alt>t'

touch "$HOME/.config/first-login/.done"
