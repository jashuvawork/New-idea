#!/usr/bin/env bash
# Restart backend if local health check fails (run from cron on EC2).
set -euo pipefail

COMPOSE="${COMPOSE_FILE:-/opt/nexusquant/New-idea/docker-compose.prod.yml}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
LOG="${LOG_FILE:-/var/log/nexusquant-health-watchdog.log}"

ts() { date -Iseconds; }

if curl -sf --max-time 8 "$HEALTH_URL" >/dev/null 2>&1; then
  exit 0
fi

echo "$(ts) health failed — restarting backend" >> "$LOG"
cd "$(dirname "$COMPOSE")"
docker compose -f "$COMPOSE" restart backend >> "$LOG" 2>&1 || true
sleep 8
if curl -sf --max-time 8 "$HEALTH_URL" >/dev/null 2>&1; then
  echo "$(ts) backend healthy after restart" >> "$LOG"
else
  echo "$(ts) backend still unhealthy — force-recreate" >> "$LOG"
  docker compose -f "$COMPOSE" up -d --force-recreate backend >> "$LOG" 2>&1 || true
fi
