#!/usr/bin/env bash
set -euo pipefail

status="$(passwd -S "$USER" 2>/dev/null | awk '{print $2}')"
if [ "$status" = "NP" ] || [ "$status" = "L" ]; then
    echo "Set password for $USER"
    sudo passwd $USER
    sudo passwd -l root
fi

if [ -e /dev/md/raid0 ]; then
    echo "Adding TPM to raid 0"
    sudo systemd-cryptenroll --tpm2-device=auto /dev/md/raid0
fi

if [ -e /dev/md/raid1 ]; then
    echo "Adding TPM to raid 1"
    sudo systemd-cryptenroll --tpm2-device=auto /dev/md/raid1
fi
