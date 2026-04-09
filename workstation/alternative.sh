#!/usr/bin/env bash
set -euo pipefail

ROOT_HELPER="/usr/libexec/alternative-root"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
LOG_FILE="$LOG_DIR/alternative.log"

log() {
  printf '[alternative] %s\n' "$*"
}

notify_user() {
  local urgency="$1"
  local title="$2"
  local body="$3"

  if command -v notify-send >/dev/null 2>&1; then
    notify-send -u "$urgency" -a "Alternative DE" "$title" "$body" || true
  fi
}

append_run_log() {
  local run_log="$1"

  mkdir -p "$LOG_DIR"
  touch "$LOG_FILE"
  cat "$run_log" >>"$LOG_FILE"
}

summarize_failure() {
  local run_log="$1"
  local message

  message="$(sed -n 's/^\[alternative\] ERROR: //p' "$run_log" | tail -n 1)"

  if [[ -z "$message" ]]; then
    message="$(tail -n 1 "$run_log" | tr -d '\r' || true)"
  fi

  if [[ -z "$message" ]]; then
    message="Authentication was denied or the rebase failed. See $LOG_FILE."
  fi

  printf '%s\n' "$message"
}

main() {
  local run_log
  local status
  local message

  if [[ "${EUID}" -eq 0 ]]; then
    exec "$ROOT_HELPER" "$@"
  fi

  mkdir -p "$LOG_DIR"
  run_log="$(mktemp "$LOG_DIR/alternative-run.XXXXXX.log")"

  log "Starting alternative rebase helper"
  notify_user normal "Alternative DE" "Authentication may be required. Starting the rebase to the alternative base."

  if pkexec "$ROOT_HELPER" >"$run_log" 2>&1; then
    append_run_log "$run_log"
    rm -f -- "$run_log"
    log "Alternative rebase finished successfully"
    notify_user normal "Alternative DE" "Rebase complete. Reboot to boot into the new deployment."
    return 0
  fi

  status=$?
  append_run_log "$run_log"
  message="$(summarize_failure "$run_log")"
  rm -f -- "$run_log"
  log "Alternative rebase failed: $message"
  notify_user critical "Alternative DE failed" "$message"
  return "$status"
}

main "$@"
