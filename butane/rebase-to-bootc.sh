#!/usr/bin/env bash
set -euo pipefail

if (( $# < 1 || $# > 2 )); then
    echo "Usage: $0 IMAGE_NAME_OR_REF [OCI_ARCHIVE]" >&2
    exit 2
fi

image_ref="$1"
archive="${2:-}"

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
        namespace="${BOOTC_IMAGE_NAMESPACE}"
    elif [[ -f /etc/bootc-image-namespace ]]; then
        namespace="$(awk 'NF { print; exit }' /etc/bootc-image-namespace)"
    fi

    if [[ -z "$namespace" ]]; then
        echo "No bootc image namespace is configured for short image name: $input" >&2
        exit 1
    fi

    printf '%s/%s\n' "${namespace%/}" "$input"
}

image_ref="$(resolve_image_ref "$image_ref")"
remote_ref="ostree-image-signed:docker://${image_ref}"

echo "Trying remote bootc image: $remote_ref"
if rpm-ostree rebase "$remote_ref"; then
    exit 0
fi

if [[ -z "$archive" || ! -f "$archive" ]]; then
    echo "Remote rebase failed and no local archive is available" >&2
    exit 1
fi

digest_file="${archive}.sha256"
if [[ ! -f "$digest_file" ]]; then
    echo "Remote rebase failed and no trusted digest is available for $archive" >&2
    exit 1
fi

expected="$(awk 'NR == 1 { print $1; exit }' "$digest_file")"
actual="$(sha256sum "$archive" | awk '{ print $1 }')"

if [[ -z "$expected" || "$actual" != "$expected" ]]; then
    echo "Embedded bootc image digest verification failed for $archive" >&2
    exit 1
fi

archive_ref="ostree-unverified-image:oci-archive:${archive}"
echo "Remote rebase failed; using digest-verified embedded bootc image: $archive_ref"

mount -o remount,rw /sysroot 2>/dev/null || true

if ostree container image deploy \
    --sysroot=/ \
    --stateroot=fedora-coreos \
    --imgref="$archive_ref" \
    --target-imgref="$remote_ref"; then
    exit 0
fi

echo "Falling back to rpm-ostree local archive rebase"
rpm-ostree rebase "$archive_ref"
