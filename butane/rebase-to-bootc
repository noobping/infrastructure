#!/usr/bin/env bash
set -euo pipefail

if (( $# < 1 || $# > 2 )); then
    echo "Usage: $0 IMAGE_REF [OCI_ARCHIVE]" >&2
    exit 2
fi

image_ref="$1"
archive="${2:-}"
remote_ref="ostree-image-signed:docker://${image_ref}"

echo "Trying remote bootc image: $remote_ref"
if rpm-ostree rebase "$remote_ref"; then
    exit 0
fi

if [[ -z "$archive" || ! -f "$archive" ]]; then
    echo "Remote rebase failed and no local archive is available" >&2
    exit 1
fi

archive_ref="ostree-unverified-image:oci-archive:${archive}"
echo "Remote rebase failed; using embedded bootc image: $archive_ref"

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
