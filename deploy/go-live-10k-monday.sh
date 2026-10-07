#!/usr/bin/env bash
# Prepare or arm live trading on EC2 (default ₹2L capital / overlay).
#
# Run ON the EC2 instance (as root):
#   # Step 1 — before open: apply capital/risk overlay (still paper)
#   sudo bash deploy/go-live-10k-monday.sh --prepare
#
#   # Step 2 — before 9:15 IST: flip live execution + restart
#   sudo bash deploy/go-live-10k-monday.sh --arm-live
#
#   # After session / when done with live: back to paper
#   sudo bash deploy/go-live-10k-monday.sh --paper
#
# Options:
#   --prepare     Apply env.live-200k.overlay (default; still paper)
#   --arm-live    Apply overlay + ENABLE_LIVE_TRADING=true, PAPER_TRADING=false, restart backend
#   --paper       Stop auto-trader, flip back to paper mode, restart backend, resume auto-trader
#   --dry-run     Print actions without writing env or restarting
#   ENV_FILE=     Override env path (default /opt/nexusquant/env)
#   REPO_DIR=     Override repo path (default /opt/nexusquant/New-idea)
#   RULES_OVERLAY= Frozen October rules (default deploy/env.october-frozen.overlay)
#   LIVE_OVERLAY= Capital + execution overlay (default deploy/env.live-150k.overlay)
#   LIVE_CAPITAL_INR= Runtime capital ceiling when arming (default 150000)
#   PAPER_CAPITAL_INR= Paper capital when disarming (default 150000)
#   PAPER_OVERLAY=  Capital/risk overlay on --paper (default deploy/env.paper-150k.overlay)
#   ₹1.5L live: LIVE_OVERLAY=deploy/env.live-150k.overlay LIVE_CAPITAL_INR=150000
#   Small-cap legacy: LIVE_OVERLAY=deploy/env.live-10k.overlay LIVE_CAPITAL_INR=10000
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
RULES_OVERLAY="${RULES_OVERLAY:-${REPO_DIR}/deploy/env.october-frozen.overlay}"
OVERLAY="${LIVE_OVERLAY:-${REPO_DIR}/deploy/env.live-150k.overlay}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
STATUS_URL="${STATUS_URL:-http://127.0.0.1:8000/api/deployment/status}"
READINESS_URL="${READINESS_URL:-http://127.0.0.1:8000/api/deployment/readiness}"
CAPITAL_URL="${CAPITAL_URL:-http://127.0.0.1:8000/api/auto-trader/capital}"
PAPER_CAPITAL_INR="${PAPER_CAPITAL_INR:-150000}"
LIVE_CAPITAL_INR="${LIVE_CAPITAL_INR:-150000}"
PAPER_OVERLAY="${PAPER_OVERLAY:-${REPO_DIR}/deploy/env.paper-150k.overlay}"

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

if [ ! -f "$RULES_OVERLAY" ]; then
  echo "ERROR: rules overlay not found at $RULES_OVERLAY" >&2
  exit 1
fi
if [ "$MODE" != "paper" ] && [ ! -f "$OVERLAY" ] && [ "$MODE" = "arm-live" ]; then
  echo "ERROR: capital overlay not found at $OVERLAY" >&2
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

echo "=== NexusQuant live go-live ($MODE) capital=₹${LIVE_CAPITAL_INR} $(date -Iseconds) ==="
echo "Rules overlay: $RULES_OVERLAY"
echo "Capital overlay: $OVERLAY"
echo "Env: $ENV_FILE | Repo: $REPO_DIR"

_apply_overlay_file() {
  local path="$1"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] apply overlay $path"
    return
  fi
  ENV_FILE="$ENV_FILE" bash "$REPO_DIR/deploy/apply-env-overlay.sh" "$path"
}

if [ "$MODE" != "paper" ]; then
  if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$(dirname "$ENV_FILE")"
    touch "$ENV_FILE"
  fi
  _apply_overlay_file "$RULES_OVERLAY"
  if [ "$MODE" = "prepare" ]; then
    _apply_overlay_file "$PAPER_OVERLAY"
  elif [ -f "$OVERLAY" ]; then
    _apply_overlay_file "$OVERLAY"
  fi
