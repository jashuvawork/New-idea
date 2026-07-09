#!/usr/bin/env bash
# Force QUICK_SIDEWAYS_ENABLED=true on EC2 and restart backend (run via SSM or on host).
set -euo pipefail
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/nexusquant/New-idea/docker-compose.prod.yml}"

grep -v '^QUICK_SIDEWAYS_ENABLED=' "$ENV_FILE" > /tmp/nexus.env || true
grep -v '^RAPID_SCALP_MODE_ENABLED=' /tmp/nexus.env > /tmp/nexus.env2 || true
printf '%s\n' "QUICK_SIDEWAYS_ENABLED=true" >> /tmp/nexus.env2
printf '%s\n' "RAPID_SCALP_MODE_ENABLED=true" >> /tmp/nexus.env2
mv /tmp/nexus.env2 "$ENV_FILE"

if [ -f "$COMPOSE_FILE" ]; then
  docker compose -f "$COMPOSE_FILE" restart backend
fi

echo "QUICK_SIDEWAYS_ENABLED=true — RAPID_SCALP_MODE_ENABLED=true — backend restarted"
