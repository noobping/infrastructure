#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <stack-url> <username>" >&2
  exit 2
fi

STACK_URL="$1"
STACK_USER="$2"

# Read secret from stdin.
IFS= read -r STACK_SECRET || true

if [[ -z "${STACK_URL}" || -z "${STACK_USER}" || -z "${STACK_SECRET}" ]]; then
  echo "missing required input" >&2
  exit 2
fi

# Keep only the base URL, then force the WebDAV path.
STACK_URL="${STACK_URL%/}"
STACK_WEBDAV_URL="${STACK_URL}/remote.php/webdav/"

# Basic sanity check.
case "${STACK_WEBDAV_URL}" in
  https://*) ;;
  *)
    echo "only https URLs are allowed" >&2
    exit 2
    ;;
esac

umask 077
tmpfile="$(mktemp /etc/rclone/rclone.conf.XXXXXX)"
trap 'rm -f "${tmpfile}"' EXIT

# Obscure for rclone config format. This is not strong secret protection,
# but it is the format rclone expects in config files.
OBSCURED_PASS="$(printf '%s' "${STACK_SECRET}" | rclone obscure)"

cat > "${tmpfile}" <<EOF
[stack]
type = webdav
url = ${STACK_WEBDAV_URL}
vendor = nextcloud
user = ${STACK_USER}
pass = ${OBSCURED_PASS}
EOF

install -o root -g root -m 0600 "${tmpfile}" /etc/rclone/rclone.conf

# Optional: restart or trigger your sync service if present.
systemctl try-restart profile-sync.service 2>/dev/null || true
systemctl try-restart profile-sync.timer 2>/dev/null || true

rm -f "${tmpfile}"
trap - EXIT