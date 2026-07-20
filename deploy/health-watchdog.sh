#!/usr/bin/env bash
# Local EC2 watchdog: restart backend when /health is unreachable or too slow.
# Treats a hung event loop (health never answers) the same as a dead container.
set -euo pipefail

# Production compose lives next to the git checkout — NOT /opt/nexusquant/app/...
# (Jul20 outage: wrong default path meant restarts never ran while TCP:8000 stayed open.)
REPO_DIR="${REPO_DIR:-/opt/nexusquant/New-idea}"
COMPOSE_CANDIDATES=(
  "${COMPOSE_FILE:-}"
  "${REPO_DIR}/docker-compose.prod.yml"
  "/opt/nexusquant/New-idea/docker-compose.prod.yml"
  "/opt/nexusquant/app/deploy/docker-compose.prod.yml"
)
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
LOG_FILE="${LOG_FILE:-/opt/nexusquant/logs/health-watchdog.log}"
STATE_FILE="${STATE_FILE:-/opt/nexusquant/logs/health-watchdog.state}"
# Health must answer quickly — a hung asyncio loop often accepts TCP but never
# completes the response. Anything slower than this is treated as DOWN.
MAX_HEALTH_SECS="${MAX_HEALTH_SECS:-3}"
FAIL_THRESHOLD="${FAIL_THRESHOLD:-1}"
COOLDOWN_SECS="${COOLDOWN_SECS:-90}"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$STATE_FILE")"
FAILS=0
if [[ -f "$STATE_FILE" ]]; then
  FAILS="$(tr -dc '0-9' <"$STATE_FILE" || true)"
  FAILS="${FAILS:-0}"
fi

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

resolve_compose() {
  local candidate
  for candidate in "${COMPOSE_CANDIDATES[@]}"; do
    [[ -z "$candidate" ]] && continue
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

restart_backend() {
  local compose_file="$1"
  local compose_dir
  compose_dir="$(dirname "$compose_file")"
  echo "$(ts) using_compose=${compose_file}" >>"$LOG_FILE"
  (
    cd "$compose_dir"
    docker compose -f "$compose_file" restart backend
  ) >>"$LOG_FILE" 2>&1 && return 0

  # Fallback: restart whatever container publishes :8000
  local cid
  cid="$(docker ps --format '{{.ID}} {{.Ports}}' | awk '/0\.0\.0\.0:8000|->8000\/tcp/ {print $1; exit}')"
  if [[ -n "${cid:-}" ]]; then
    echo "$(ts) compose_restart_failed docker_restart cid=${cid}" >>"$LOG_FILE"
    docker restart "$cid" >>"$LOG_FILE" 2>&1
    return $?
  fi
  return 1
}

force_recreate_backend() {
  local compose_file="$1"
  local compose_dir
  compose_dir="$(dirname "$compose_file")"
  (
    cd "$compose_dir"
    docker compose -f "$compose_file" up -d --force-recreate --no-deps backend
  ) >>"$LOG_FILE" 2>&1 || true
}

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

COMPOSE_FILE_RESOLVED="$(resolve_compose || true)"
if [[ -z "${COMPOSE_FILE_RESOLVED:-}" ]]; then
  echo "$(ts) no_compose_file_found tried=${COMPOSE_CANDIDATES[*]}" >>"$LOG_FILE"
  # Last-resort container restart by published port
  cid="$(docker ps --format '{{.ID}} {{.Ports}}' | awk '/0\.0\.0\.0:8000|->8000\/tcp/ {print $1; exit}')"
  if [[ -n "${cid:-}" ]]; then
    echo "$(ts) restarting_by_port cid=${cid}" >>"$LOG_FILE"
    docker restart "$cid" >>"$LOG_FILE" 2>&1 || true
    echo "$NOW_EPOCH" >"${STATE_FILE}.last_restart"
    echo 0 >"$STATE_FILE"
    exit 0
  fi
  echo "$(ts) restart_failed no_compose_no_container" >>"$LOG_FILE"
  exit 1
fi

echo "$(ts) restarting backend (health unreachable or >${MAX_HEALTH_SECS}s)" >>"$LOG_FILE"
if restart_backend "$COMPOSE_FILE_RESOLVED"; then
  echo "$NOW_EPOCH" >"${STATE_FILE}.last_restart"
  sleep 8
  code2="$(curl -sS -o /dev/null -w "%{http_code}" \
    --connect-timeout 2 --max-time "$MAX_HEALTH_SECS" \
    "$HEALTH_URL" 2>/dev/null || echo "000")"
  if [[ "$code2" != "200" ]]; then
    echo "$(ts) restart_insufficient force_recreate" >>"$LOG_FILE"
    force_recreate_backend "$COMPOSE_FILE_RESOLVED"
  fi
  echo 0 >"$STATE_FILE"
  echo "$(ts) recovery_attempted" >>"$LOG_FILE"
  exit 0
fi

echo "$(ts) restart_failed" >>"$LOG_FILE"
exit 1
