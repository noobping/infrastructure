#!/usr/bin/env bash
set -euo pipefail

choice=$(
  {
    printf '%s\n' "Disconnect" "Rescan"
    nmcli -t -f SSID dev wifi list --rescan yes 2>/dev/null || true
  } | awk 'NF' | sort -u | wofi --show=dmenu --prompt="Wi-Fi" --insensitive
)

if [[ -z "$choice" ]]; then
  exit 0
fi

case "$choice" in
  "Disconnect")
    device="$({ nmcli -t -f DEVICE,TYPE,STATE dev 2>/dev/null || true; } | awk -F: '$2=="wifi" && $3=="connected" { print $1; exit }')"
    if [[ -n "$device" ]]; then
      nmcli dev disconnect "$device"
    fi
    exit 0
    ;;
  "Rescan")
    nmcli dev wifi rescan
    exec "$0"
    ;;
esac

if { nmcli -t -f NAME connection show 2>/dev/null || true; } | grep -Fxq "$choice"; then
  nmcli connection up id "$choice"
  exit 0
fi

password=$(wofi --show=dmenu --lines=1 --password --prompt="Password for $choice")

if [[ -z "$password" ]]; then
  exit 0
fi

nmcli dev wifi connect "$choice" password "$password"
