#!/usr/bin/env bash
# Force QUICK_SIDEWAYS_ENABLED=false on EC2 and restart backend (run via SSM or on host).
set -euo pipefail
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/nexusquant/New-idea/docker-compose.prod.yml}"

grep -v '^QUICK_SIDEWAYS_ENABLED=' "$ENV_FILE" > /tmp/nexus.env || true
printf '%s\n' "QUICK_SIDEWAYS_ENABLED=false" >> /tmp/nexus.env
mv /tmp/nexus.env "$ENV_FILE"

if [ -f "$COMPOSE_FILE" ]; then
  docker compose -f "$COMPOSE_FILE" restart backend
fi

echo "QUICK_SIDEWAYS_ENABLED=false — backend restarted"
