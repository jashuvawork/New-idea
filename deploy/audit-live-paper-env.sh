#!/usr/bin/env bash
# Audit EC2 env against Frozen October (env.october-frozen.overlay + capital overlay).
# Exit 0 when all parity keys match overlay; exit 1 and print diffs otherwise.
#
#   ENV_FILE=/opt/nexusquant/env bash deploy/audit-live-paper-env.sh
#
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RULES_OVERLAY="${RULES_OVERLAY:-${REPO_DIR}/deploy/env.october-frozen.overlay}"
CAPITAL_OVERLAY="${CAPITAL_OVERLAY:-${LIVE_OVERLAY:-${REPO_DIR}/deploy/env.paper-150k.overlay}}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"

SKIP_KEYS=(
  ENABLE_LIVE_TRADING
  PAPER_TRADING
  PAPER_SLIPPAGE_ENABLED
  PAPER_SIMULATE_BROKER_ORDERS
  SHADOW_TRADE_ALL_SIGNALS
)

should_skip() {
  local key="$1"
  for sk in "${SKIP_KEYS[@]}"; do
    if [ "$key" = "$sk" ]; then
      return 0
    fi
  done
  return 1
}

env_val() {
  grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true
}

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: env file missing: $ENV_FILE" >&2
  exit 1
fi
if [ ! -f "$RULES_OVERLAY" ]; then
  echo "ERROR: rules overlay missing: $RULES_OVERLAY" >&2
  exit 1
fi

echo "=== Frozen October env audit ==="
echo "Env: $ENV_FILE"
echo "Rules: $RULES_OVERLAY"
echo "Capital: $CAPITAL_OVERLAY"
echo ""

mismatch=0
audit_file() {
  local path="$1"
  [ -f "$path" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    key="${line%%=*}"
    want="${line#*=}"
    should_skip "$key" && continue
    got="$(env_val "$key")"
    if [ -z "$got" ]; then
      echo "MISSING $key (want $want) [$(basename "$path")]"
      mismatch=1
    elif [ "$got" != "$want" ]; then
      echo "MISMATCH $key: got=$got want=$want [$(basename "$path")]"
      mismatch=1
    fi
  done < "$path"
}
audit_file "$RULES_OVERLAY"
audit_file "$CAPITAL_OVERLAY"

# Forbidden when parity profile is active (stale live-only keys)
FORBIDDEN_WHEN_PARITY=(
  "LIVE_BEST_TRADES_ONLY_ENABLED=true"
  "WORST_DAY_BLOCKS_LIVE=true"
  "LIVE_HOLD_TO_STRUCTURAL_SL=true"
  "USE_UPSTOX_CAPITAL_FOR_SIZING=true"
)
parity_on="$(env_val LIVE_PAPER_PARITY_ENABLED)"
oct_frozen="$(env_val OCTOBER_FROZEN_PROFILE_ENABLED)"
legacy_narrow="$(env_val LEGACY_LIVE_NARROW_STACK_ENABLED)"
if [ "$oct_frozen" = "true" ] && [ "$legacy_narrow" = "true" ]; then
  echo "FORBIDDEN: LEGACY_LIVE_NARROW_STACK_ENABLED with OCTOBER_FROZEN_PROFILE_ENABLED"
  mismatch=1
fi

live_on="$(env_val ENABLE_LIVE_TRADING)"
expect_live="${EXPECT_LIVE:-false}"
if [ "$expect_live" = "true" ] || [ "$live_on" = "true" ]; then
  if [ "$oct_frozen" != "true" ]; then
    echo "MISSING OCTOBER_FROZEN_PROFILE_ENABLED=true (required for armed live)"
    mismatch=1
  fi
  if [ "$parity_on" != "true" ] && [ "$(env_val LIVE_TRADE_SELECTION_PARITY_WITH_PAPER)" != "true" ]; then
    echo "MISSING parity keys (LIVE_PAPER_PARITY_ENABLED or LIVE_TRADE_SELECTION_PARITY_WITH_PAPER) for live"
    mismatch=1
  fi
fi

if [ "$parity_on" = "true" ] || [ "$(env_val LIVE_TRADE_SELECTION_PARITY_WITH_PAPER)" = "true" ]; then
  for spec in "${FORBIDDEN_WHEN_PARITY[@]}"; do
    fk="${spec%%=*}"
    fv="${spec#*=}"
    got="$(env_val "$fk")"
    if [ "$got" = "$fv" ]; then
      echo "FORBIDDEN (parity on): $fk=$got"
      mismatch=1
    fi
  done
fi

if [ "$mismatch" -eq 0 ]; then
  echo "OK — env matches Frozen October overlays (execution mode not checked)."
  exit 0
fi
echo ""
echo "Fix: sudo ENV_FILE=$ENV_FILE bash $REPO_DIR/deploy/apply-live-paper-parity-env.sh"
echo "     sudo docker compose -f docker-compose.prod.yml up -d --force-recreate backend"
exit 1
