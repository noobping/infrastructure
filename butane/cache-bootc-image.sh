#!/usr/bin/env bash
set -euo pipefail

archive_dir=/run/media/iso/bootc
target=/mnt/bootc-target
state_dest=/run/coreos-installer/dest-device

detect_dest() {
    local smallest
    smallest=$(lsblk -dn -o NAME,SIZE,TYPE,TRAN,RM | awk '$3 == "disk" && $4 != "usb" && $5 == 0 {print "/dev/" $1, $2}' | sort -h -k2,2 | head -n1 | awk '{print $1}')
    if [[ -b "$smallest" ]]; then
        echo "$smallest"
        return 0
    fi
    return 1
}

resolve_dest() {
    local dest

    if [[ -f "$state_dest" ]]; then
        dest="$(awk 'NF { print; exit }' "$state_dest")"
        if [[ -n "$dest" && -b "$dest" ]]; then
            echo "$dest"
            return 0
        fi
    fi

    dest="$(awk '$1 == "dest-device:" { print $2; exit }' /etc/coreos/installer.d/*.yaml 2>/dev/null || true)"
    if [[ -n "$dest" && -b "$dest" ]]; then
        echo "$dest"
        return 0
    fi

    detect_dest
}

resolve_var_root() {
    local stateroot

    if [[ -e "$target/var" ]]; then
        echo "$target/var"
        return 0
    fi

    stateroot="$(find "$target/ostree/deploy" -mindepth 1 -maxdepth 1 -type d -print -quit)"
    if [[ -n "$stateroot" ]]; then
        echo "$stateroot/var"
        return 0
    fi

    return 1
}

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
digest_src="${archive}.sha256"
profile="$(basename "$archive" .ociarchive)"
dest="$(resolve_dest || true)"

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
mount -o rw "$root_part" "$target"
trap 'umount "$target"' EXIT

var_root="$(resolve_var_root || true)"
if [[ -z "$var_root" ]]; then
    echo "Unable to determine writable /var path in installed system" >&2
    exit 1
fi

if [[ -f "$digest_src" ]]; then
    expected="$(awk 'NR == 1 { print $1; exit }' "$digest_src")"
    actual="$(sha256sum "$archive" | awk '{ print $1 }')"

    if [[ -z "$expected" || "$actual" != "$expected" ]]; then
        echo "Embedded bootc image digest mismatch for $profile" >&2
        exit 1
    fi
else
    echo "No embedded bootc image digest found for $profile; offline fallback will be unavailable" >&2
fi

dest_dir="$var_root/lib/bootc-images"
install -d -m 0755 "$dest_dir"
install -m 0644 "$archive" "$dest_dir/${profile}.ociarchive"
if [[ -f "$digest_src" ]]; then
    install -m 0644 "$digest_src" "$dest_dir/${profile}.ociarchive.sha256"
fi
sync

echo "Cached embedded bootc image for $profile in installed system"
