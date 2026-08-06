#!/usr/bin/env bash
# Local EC2 watchdog: restart backend when /health is unreachable or too slow.
# Treats a hung event loop (health never answers) the same as a dead container.
#
# Aug6: in-process loop watchdog (backend) exits a frozen uvicorn so Docker
# restarts it; this host cron is the outer safety net if that fails.
set +e
set -u

# Cron often has a minimal PATH — docker/compose must resolve.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

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

DOCKER_BIN="$(command -v docker || true)"
if [[ -z "${DOCKER_BIN}" ]]; then
  for candidate in /usr/bin/docker /usr/local/bin/docker; do
    if [[ -x "$candidate" ]]; then
      DOCKER_BIN="$candidate"
      break
    fi
  done
fi

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$STATE_FILE")" 2>/dev/null || true
if ! touch "$LOG_FILE" 2>/dev/null; then
  LOG_FILE="/tmp/health-watchdog.log"
  STATE_FILE="/tmp/health-watchdog.state"
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
fi

FAILS=0
if [[ -f "$STATE_FILE" ]]; then
  FAILS="$(tr -dc '0-9' <"$STATE_FILE" || true)"
  FAILS="${FAILS:-0}"
fi

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

log() {
  echo "$(ts) $*" >>"$LOG_FILE" 2>/dev/null || echo "$(ts) $*" >&2
}

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

backend_cid() {
  if [[ -z "${DOCKER_BIN}" ]]; then
    return 1
  fi
  "$DOCKER_BIN" ps --format '{{.ID}} {{.Ports}}' \
    | awk '/0\.0\.0\.0:8000|->8000\/tcp/ {print $1; exit}'
}

restart_backend() {
  local compose_file="$1"
  local compose_dir
  compose_dir="$(dirname "$compose_file")"
  log "using_compose=${compose_file} docker=${DOCKER_BIN:-missing}"
  if [[ -n "${DOCKER_BIN}" ]]; then
    (
      cd "$compose_dir"
      "$DOCKER_BIN" compose -f "$compose_file" restart backend
    ) >>"$LOG_FILE" 2>&1 && return 0
  fi

  # Fallback: restart whatever container publishes :8000
  local cid
  cid="$(backend_cid || true)"
  if [[ -n "${cid:-}" ]]; then
    log "compose_restart_failed docker_restart cid=${cid}"
    "$DOCKER_BIN" restart "$cid" >>"$LOG_FILE" 2>&1
    return $?
  fi
  return 1
}

force_recreate_backend() {
  local compose_file="$1"
  local compose_dir
  compose_dir="$(dirname "$compose_file")"
  if [[ -z "${DOCKER_BIN}" ]]; then
    return 1
  fi
  (
    cd "$compose_dir"
    "$DOCKER_BIN" compose -f "$compose_file" up -d --force-recreate --no-deps backend
  ) >>"$LOG_FILE" 2>&1 || true
}

kill_backend_container() {
  local cid
  cid="$(backend_cid || true)"
  if [[ -n "${cid:-}" && -n "${DOCKER_BIN}" ]]; then
    log "docker_kill cid=${cid}"
    "$DOCKER_BIN" kill "$cid" >>"$LOG_FILE" 2>&1 || true
    "$DOCKER_BIN" start "$cid" >>"$LOG_FILE" 2>&1 || true
    return 0
  fi
  return 1
}

probe_ok=0
for attempt in 1 2; do
  code="$(curl -sS -o /dev/null -w "%{http_code}" \
    --connect-timeout 2 --max-time "$MAX_HEALTH_SECS" \
    "$HEALTH_URL" 2>/dev/null || echo "000")"
  # curl failures can append "000" after a partial code — take last 3 digits
  code="${code: -3}"
  if [[ "$code" == "200" ]]; then
    probe_ok=1
    break
  fi
  sleep 1
done

if [[ "$probe_ok" -eq 1 ]]; then
  echo 0 >"$STATE_FILE" 2>/dev/null || true
  exit 0
fi

FAILS=$((FAILS + 1))
echo "$FAILS" >"$STATE_FILE" 2>/dev/null || true
log "health_fail count=${FAILS} url=${HEALTH_URL} max_secs=${MAX_HEALTH_SECS} path=${PATH}"

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
  log "cooldown_skip secs_left=$((COOLDOWN_SECS - (NOW_EPOCH - LAST_RESTART)))"
  exit 0
fi

COMPOSE_FILE_RESOLVED="$(resolve_compose || true)"
if [[ -z "${COMPOSE_FILE_RESOLVED:-}" ]]; then
  log "no_compose_file_found tried=${COMPOSE_CANDIDATES[*]}"
  if kill_backend_container; then
    echo "$NOW_EPOCH" >"${STATE_FILE}.last_restart" 2>/dev/null || true
    echo 0 >"$STATE_FILE" 2>/dev/null || true
    exit 0
  fi
  log "restart_failed no_compose_no_container"
  exit 1
fi

log "restarting backend (health unreachable or >${MAX_HEALTH_SECS}s)"
if restart_backend "$COMPOSE_FILE_RESOLVED"; then
  echo "$NOW_EPOCH" >"${STATE_FILE}.last_restart" 2>/dev/null || true
  sleep 8
  code2="$(curl -sS -o /dev/null -w "%{http_code}" \
    --connect-timeout 2 --max-time "$MAX_HEALTH_SECS" \
    "$HEALTH_URL" 2>/dev/null || echo "000")"
  code2="${code2: -3}"
  if [[ "$code2" != "200" ]]; then
    log "restart_insufficient force_recreate"
    force_recreate_backend "$COMPOSE_FILE_RESOLVED"
    sleep 8
    code3="$(curl -sS -o /dev/null -w "%{http_code}" \
      --connect-timeout 2 --max-time "$MAX_HEALTH_SECS" \
      "$HEALTH_URL" 2>/dev/null || echo "000")"
    code3="${code3: -3}"
    if [[ "$code3" != "200" ]]; then
      log "force_recreate_insufficient docker_kill"
      kill_backend_container || true
    fi
  fi
  echo 0 >"$STATE_FILE" 2>/dev/null || true
  log "recovery_attempted"
  exit 0
fi

log "restart_failed trying_kill"
if kill_backend_container; then
  echo "$NOW_EPOCH" >"${STATE_FILE}.last_restart" 2>/dev/null || true
  echo 0 >"$STATE_FILE" 2>/dev/null || true
  exit 0
fi

log "restart_failed"
exit 1
