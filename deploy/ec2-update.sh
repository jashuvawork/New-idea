#!/usr/bin/env bash
# NexusQuant EC2 one-command update — pull latest, merge env, rebuild, verify.
#
# Run ON the EC2 instance:
#   sudo bash deploy/ec2-update.sh
#
# Or one-liner from your laptop (after merge to main):
#   ssh -i ~/.ssh/your-key.pem ec2-user@65.1.137.232 'curl -fsSL https://raw.githubusercontent.com/jashuvawork/New-idea/main/deploy/ec2-update.sh | sudo bash -s --'
#
# Options:
#   BRANCH=main          Git branch to deploy (default: main)
#   SKIP_BUILD=1         Skip docker build (restart only)
#   SKIP_ENV_MERGE=1     Do not add missing keys from env template
#   REPO_DIR=/path       Override repo location

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/nexusquant/New-idea}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
LOG_FILE="${LOG_FILE:-/var/log/nexusquant-deploy.log}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
STATUS_URL="${STATUS_URL:-http://127.0.0.1:8000/api/deployment/status}"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== NexusQuant EC2 update $(date -Iseconds) ==="
echo "Branch: $BRANCH | Repo: $REPO_DIR | Env: $ENV_FILE"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root (sudo bash deploy/ec2-update.sh)"
  exit 1
fi

# --- locate repo ---
if [ ! -d "$REPO_DIR/.git" ]; then
  if [ -d /opt/nexusquant/New-idea/.git ]; then
    REPO_DIR=/opt/nexusquant/New-idea
  elif [ -d /opt/nexusquant/.git ]; then
    REPO_DIR=/opt/nexusquant
  else
    echo "ERROR: repo not found. Set REPO_DIR or clone to /opt/nexusquant/New-idea"
    exit 1
  fi
fi

cd "$REPO_DIR"
echo "Using repo: $REPO_DIR"

# --- docker ---
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not installed"
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: docker compose plugin not available"
  exit 1
fi

# --- git pull ---
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH" || git reset --hard "origin/$BRANCH"
COMMIT_SHA="$(git rev-parse --short HEAD)"
echo "Deployed commit: $COMMIT_SHA"

# --- env file ---
mkdir -p "$(dirname "$ENV_FILE")" /opt/nexusquant/data/trades
touch "$ENV_FILE"

if [ "${SKIP_ENV_MERGE:-0}" != "1" ] && [ -f deploy/env.production.template ]; then
  echo "Merging missing env keys from deploy/env.production.template ..."
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    if ! grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
      echo "${key}=${val}" >> "$ENV_FILE"
      echo "  + ${key}"
    fi
  done < deploy/env.production.template

  # Sync operational defaults from template (overwrites stale server values on deploy)
  SYNC_ENV_KEYS=(
    SYMBOLS
    MIN_OPTION_PREMIUM_INR
    MAX_OPTION_PREMIUM_INR
    DAILY_PROFIT_STAGE_LOCKS_ENABLED
    DAILY_PROFIT_STAGE_PCTS
    AGGRESSIVE_MIN_SWING_CONFIDENCE
    DAILY_PROFIT_TARGET_INR
    UPSTOX_WS_ENABLED
    MARKET_POLL_SECONDS
    SNAPSHOT_CACHE_SECONDS
    MARKET_POLL_INTERVAL_MS
    MARKET_POLL_INTERVAL_WS_MS
    TICK_SNAPSHOT_INTERVAL_MS
    SNAPSHOT_CACHE_INTERVAL_MS
    TICK_WAKE_DEBOUNCE_MS
    TICK_SNAPSHOT_SECONDS
    MARKET_POLL_SECONDS_WS
    SSE_HEARTBEAT_SECONDS
    UPSTOX_MIN_REQUEST_INTERVAL_MS
    UPSTOX_CHAIN_CACHE_SECONDS
    UPSTOX_LTP_CACHE_SECONDS
    UPSTOX_WS_RESUBSCRIBE_SECONDS
    PAPER_LIVE_PARITY_ENABLED
    PAPER_SIMULATE_BROKER_ORDERS
    ENTRY_EARLIEST_HOUR
    ENTRY_EARLIEST_MINUTE
    OPEN_CAUTION_UNTIL_HOUR
    OPEN_CAUTION_UNTIL_MINUTE
    OPEN_CAUTION_MIN_EXPLOSION_SCORE
    OPEN_CAUTION_SCORE_BONUS
    PER_TRADE_CAPITAL_PCT
    PER_TRADE_RISK_PCT
    MAX_EXPOSURE_PCT
    EMERGENCY_STOP_INR
    EMERGENCY_STOP_SCALE_WITH_POSITION
    SCALP_STOP_POINTS
    SCALP_STOP_MIN_HOLD_SECONDS
    EXPLOSION_INITIAL_STOP_POINTS
    EXPLOSION_STOP_MIN_HOLD_SECONDS
    EXPLOSION_NO_PROGRESS_SECONDS
    AGGRESSIVE_MIN_EXPLOSION_SCORE
    EXPLOSION_CONFIRMED_MIN_SCORE
    EXPLOSION_MAX_LOTS
    EXPLOSION_TARGET_STANDARD
    EXPLOSION_TARGET_ELITE
    BULLISH_HOLD_ENABLED
    EXPLOSION_MICRO_TARGET_POINTS
    EXPLOSION_TRAIL_ARM_POINTS
    ENHANCED_VELOCITY_THRESHOLD
    ENHANCED_TQS_ENTRY
    RUNNER_ALIGNMENT_OVERRIDE_SCORE
    EXPLOSION_MIN_VELOCITY_3S
    EXPLOSION_MIN_VELOCITY_9S
    EXPLOSION_EARLY_VELOCITY_3S
    EXPLOSION_EARLY_VOLUME_SURGE
    MAX_LOTS_PER_TRADE
    EXPLOSION_REENTRY_COOLDOWN_SECONDS
    EXPLOSION_EMERGENCY_COOLDOWN_SECONDS
    SYMBOL_LOSS_COOLDOWN_SECONDS
    SYMBOL_EMERGENCY_COOLDOWN_SECONDS
    SYMBOL_STREAK_COOLDOWN_SECONDS
    REENTRY_SCORE_PENALTY_PER_LOSS
    CALIBRATION_BLOCK_MIN_LOSSES
    ENHANCED_MICRO_TARGET_POINTS
    AGGRESSIVE_MIN_TQS
    SCALP_MAX_LOTS
    RAPID_SCALP_MODE_ENABLED
    SURE_SHOT_MODE_ENABLED
    SURE_SHOT_MIN_SYMBOL_TQS
    SURE_SHOT_MIN_RANK_SCORE
    SURE_SHOT_SCALP_MIN_SCORE
    RECENT_WIN_RANK_BONUS
    MIDDAY_CHOP_BLOCK_SCALPS
    SCALP_STOP_MIN_HOLD_SECONDS
    SCALP_TRAIL_ARM_POINTS
    SCALP_TRAIL_KEEP_RATIO
    SCALP_NO_PROGRESS_SECONDS
  )
  echo "Syncing template defaults for operational keys ..."
  for key in "${SYNC_ENV_KEYS[@]}"; do
    tpl_line="$(grep -E "^${key}=" deploy/env.production.template | tail -1 || true)"
    [[ -z "$tpl_line" ]] && continue
    tpl_val="${tpl_line#*=}"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
      cur_val="$(grep -E "^${key}=" "$ENV_FILE" | tail -1 | cut -d= -f2-)"
      if [ "$cur_val" != "$tpl_val" ]; then
        sed -i "s|^${key}=.*|${key}=${tpl_val}|" "$ENV_FILE"
        echo "  ~ ${key}=${tpl_val} (was ${cur_val})"
      fi
    else
      echo "${key}=${tpl_val}" >> "$ENV_FILE"
      echo "  + ${key}=${tpl_val}"
    fi
  done
