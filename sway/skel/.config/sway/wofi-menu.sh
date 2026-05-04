#!/usr/bin/env bash
set -euo pipefail

choice=$(
  printf '%s\n' \
    "Applications" \
    "Run command" \
    "Files" \
    "Windows" \
    "Wi-Fi" \
    "Passwords" \
    "One-time passwords" \
    "Clipboard" \
    "Power" \
  | wofi --show=dmenu --prompt=Menu --insensitive
)

case "$choice" in
  "Applications")
    wofi --show=drun --allow-images --prompt=Applications
    ;;
  "Run command")
    wofi --show=run --prompt=Run
    ;;
  "Files")
    "$HOME/.config/sway/wofi-file-menu.sh"
    ;;
  "Windows")
    "$HOME/.config/sway/wofi-select-window.sh"
    ;;
  "Wi-Fi")
    "$HOME/.config/sway/wofi-wifi-menu.sh"
    ;;
  "Passwords")
    "$HOME/.config/sway/wofi-pass-menu.sh"
    ;;
  "One-time passwords")
    "$HOME/.config/sway/wofi-otp-menu.sh"
    ;;
  "Clipboard")
    clipman pick -t wofi
    ;;
  "Power")
    "$HOME/.config/sway/wofi-power-menu.sh"
    ;;
esac
