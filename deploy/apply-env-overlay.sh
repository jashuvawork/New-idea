#!/usr/bin/env bash
# Merge key=value overlay onto an env file (overwrites existing keys).
#
# Usage:
#   bash deploy/apply-env-overlay.sh deploy/env.live-10k.overlay
#   ENV_FILE=/opt/nexusquant/env sudo bash deploy/apply-env-overlay.sh deploy/env.live-10k.overlay
#
set -euo pipefail

OVERLAY="${1:-}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"

if [ -z "$OVERLAY" ] || [ ! -f "$OVERLAY" ]; then
  echo "Usage: $0 <overlay-file>" >&2
  exit 1
fi

mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"

tmp="$(mktemp)"
cp "$ENV_FILE" "$tmp"

while IFS= read -r line || [ -n "$line" ]; do
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line// }" ]] && continue
  key="${line%%=*}"
  val="${line#*=}"
  if grep -q "^${key}=" "$tmp" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$tmp"
  else
    echo "${key}=${val}" >> "$tmp"
  fi
  echo "  ${key}=${val}"
done < "$OVERLAY"

mv "$tmp" "$ENV_FILE"
echo "Applied overlay $(basename "$OVERLAY") → $ENV_FILE"
