#!/usr/bin/env bash
set -euo pipefail

state_dir=/run/coreos-installer

detect_dest() {
    local dev smallest
    smallest=$(lsblk -dn -o NAME,SIZE,TYPE,TRAN,RM | awk '$3 == "disk" && $4 != "usb" && $5 == 0 {print "/dev/" $1, $2}' | sort -h -k2,2 | head -n1 | awk '{print $1}')
    if [[ -b "$smallest" ]]; then
        echo "$smallest"
        return 0
    fi
    echo "error: unable to determine installation device" >&2
    return 1
}

main() {
    dest="$(detect_dest)"
    echo "$dest"
    mkdir -p "$state_dir" 2>/dev/null || true
    if [[ -d "$state_dir" ]]; then
        printf '%s\n' "$dest" > "$state_dir/dest-device"
    fi
    mkdir -p /etc/coreos/installer.d 2>/dev/null
    if [[ -d "/etc/coreos/installer.d" ]]
    then cat > /etc/coreos/installer.d/10-dest.yaml <<EOF
dest-device: $dest
EOF
    fi
}

main "$@"
