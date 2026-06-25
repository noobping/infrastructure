#!/usr/bin/env bash
set -euo pipefail

state_dir=/run/coreos-installer
min_size_bytes=${INSTALL_MIN_BYTES:-34359738368}

print_disks() {
    lsblk -dn -o NAME,SIZE,TYPE,TRAN,RM,RO,MODEL >&2 || true
}

detect_dest() {
    local smallest

    if [[ -n "${INSTALL_DEST_DEVICE:-}" ]]; then
        if [[ -b "$INSTALL_DEST_DEVICE" ]]; then
            echo "$INSTALL_DEST_DEVICE"
            return 0
        fi
        echo "error: INSTALL_DEST_DEVICE is not a block device: $INSTALL_DEST_DEVICE" >&2
        return 1
    fi

    smallest=$(
        lsblk -bdn -o NAME,SIZE,TYPE,TRAN,RM,RO \
        | awk -v min_size_bytes="$min_size_bytes" '
            $3 == "disk" && $4 != "usb" && $5 == 0 && $6 == 0 && $2 >= min_size_bytes {
                print "/dev/" $1, $2
            }
        ' \
        | sort -n -k2,2 \
        | head -n1 \
        | awk '{print $1}'
    )

    if [[ -b "$smallest" ]]; then
        echo "$smallest"
        return 0
    fi

    echo "error: unable to determine installation device" >&2
    echo "error: no non-USB, non-removable, writable disk >= ${min_size_bytes} bytes was found" >&2
    echo "error: set INSTALL_DEST_DEVICE=/dev/… to override detection" >&2
    print_disks
    return 1
}

main() {
    local dest

    dest=$(detect_dest)
    echo "$dest"
    mkdir -p "$state_dir" 2>/dev/null || true
    if [[ -d "$state_dir" ]]; then
        printf '%s\n' "$dest" > "$state_dir/dest-device"
    fi
    mkdir -p /etc/coreos/installer.d 2>/dev/null
    if [[ -d "/etc/coreos/installer.d" ]]; then
        cat > /etc/coreos/installer.d/10-dest.yaml <<EOF_CONFIG
dest-device: $dest
EOF_CONFIG
    fi
}

main "$@"
