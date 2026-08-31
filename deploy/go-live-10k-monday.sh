#!/usr/bin/env bash
# Prepare or arm ₹10k live trading on EC2.
#
# Run ON the EC2 instance (as root):
#   # Step 1 — before Monday: apply capital/risk overlay (still paper)
#   sudo bash deploy/go-live-10k-monday.sh --prepare
#
#   # Step 2 — Monday before 9:15 IST: flip live execution + restart
#   sudo bash deploy/go-live-10k-monday.sh --arm-live
#
#   # After session / when done with live: back to paper
#   sudo bash deploy/go-live-10k-monday.sh --paper
#
# Options:
#   --prepare     Apply env.live-10k.overlay (capital ₹10k, scaled risk; paper mode)
#   --arm-live    Apply overlay + ENABLE_LIVE_TRADING=true, PAPER_TRADING=false, restart backend
#   --paper       Stop auto-trader, flip back to paper mode, restart backend, resume auto-trader
#   --dry-run     Print actions without writing env or restarting
#   ENV_FILE=     Override env path (default /opt/nexusquant/env)
#   REPO_DIR=     Override repo path (default /opt/nexusquant/New-idea)
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
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
OVERLAY="${REPO_DIR}/deploy/env.live-10k.overlay"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
READINESS_URL="${READINESS_URL:-http://127.0.0.1:8000/api/deployment/readiness}"
CAPITAL_URL="${CAPITAL_URL:-http://127.0.0.1:8000/api/auto-trader/capital}"

MODE=""
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --prepare) MODE=prepare ;;
    --arm-live) MODE=arm-live ;;
    --paper) MODE=paper ;;
    --dry-run) DRY_RUN=1 ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: $0 --prepare | --arm-live | --paper [--dry-run]" >&2
      exit 1
      ;;
  esac
done

if [ -z "$MODE" ]; then
  echo "Usage: $0 --prepare | --arm-live | --paper [--dry-run]" >&2
  exit 1
fi

if [ "$(id -u)" -ne 0 ] && [ "$DRY_RUN" -eq 0 ]; then
  echo "ERROR: run as root (sudo bash deploy/go-live-10k-monday.sh ...)" >&2
  exit 1
fi

if [ ! -f "$OVERLAY" ]; then
  echo "ERROR: overlay not found at $OVERLAY" >&2
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

echo "=== NexusQuant ₹10k go-live ($MODE) $(date -Iseconds) ==="
echo "Env: $ENV_FILE | Repo: $REPO_DIR"

if [ "$MODE" != "paper" ]; then
  if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$(dirname "$ENV_FILE")"
    touch "$ENV_FILE"
    ENV_FILE="$ENV_FILE" bash "$REPO_DIR/deploy/apply-env-overlay.sh" "$OVERLAY"
  else
    echo "[dry-run] apply overlay $OVERLAY"
  fi
fi

if [ "$MODE" = "paper" ]; then
  echo "Stopping auto-trader before returning to paper mode..."
  curl -sf -X POST "http://127.0.0.1:8000/api/execution/stop" >/dev/null 2>&1 || true
  echo "Disarming live execution (paper mode)..."
  _set_env_key ENABLE_LIVE_TRADING false
  _set_env_key PAPER_TRADING true
  _set_env_key PAPER_SLIPPAGE_ENABLED true
  _set_env_key PAPER_SIMULATE_BROKER_ORDERS true
  _set_env_key SHADOW_TRADE_ALL_SIGNALS true
fi

if [ "$MODE" = "arm-live" ]; then
  echo "Stopping auto-trader and clearing paper session before live arm..."
  curl -sf -X POST "http://127.0.0.1:8000/api/execution/stop" >/dev/null 2>&1 || true
  curl -sf -X POST "http://127.0.0.1:8000/api/auto-trader/purge-logs" >/dev/null 2>&1 || true
  echo "Arming live execution..."
  _set_env_key ENABLE_LIVE_TRADING true
  _set_env_key PAPER_TRADING false
  _set_env_key PAPER_SLIPPAGE_ENABLED false
  _set_env_key PAPER_SIMULATE_BROKER_ORDERS false
  _set_env_key SHADOW_TRADE_ALL_SIGNALS false
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[dry-run] skip docker restart"
  exit 0
fi

if [ -d "$REPO_DIR" ] && command -v docker >/dev/null 2>&1; then
  cd "$REPO_DIR"
  echo "Restarting backend..."
  docker compose -f "$COMPOSE_FILE" up -d --force-recreate backend
  echo "Waiting for health..."
  for i in $(seq 1 30); do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
fi

echo "Setting runtime capital ceiling to ₹10,000..."
curl -sf -X POST "$CAPITAL_URL" \
  -H 'Content-Type: application/json' \
  -d '{"allocatedInr": 10000}' || echo "WARN: capital API failed — set manually in UI"

if [ "$MODE" = "arm-live" ]; then
  echo "Resuming auto-trader in LIVE mode..."
  curl -sf -X POST "http://127.0.0.1:8000/api/execution/resume" >/dev/null 2>&1 || true
elif [ "$MODE" = "paper" ]; then
  echo "Resuming auto-trader in PAPER mode..."
  curl -sf -X POST "http://127.0.0.1:8000/api/execution/resume" >/dev/null 2>&1 || true
fi

echo ""
echo "Readiness:"
curl -sf "$READINESS_URL" | python3 -c "
import json, sys
d = json.load(sys.stdin)
checks = d.get('checks') or {}
print('  executionMode:', d.get('executionMode'))
print('  readyForLive:', d.get('readyForLive'))
print('  milestoneRequired:', checks.get('milestoneRequired'))
print('  milestonePassed:', checks.get('milestonePassed'))
if d.get('armLiveSteps'):
    print('  remaining steps:')
    for s in d['armLiveSteps']:
        print('   -', s)
" 2>/dev/null || echo "  (readiness endpoint not ready yet)"

echo ""
if [ "$MODE" = "prepare" ]; then
  echo "Prepared — still PAPER. Before 9:15 IST Monday run:"
  echo "  sudo bash deploy/go-live-10k-monday.sh --arm-live"
  echo "Also: complete Upstox OAuth if token is stale (/api/upstox/login-url)."
elif [ "$MODE" = "paper" ]; then
  echo "Back on paper trading. To arm live again:"
  echo "  sudo bash deploy/go-live-10k-monday.sh --arm-live"
else
  echo "Live armed at ₹10k. Confirm Upstox token + readiness before session open."
fi
