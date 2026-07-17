#!/usr/bin/env bash
# Local EC2 watchdog: restart backend when /health is unreachable or too slow.
# Treats a hung event loop (health never answers) the same as a dead container.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-/opt/nexusquant/app/deploy/docker-compose.prod.yml}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
LOG_FILE="${LOG_FILE:-/opt/nexusquant/logs/health-watchdog.log}"
STATE_FILE="${STATE_FILE:-/opt/nexusquant/logs/health-watchdog.state}"
# Health must answer quickly — a hung asyncio loop often accepts TCP but never
# completes the response. Anything slower than this is treated as DOWN.
MAX_HEALTH_SECS="${MAX_HEALTH_SECS:-3}"
FAIL_THRESHOLD="${FAIL_THRESHOLD:-2}"
COOLDOWN_SECS="${COOLDOWN_SECS:-120}"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$STATE_FILE")"
FAILS=0
if [[ -f "$STATE_FILE" ]]; then
  FAILS="$(tr -dc '0-9' <"$STATE_FILE" || true)"
  FAILS="${FAILS:-0}"
fi

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

probe_ok=0
for attempt in 1 2; do
  code="$(curl -sS -o /dev/null -w "%{http_code}" \
    --connect-timeout 2 --max-time "$MAX_HEALTH_SECS" \
    "$HEALTH_URL" 2>/dev/null || echo "000")"
  if [[ "$code" == "200" ]]; then
    probe_ok=1
    break
  fi
  sleep 1
done

if [[ "$probe_ok" -eq 1 ]]; then
  echo 0 >"$STATE_FILE"
  exit 0
fi

FAILS=$((FAILS + 1))
echo "$FAILS" >"$STATE_FILE"
echo "$(ts) health_fail count=${FAILS} url=${HEALTH_URL} max_secs=${MAX_HEALTH_SECS}" >>"$LOG_FILE"

if [[ "$FAILS" -lt "$FAIL_THRESHOLD" ]]; then
  exit 0
fi

# Cooldown: avoid restart storms
NOW_EPOCH="$(date +%s)"
LAST_RESTART=0
if [[ -f "${STATE_FILE}.last_restart" ]]; then
  LAST_RESTART="$(tr -dc '0-9' <"${STATE_FILE}.last_restart" || true)"
  LAST_RESTART="${LAST_RESTART:-0}"
fi
if (( NOW_EPOCH - LAST_RESTART < COOLDOWN_SECS )); then
  echo "$(ts) cooldown_skip secs_left=$((COOLDOWN_SECS - (NOW_EPOCH - LAST_RESTART)))" >>"$LOG_FILE"
  exit 0
fi

echo "$(ts) restarting backend (health unreachable or >${MAX_HEALTH_SECS}s)" >>"$LOG_FILE"
cd /opt/nexusquant/app
if docker compose -f "$COMPOSE_FILE" restart backend >>"$LOG_FILE" 2>&1; then
  echo "$NOW_EPOCH" >"${STATE_FILE}.last_restart"
  # Give the process a moment, then verify. If still dead, force-recreate.
  sleep 8
  code2="$(curl -sS -o /dev/null -w "%{http_code}" \
    --connect-timeout 2 --max-time "$MAX_HEALTH_SECS" \
    "$HEALTH_URL" 2>/dev/null || echo "000")"
  if [[ "$code2" != "200" ]]; then
    echo "$(ts) restart_insufficient force_recreate" >>"$LOG_FILE"
    docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-deps backend >>"$LOG_FILE" 2>&1 || true
  fi
  echo 0 >"$STATE_FILE"
  echo "$(ts) recovery_attempted" >>"$LOG_FILE"
  exit 0
fi

echo "$(ts) restart_failed" >>"$LOG_FILE"
exit 1
