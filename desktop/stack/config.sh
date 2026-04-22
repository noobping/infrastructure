#!/usr/bin/env bash
set -euo pipefail

FORM_OUTPUT="$(
  zenity --forms \
    --title="Configure TransIP STACK" \
    --text="Enter your STACK settings.\nIf 2FA is enabled, use a STACK token instead of your normal password." \
    --separator="|" \
    --add-entry="STACK URL" \
    --add-entry="Username" \
    --add-password="Password or token"
)" || exit 0

IFS='|' read -r STACK_URL STACK_USER STACK_SECRET <<< "${FORM_OUTPUT}"

if [[ -z "${STACK_URL}" || -z "${STACK_USER}" || -z "${STACK_SECRET}" ]]; then
  zenity --error --title="Missing information" \
    --text="All fields are required."
  exit 1
fi

# Normalize the URL a bit.
STACK_URL="${STACK_URL%/}"
if [[ "${STACK_URL}" != http://* && "${STACK_URL}" != https://* ]]; then
  STACK_URL="https://${STACK_URL}"
fi

# Send the secret via stdin, not argv.
if printf '%s' "${STACK_SECRET}" | pkexec /usr/libexec/stack-config-helper "${STACK_URL}" "${STACK_USER}"; then
  zenity --info --title="STACK configured" \
    --text="The STACK connection was saved successfully."
else
  zenity --error --title="Configuration failed" \
    --text="Could not save the STACK configuration."
  exit 1
fi