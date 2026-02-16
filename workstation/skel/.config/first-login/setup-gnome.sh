#!/usr/bin/env bash
set -e

BASE="$HOME/.config/first-login"
dconf load /org/gnome/shell/extensions/ < "$BASE/gnome-extensions-settings.dconf"
dconf load /org/gnome/shell/ < "$BASE/gnome-shell-settings.dconf"
gsettings set org.gnome.settings-daemon.plugins.media-keys terminal "['<Control><Alt>t']"
gsettings set org.gnome.settings-daemon.plugins.media-keys terminal-command 'ptyxis --new-window'
touch "$HOME/.config/first-login/.done"
