#!/usr/bin/env bash

# List passwords
password_store=${PASSWORD_STORE_DIR:-$HOME/.password-store}
passwords=$(find "$password_store" -iname "*.gpg" -print | sed -e "s@${password_store}/@@g" -e 's@\.gpg@@g' | wofi --show=dmenu --insensitive --prompt='Select a password')

# Exit if no password is selected
[ -z "$passwords" ] && exit 1

# Retrieve and copy password to clipboard
message=$(pass "$passwords" -c)
notify-send $message
