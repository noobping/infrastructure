#!/usr/bin/env bash
set -euo pipefail

echo "Set password for $USER"
sudo passwd $USER
sudo passwd -l root
sudo systemctl disable getty@tty1.service

if [ -e /dev/md/raid0 ]; then
    echo "Adding TPM to raid 0"
    sudo systemd-cryptenroll --tpm2-device=auto /dev/md/raid0
fi

if [ -e /dev/md/raid1 ]; then
    echo "Adding TPM to raid 1"
    sudo systemd-cryptenroll --tpm2-device=auto /dev/md/raid1
fi

if [ -e "/etc/sudoers.d/$USER" ]; then
    sudo sed -i 's/\bNOPASSWD:\b//g' "/etc/sudoers.d/$USER"
    sudo visudo -cf "/etc/sudoers.d/$USER"
fi
