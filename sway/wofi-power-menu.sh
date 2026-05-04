#!/usr/bin/env bash
set -euo pipefail

confirm() {
  local prompt="$1"
  local answer
  answer="$(printf '%s\n' No Yes | wofi --show=dmenu --prompt="$prompt" --insensitive || true)"
  [[ "$answer" == "Yes" ]]
}

choice=$(
  printf '%s\n' \
    "Lock" \
    "Suspend" \
    "Logout" \
    "Reboot" \
    "Power off" \
    "Firmware setup" \
  | wofi --show=dmenu --prompt=Power --insensitive
)

case "$choice" in
  "Lock")
    swaylock -f -c 111318
    ;;
  "Suspend")
    systemctl suspend
    ;;
  "Logout")
    confirm "Log out?" && swaymsg exit
    ;;
  "Reboot")
    confirm "Reboot?" && systemctl reboot
    ;;
  "Power off")
    confirm "Power off?" && systemctl poweroff
    ;;
  "Firmware setup")
    confirm "Reboot to firmware?" && systemctl reboot --firmware-setup
    ;;
esac
