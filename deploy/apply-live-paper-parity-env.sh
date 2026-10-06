#!/usr/bin/env bash
# Merge deploy/env.live-200k.overlay onto ENV_FILE without flipping execution mode.
# Used on EC2 after template sync so WORST_DAY_BLOCKS_LIVE / USE_UPSTOX etc. match Oct paper.
#
#   ENV_FILE=/opt/nexusquant/env sudo bash deploy/apply-live-paper-parity-env.sh
#
set -euo pipefail

REPO_DIR="${REPO_DIR:-}"
if [ -z "$REPO_DIR" ]; then
  if [ -d /opt/nexusquant/New-idea/.git ]; then
    REPO_DIR=/opt/nexusquant/New-idea
  elif [ -d /opt/nexusquant/.git ]; then
    REPO_DIR=/opt/nexusquant
  else
    REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi
fi

OVERLAY="${LIVE_OVERLAY:-${REPO_DIR}/deploy/env.live-200k.overlay}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"

# Never overwrite live/paper execution toggles (set by go-live --arm-live / --paper).
SKIP_KEYS=(
  ENABLE_LIVE_TRADING
  PAPER_TRADING
  PAPER_SLIPPAGE_ENABLED
  PAPER_SIMULATE_BROKER_ORDERS
  SHADOW_TRADE_ALL_SIGNALS
)

if [ ! -f "$OVERLAY" ]; then
  echo "ERROR: overlay not found: $OVERLAY" >&2
  exit 1
fi

mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"

should_skip() {
  local key="$1"
  for sk in "${SKIP_KEYS[@]}"; do
    if [ "$key" = "$sk" ]; then
      return 0
    fi
  done
  return 1
}

tmp="$(mktemp)"
cp "$ENV_FILE" "$tmp"

while IFS= read -r line || [ -n "$line" ]; do
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line// }" ]] && continue
  key="${line%%=*}"
  val="${line#*=}"
  if should_skip "$key"; then
    continue
  fi
  if grep -q "^${key}=" "$tmp" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$tmp"
  else
    echo "${key}=${val}" >> "$tmp"
  fi
  echo "  ${key}=${val}"
done < "$OVERLAY"

mv "$tmp" "$ENV_FILE"
echo "Applied paper-parity keys from $(basename "$OVERLAY") → $ENV_FILE (execution mode preserved)"
