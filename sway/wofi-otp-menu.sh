#!/usr/bin/env bash
set -euo pipefail

# List passwords
password_store=${PASSWORD_STORE_DIR:-$HOME/.password-store}

if [[ ! -d "$password_store" ]]; then
  notify-send "Password store not found" "$password_store"
  exit 0
fi

passwords=$(find "$password_store" -iname "*.gpg" -print 2>/dev/null | sed -e "s@${password_store}/@@g" -e 's@\.gpg@@g' | wofi --show=dmenu --insensitive --prompt='One-time passwords')

# Exit if no password is selected
[[ -z "$passwords" ]] && exit 0

# Retrieve and copy password to clipboard
message=$(pass otp "$passwords" -c)
notify-send "$message"