fi

if [ "$MODE" = "paper" ]; then
  if [ -f "$PAPER_OVERLAY" ] && [ "$DRY_RUN" -eq 0 ]; then
    echo "Applying paper capital/risk overlay: $PAPER_OVERLAY"
    ENV_FILE="$ENV_FILE" bash "$REPO_DIR/deploy/apply-env-overlay.sh" "$PAPER_OVERLAY"
  elif [ -f "$PAPER_OVERLAY" ]; then
    echo "[dry-run] apply paper overlay $PAPER_OVERLAY"
  fi
  echo "Stopping auto-trader before returning to paper mode..."
  curl -sf -X POST "http://127.0.0.1:8000/api/execution/stop" >/dev/null 2>&1 || true
  echo "Disarming live execution (paper mode)..."
  _set_env_key ENABLE_LIVE_TRADING false
  _set_env_key PAPER_TRADING true
  _set_env_key PAPER_SLIPPAGE_ENABLED true
  _set_env_key PAPER_SIMULATE_BROKER_ORDERS true
  _set_env_key SHADOW_TRADE_ALL_SIGNALS true
  echo "Restoring paper capital to ₹${PAPER_CAPITAL_INR}..."
  _set_env_key FALLBACK_CAPITAL_INR "$PAPER_CAPITAL_INR"
  _set_env_key MAX_SIZING_CAPITAL_INR "$PAPER_CAPITAL_INR"
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

if [ "$MODE" = "arm-live" ]; then
  CAPITAL_INR="$LIVE_CAPITAL_INR"
elif [ "$MODE" = "paper" ]; then
  CAPITAL_INR="$PAPER_CAPITAL_INR"
else
  CAPITAL_INR="$PAPER_CAPITAL_INR"
fi

echo "Setting runtime capital ceiling to ₹${CAPITAL_INR}..."
curl -sf -X POST "$CAPITAL_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"allocatedInr\": ${CAPITAL_INR}}" || echo "WARN: capital API failed — set manually in UI"

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

if [ "$MODE" = "arm-live" ]; then
  echo "Deployment flags:"
  curl -sf "$STATUS_URL" | python3 -c "
import json, sys
d = json.load(sys.stdin)
f = d.get('flags') or {}
print('  commit:', d.get('commit'))
print('  enableLiveTrading:', f.get('enableLiveTrading'))
print('  paperTrading:', f.get('paperTrading'))
print('  livePaperParityEnabled:', f.get('livePaperParityEnabled'))
print('  liveBestTradesOnlyEnabled:', f.get('liveBestTradesOnlyEnabled'))
print('  fallbackCapitalInr:', f.get('fallbackCapitalInr'))
if not f.get('enableLiveTrading') or f.get('paperTrading'):
    raise SystemExit('ERROR: live arm failed — still on paper')
if f.get('livePaperParityEnabled') is not True:
    print('  WARN: livePaperParityEnabled is not true — check env.live-200k.overlay merge')
prof = f.get('livePaperProfile') or {}
print('  livePaperProfileOk:', prof.get('profileOk'))
if prof.get('profileIssues'):
    print('  profileIssues:', prof.get('profileIssues'))
if prof.get('profileOk') is not True:
    raise SystemExit('ERROR: live env is not Oct paper profile — run --prepare and restart')
" 2>/dev/null || echo "  (deployment status not ready yet)"
fi

echo ""
if [ "$MODE" = "prepare" ]; then
  echo "Prepared — still PAPER. Before 9:15 IST Monday run:"
  echo "  sudo bash deploy/go-live-10k-monday.sh --arm-live"
  echo "Also: complete Upstox OAuth if token is stale (/api/upstox/login-url)."
elif [ "$MODE" = "paper" ]; then
  echo "Back on paper trading at ₹${PAPER_CAPITAL_INR}. To arm live again:"
  echo "  sudo bash deploy/go-live-10k-monday.sh --arm-live"
else
  echo "Live armed at ₹${LIVE_CAPITAL_INR}. Confirm Upstox token + readiness before session open."
fi
