#!/usr/bin/env bash
# Merge Frozen October rules + optional capital overlay without flipping execution mode.
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

RULES_OVERLAY="${RULES_OVERLAY:-${REPO_DIR}/deploy/env.october-frozen.overlay}"
OVERLAY="${LIVE_OVERLAY:-${REPO_DIR}/deploy/env.paper-150k.overlay}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"

SKIP_KEYS=(
  ENABLE_LIVE_TRADING
  PAPER_TRADING
  PAPER_SLIPPAGE_ENABLED
  PAPER_SIMULATE_BROKER_ORDERS
  SHADOW_TRADE_ALL_SIGNALS
)

if [ ! -f "$RULES_OVERLAY" ]; then
  echo "ERROR: rules overlay not found: $RULES_OVERLAY" >&2
  exit 1
fi
if [ ! -f "$OVERLAY" ]; then
  echo "ERROR: capital overlay not found: $OVERLAY" >&2
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

merge_overlay() {
  local path="$1"
  local tmp
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
  done < "$path"
  mv "$tmp" "$ENV_FILE"
  echo "Applied $(basename "$path")"
}

merge_overlay "$RULES_OVERLAY"
merge_overlay "$OVERLAY"
echo "→ $ENV_FILE (execution mode preserved)"
