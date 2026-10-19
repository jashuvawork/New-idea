#!/usr/bin/env bash
# Flip live or paper execution without a separate live profile.
#
# Capital, loss stops, and entry gates are copied from
# deploy/env.production.template (the paper / Oct 1 book, ₹2,00,000).
# This does not apply a ₹10k overlay.
#
# Run on the EC2 instance:
#   sudo bash deploy/set-execution-mode.sh --live
#   sudo bash deploy/set-execution-mode.sh --paper
#   bash deploy/set-execution-mode.sh --live --dry-run
#
# ENV_FILE, REPO_DIR, and SKIP_RESTART override the defaults.
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
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
TEMPLATE="${REPO_DIR}/deploy/env.production.template"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
CAPITAL_URL="${CAPITAL_URL:-http://127.0.0.1:8000/api/auto-trader/capital}"

# Keys a previous ₹10k live overlay used to rewrite. Values come from the
# production template so arming live cannot shrink the book or add a grade-S bar.
PIN_KEYS=(
  FALLBACK_CAPITAL_INR
  MAX_SIZING_CAPITAL_INR
  DAILY_LOSS_STOP_INR
  EMERGENCY_STOP_ENABLED
  EMERGENCY_STOP_INR
  MAX_RISK_PER_TRADE_INR
  EXPLOSION_PER_TRADE_MAX_LOSS_INR
  EXPLOSION_EXCEPTIONAL_PER_TRADE_MAX_LOSS_INR
  SESSION_LARGE_LOSS_PAUSE_INR
  LOSS_STREAK_PAUSE_COUNT
  TOP_MOMENTS_MIN_GRADE
  LIVE_BEST_TRADES_ONLY_ENABLED
  LIVE_EARLY_FAIL_EXIT_ENABLED
  LIVE_DISABLE_SESSION_LIFT
  CHOP_LIVE_EARLY_FAIL_EXIT_ENABLED
  CHOP_LIVE_DISABLE_SESSION_LIFT
  CHOP_LIVE_HARD_BLOCK_WORST_DAY
  BEST_TRADE_BLOCK_CHOP_DEEP_CHASE_ENABLED
  DAILY_PROFIT_TARGET_INR
  FTV_ALLOCATION_MAX_POSITIONS
  FTV_ALLOCATION_MAX_SAME_SIDE
  LIVE_HOLD_TO_STRUCTURAL_SL
  LIVE_MILESTONE_REQUIRED
)

MODE=""
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --live) MODE=live ;;
    --paper) MODE=paper ;;
    --dry-run) DRY_RUN=1 ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: $0 --live | --paper [--dry-run]" >&2
      exit 1
      ;;
  esac
done

if [ -z "$MODE" ]; then
  echo "Usage: $0 --live | --paper [--dry-run]" >&2
  exit 1
fi

if [ "$(id -u)" -ne 0 ] && [ "$DRY_RUN" -eq 0 ] && [ "$ENV_FILE" = "/opt/nexusquant/env" ]; then
  echo "ERROR: run as root (sudo bash deploy/set-execution-mode.sh --${MODE})" >&2
  exit 1
fi

if [ ! -f "$TEMPLATE" ]; then
  echo "ERROR: production template not found at $TEMPLATE" >&2
  exit 1
fi

_set_env_key() {
  local key="$1"
  local val="$2"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] ${key}=${val}"
    return
  fi
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
  echo "  ${key}=${val}"
}

_template_value() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" "$TEMPLATE" | tail -1 || true)"
  if [ -z "$line" ]; then
    return 1
  fi
  printf '%s' "${line#*=}"
}

echo "=== NexusQuant execution mode ($MODE) $(date -Iseconds) ==="
echo "Env: $ENV_FILE | Repo: $REPO_DIR"

if [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  touch "$ENV_FILE"
fi

echo "Pinning paper / Oct 1 gates from the production template..."
for key in "${PIN_KEYS[@]}"; do
  val="$(_template_value "$key" || true)"
  if [ -z "$val" ]; then
    echo "  skip ${key} (not in template)"
    continue
  fi
  _set_env_key "$key" "$val"
done

if [ "$MODE" = "live" ]; then
  echo "Arming live execution on the paper book..."
  _set_env_key ENABLE_LIVE_TRADING true
  _set_env_key PAPER_TRADING false
  _set_env_key PAPER_SLIPPAGE_ENABLED false
  _set_env_key PAPER_SIMULATE_BROKER_ORDERS false
else
  echo "Returning to paper execution..."
  _set_env_key ENABLE_LIVE_TRADING false
  _set_env_key PAPER_TRADING true
  _set_env_key PAPER_SLIPPAGE_ENABLED true
  _set_env_key PAPER_SIMULATE_BROKER_ORDERS true
  _set_env_key SHADOW_TRADE_ALL_SIGNALS true
fi

if [ "$DRY_RUN" -eq 1 ] || [ "${SKIP_RESTART:-0}" = "1" ]; then
  echo "Skip backend restart."
  exit 0
fi

if [ "$MODE" = "live" ] || [ "$MODE" = "paper" ]; then
  curl -sf -X POST "http://127.0.0.1:8000/api/execution/stop" >/dev/null 2>&1 || true
fi

if [ -d "$REPO_DIR" ] && command -v docker >/dev/null 2>&1; then
  cd "$REPO_DIR"
  echo "Restarting backend..."
  docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-deps backend
  echo "Waiting for health..."
  for _i in $(seq 1 30); do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
fi

CAPITAL_INR="$(_template_value FALLBACK_CAPITAL_INR || true)"
if [ -n "$CAPITAL_INR" ]; then
  echo "Setting runtime capital ceiling to ₹${CAPITAL_INR}..."
  curl -sf -X POST "$CAPITAL_URL" \
    -H 'Content-Type: application/json' \
    -d "{\"allocatedInr\": ${CAPITAL_INR}}" || echo "WARN: capital API failed"
fi

echo "Resuming auto-trader..."
curl -sf -X POST "http://127.0.0.1:8000/api/execution/resume" >/dev/null 2>&1 || true
echo "Execution mode is ${MODE}. Book and gates stay on the production template."
