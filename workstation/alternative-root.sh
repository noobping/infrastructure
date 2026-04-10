#!/usr/bin/env bash
set -euo pipefail

BASE_FILE="/etc/recommended/base"

log() {
  printf '[alternative] %s\n' "$*"
}

fail() {
  printf '[alternative] ERROR: %s\n' "$*" >&2
  exit 1
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "This helper must be run as root."
  fi
}

read_base_ref() {
  [[ -f "$BASE_FILE" ]] || fail "Missing $BASE_FILE"

  local ref
  ref="$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' "$BASE_FILE" | head -n 1 | xargs || true)"

  [[ -n "$ref" ]] || fail "No valid rpm-ostree ref found in $BASE_FILE"

  printf '%s\n' "$ref"
}

remove_user_state() {
  local username="$1"
  local home="$2"

  [[ -n "$home" && -d "$home" ]] || return 0

  local ext_dir="$home/.local/share/gnome-shell/extensions"
  local done_file="$home/.config/recommended.done"

  if [[ -e "$ext_dir" ]]; then
    log "Removing GNOME extensions for user '$username' at $ext_dir"
    rm -rf -- "$ext_dir"
  fi

  if [[ -e "$done_file" ]]; then
    log "Removing marker file for user '$username' at $done_file"
    rm -f -- "$done_file"
  fi

  if id -u "$username" >/dev/null 2>&1; then
    chown -R "$username":"$(id -gn "$username")" "$home/.local" "$home/.config" 2>/dev/null || true
  fi
}

process_users() {
  log "Processing regular user profiles"

  while IFS=: read -r username _ uid _ _ home shell; do
    [[ "$uid" -ge 1000 ]] || continue
    [[ "$uid" -eq 65534 ]] && continue
    [[ "$shell" == "/sbin/nologin" || "$shell" == "/usr/sbin/nologin" ]] && continue
    [[ "$shell" == "/bin/false" || "$shell" == "/usr/bin/false" ]] && continue

    remove_user_state "$username" "$home"
  done < /etc/passwd
}

main() {
  require_root

  local ref
  ref="$(read_base_ref)"

  log "Using rpm-ostree ref: $ref"

  process_users

  log "Running rpm-ostree rebase"
  rpm-ostree rebase "$ref"

  log "Done. Reboot may be required to boot into the new deployment."
}

main "$@"
