#!/usr/bin/env bash
set -euo pipefail

if (( $# != 1 )); then
    echo "Usage: $0 IMAGE_NAME_OR_REF" >&2
    exit 2
fi

iso_mount="${BOOTC_ISO_MOUNT:-/run/bootc-iso}"
mounted_iso=

cleanup() {
    if [[ -n "$mounted_iso" ]]; then
        umount "$mounted_iso" 2>/dev/null || true
        rmdir "$iso_mount" 2>/dev/null || true
    fi
}

trap cleanup EXIT

resolve_image_ref() {
    local input="$1"
    local namespace=

    case "$input" in
        */*)
            printf '%s\n' "$input"
            return 0
            ;;
    esac

    if [[ -n "${BOOTC_IMAGE_NAMESPACE:-}" ]]; then
        namespace="$BOOTC_IMAGE_NAMESPACE"
    elif [[ -f /etc/bootc-image-namespace ]]; then
        namespace="$(awk 'NF { print; exit }' /etc/bootc-image-namespace)"
    fi

    if [[ -z "$namespace" ]]; then
        echo "No bootc image namespace is configured for short image name: $input" >&2
        exit 1
    fi

    printf '%s/%s\n' "${namespace%/}" "$input"
}

iso_devices() {
    {
        if command -v lsblk >/dev/null 2>&1; then
            lsblk -Ppno PATH,FSTYPE 2>/dev/null | awk -F'"' '/FSTYPE="(iso9660|udf)"/ { print $2 }'
        fi

        for dev in /dev/sr* /dev/disk/by-label/*; do
            if [[ -e "$dev" ]]; then
                readlink -f "$dev"
            fi
        done
    } | awk '!seen[$0]++'
}

find_archive() {
    local name="$1"
    local dev dir

    for dir in /bootc /run/initramfs/live/bootc /run/media/iso/bootc "$iso_mount/bootc"; do
        if [[ -f "$dir/$name" ]]; then
            archive="$dir/$name"
            return 0
        fi
    done

    command -v mount >/dev/null 2>&1 || return 1
    while IFS= read -r dev; do
        if [[ -z "$dev" || ! -b "$dev" ]]; then
            continue
        fi

        echo "Trying ISO device: $dev"
        mkdir -p "$iso_mount"
        if mount -o ro "$dev" "$iso_mount"; then
            mounted_iso=1
            if [[ -f "$iso_mount/bootc/$name" ]]; then
                archive="$iso_mount/bootc/$name"
                return 0
            fi

            echo "$name not found on $dev" >&2
            cleanup
            mounted_iso=
        fi
    done < <(iso_devices)

    return 1
}

verify_archive() {
    local archive="$1"
    local expected actual

    if [[ ! -f "${archive}.sha256" ]]; then
        echo "No trusted digest is available for $archive" >&2
        return 1
    fi

    expected="$(awk 'NR == 1 { print $1; exit }' "${archive}.sha256")"
    actual="$(sha256sum "$archive" | awk '{ print $1 }')"
    [[ -n "$expected" && "$actual" == "$expected" ]]
}

image_ref="$(resolve_image_ref "$1")"
remote_ref="ostree-image-signed:docker://${image_ref}"
archive_name="${image_ref%%@*}"
archive_name="${archive_name##*/}"
archive_name="${archive_name%%:*}.ociarchive"
archive=

echo "Trying remote bootc image: $remote_ref"
if rpm-ostree rebase "$remote_ref"; then
    exit 0
fi

if ! find_archive "$archive_name"; then
    echo "Remote rebase failed and $archive_name was not found in the ISO" >&2
    lsblk -f >&2 || true
    exit 1
fi

if ! verify_archive "$archive"; then
    echo "Embedded bootc image digest verification failed for $archive" >&2
    exit 1
fi

archive_ref="ostree-unverified-image:oci-archive:${archive}"
echo "Remote rebase failed; using ISO archive: $archive_ref"

mount -o remount,rw /sysroot 2>/dev/null || true
rpm-ostree rebase "$archive_ref"
