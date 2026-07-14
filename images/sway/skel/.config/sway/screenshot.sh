#!/usr/bin/env bash
set -euo pipefail

picture_dir="$(xdg-user-dir PICTURES 2>/dev/null || true)"
if [[ -z "$picture_dir" || "$picture_dir" == "$HOME" ]]; then
  picture_dir="$HOME/Pictures"
fi

mkdir -p "$picture_dir"
file="$picture_dir/screenshot-$(date +%Y%m%d-%H%M%S).png"

case "${1:-screen}" in
  area)
    grim -g "$(slurp)" "$file"
    ;;
  screen)
    grim "$file"
    ;;
  *)
    echo "Usage: $0 [screen|area]" >&2
    exit 2
    ;;
esac

wl-copy < "$file"
notify-send "Screenshot saved" "$file"