fi

# Required runtime keys (append only if missing)
ensure_env() {
  local k="$1" v="$2"
  if ! grep -q "^${k}=" "$ENV_FILE" 2>/dev/null; then
    echo "${k}=${v}" >> "$ENV_FILE"
    echo "  + ${k} (default)"
  fi
}
ensure_env REDIS_URL "redis://redis:6379/0"
ensure_env ENVIRONMENT "production"
ensure_env TRADE_STORE_DIR "/opt/nexusquant/data/trades"
ensure_env UPSTOX_REDIRECT_URI "https://www.jashuvatrade.xyz/api/upstox/callback"
ensure_env COMMIT_SHA "$COMMIT_SHA"

# Update commit sha every deploy
if grep -q "^COMMIT_SHA=" "$ENV_FILE"; then
  sed -i "s/^COMMIT_SHA=.*/COMMIT_SHA=${COMMIT_SHA}/" "$ENV_FILE"
else
  echo "COMMIT_SHA=${COMMIT_SHA}" >> "$ENV_FILE"
fi

# --- compose ---
COMPOSE_PATH="$REPO_DIR/$COMPOSE_FILE"
if [ ! -f "$COMPOSE_PATH" ]; then
  COMPOSE_PATH="$REPO_DIR/docker-compose.prod.yml"
fi
if [ ! -f "$COMPOSE_PATH" ]; then
  echo "ERROR: $COMPOSE_FILE not found in $REPO_DIR"
  exit 1
fi

export COMPOSE_PATH
echo "Compose: $COMPOSE_PATH"

if [ "${SKIP_BUILD:-0}" = "1" ]; then
  echo "Skipping build (SKIP_BUILD=1)"
  docker compose -f "$COMPOSE_PATH" up -d --remove-orphans
else
  echo "Building backend image ..."
  docker compose -f "$COMPOSE_PATH" build --pull backend
  docker compose -f "$COMPOSE_PATH" up -d --remove-orphans
fi

echo "Waiting for API health ..."
ready=0
for i in $(seq 1 30); do
  if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

if [ "$ready" -ne 1 ]; then
  echo "ERROR: API did not become healthy within 60s"
  docker compose -f "$COMPOSE_PATH" ps
  docker compose -f "$COMPOSE_PATH" logs --tail=40 backend || true
  exit 1
fi

echo ""
echo "=== Health ==="
curl -sf "$HEALTH_URL" | python3 -m json.tool 2>/dev/null || curl -sf "$HEALTH_URL"

echo ""
echo "=== Deployment status (websocket / cadence) ==="
if command -v python3 >/dev/null 2>&1; then
  curl -sf "$STATUS_URL" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('commit:', d.get('commit'))
print('upstox token:', d.get('upstox', {}).get('hasToken'))
ws = d.get('websocket', {})
print('websocket:', json.dumps(ws, indent=2))
cad = d.get('cadence', {})
print('cadence:', json.dumps(cad, indent=2))
flags = d.get('flags', {})
for k in ('paperTrading', 'dailyProfitTargetInr', 'perTradeCapitalPct', 'paperSlippageEnabled'):
    if k in flags:
        print(f'{k}:', flags[k])
" 2>/dev/null || curl -sf "$STATUS_URL"
else
  curl -sf "$STATUS_URL"
fi

echo ""
docker compose -f "$COMPOSE_PATH" ps
echo "=== Done $(date -Iseconds) — commit $COMMIT_SHA ==="
