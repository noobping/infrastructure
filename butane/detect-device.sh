#!/usr/bin/env bash
set -euo pipefail

dest=$(lsblk -bdnpo NAME,SIZE,TYPE,TRAN,RM \
  | awk '$3 == "disk" && $4 != "usb" && $5 == 0 { print $1, $2 }' \
  | sort -nk2 | awk 'NR == 1 { print $1 }')
[[ -b $dest ]] || { echo 'No non-removable installation disk found' >&2; exit 1; }

install -d /etc/coreos/installer.d
printf 'dest-device: %s\n' "$dest" > /etc/coreos/installer.d/10-dest.yaml
