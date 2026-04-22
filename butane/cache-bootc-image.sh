#!/usr/bin/env bash
set -euo pipefail

archive_dir=/run/media/iso/bootc
target=/mnt/bootc-target

if [[ ! -d "$archive_dir" ]]; then
    echo "No embedded bootc image directory found at $archive_dir"
    exit 0
fi

shopt -s nullglob
archives=("$archive_dir"/*.ociarchive)
shopt -u nullglob

if (( ${#archives[@]} == 0 )); then
    echo "No embedded bootc image archive found in $archive_dir"
    exit 0
fi

if (( ${#archives[@]} > 1 )); then
    echo "Expected one embedded bootc image archive, found ${#archives[@]}" >&2
    exit 1
fi

archive="${archives[0]}"
profile="$(basename "$archive" .ociarchive)"
dest="$(awk '$1 == "dest-device:" { print $2; exit }' /etc/coreos/installer.d/*.yaml 2>/dev/null || true)"

if [[ -z "$dest" || ! -b "$dest" ]]; then
    echo "Unable to determine installed destination device" >&2
    exit 1
fi

udevadm settle
root_part="$(lsblk -prno PATH,PARTLABEL "$dest" | awk '$2 == "root" { print $1; exit }')"

if [[ -z "$root_part" || ! -b "$root_part" ]]; then
    echo "Unable to find root partition on $dest" >&2
    exit 1
fi

mkdir -p "$target"
mount "$root_part" "$target"
trap 'umount "$target"' EXIT

stateroot="$(find "$target/ostree/deploy" -mindepth 1 -maxdepth 1 -type d -print -quit)"
if [[ -z "$stateroot" ]]; then
    echo "Unable to find OSTree stateroot in installed system" >&2
    exit 1
fi

install -d -m 0755 "$stateroot/var/lib/bootc-images"
install -m 0644 "$archive" "$stateroot/var/lib/bootc-images/${profile}.ociarchive"
sha256sum "$archive" > "$stateroot/var/lib/bootc-images/${profile}.ociarchive.sha256"
sync

echo "Cached embedded bootc image for $profile in installed system"
