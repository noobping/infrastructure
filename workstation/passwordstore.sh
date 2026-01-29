#!/usr/bin/env bash
set -euo pipefail

repo="noobping/PasswordStore"
api="https://api.github.com/repos/${repo}/releases/latest"
out="${1:-/etc/skel/passwordstore.AppImage}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing dependency: $1" >&2
    exit 1
  }
}

need_cmd curl
need_cmd jq
need_cmd file

arch="$(uname -m)"

case "$arch" in
  x86_64)  asset_arch_re="x86_64" ;;
  aarch64) asset_arch_re="aarch64|arm64" ;;
  armv7l)  asset_arch_re="armv7|armhf" ;;
  *)       asset_arch_re="$arch" ;;
esac

echo "Repo:  $repo"
echo "Arch:  $arch"
echo "Output: $out"
echo

url="$(
  curl -fsSL "$api" \
  | jq -r --arg re "(${asset_arch_re}).*\\.AppImage$" \
      '.assets[] | select(.browser_download_url | test($re)) | .browser_download_url' \
  | head -n1
)"

if [[ -z "${url:-}" || "$url" == "null" ]]; then
  url="$(
    curl -fsSL "$api" \
    | jq -r '.assets[] | select(.browser_download_url | test("\\.AppImage$")) | .browser_download_url' \
    | head -n1
  )"
fi

if [[ -z "${url:-}" || "$url" == "null" ]]; then
  echo "ERROR: No .AppImage asset found in latest release." >&2
  echo "Assets were:" >&2
  curl -fsSL "$api" | jq -r '.assets[].browser_download_url' >&2
  exit 1
fi

echo "Downloading: $url"
tmp="$(mktemp)"
cleanup() { rm -f "$tmp"; }
trap cleanup EXIT

curl -fL --retry 5 --retry-all-errors -o "$tmp" "$url"

chmod 0755 "$tmp"

echo "Downloaded file type:"
file "$tmp"

# Validate it's an ELF binary (AppImages are ELF executables)
if ! file "$tmp" | grep -q 'ELF'; then
  echo "ERROR: Download is not an ELF binary (likely HTML/JSON/checksum or wrong asset)." >&2
  echo "First 200 bytes (printable):" >&2
  head -c 200 "$tmp" | sed 's/[^[:print:]\t]/./g' >&2
  exit 1
fi

mkdir -p "$(dirname "$out")"
mv -f "$tmp" "$out"
trap - EXIT

echo
echo "OK: Saved AppImage to: $out"
