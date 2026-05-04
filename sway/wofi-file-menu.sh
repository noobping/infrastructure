#!/usr/bin/env bash
set -euo pipefail

home="${HOME%/}"

selection=$(
  {
    find "$home" -xdev \
      \( \
        -path "$home/.cache" -o \
        -path "$home/.cache/*" -o \
        -path "$home/.git" -o \
        -path "$home/.git/*" -o \
        -path "$home/.local/share/Trash" -o \
        -path "$home/.local/share/Trash/*" -o \
        -path "$home/.var/app/*/cache" -o \
        -path "$home/.var/app/*/cache/*" \
      \) -prune -o \
      \( -type f -o -type d \) -print 2>/dev/null || true
  } \
  | sed "s#^$home#~#" \
  | wofi --show=dmenu --prompt="Open file" --insensitive
)

if [[ -z "$selection" ]]; then
  exit 0
fi

path="${selection/#\~/$home}"
setsid -f xdg-open "$path" >/dev/null 2>&1
