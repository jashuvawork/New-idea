#!/usr/bin/env bash
# Set MCX commodity option underlyings on EC2 (merged into SYMBOLS at runtime).
# Default empty (MCX off). Example: COMMODITY_SYMBOLS=CRUDEOIL,NATURALGAS bash deploy/set-commodity-symbols.sh
set -euo pipefail
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/nexusquant/New-idea/docker-compose.prod.yml}"
COMMODITY_SYMBOLS="${COMMODITY_SYMBOLS:-}"

touch "$ENV_FILE"
if grep -q '^COMMODITY_SYMBOLS=' "$ENV_FILE"; then
  sed -i "s|^COMMODITY_SYMBOLS=.*|COMMODITY_SYMBOLS=${COMMODITY_SYMBOLS}|" "$ENV_FILE"
else
  echo "COMMODITY_SYMBOLS=${COMMODITY_SYMBOLS}" >> "$ENV_FILE"
fi

if [ -f "$COMPOSE_FILE" ]; then
  docker compose -f "$COMPOSE_FILE" restart backend
  sleep 8
  curl -sf --max-time 10 http://127.0.0.1:8000/health >/dev/null
fi

echo "COMMODITY_SYMBOLS=${COMMODITY_SYMBOLS} — backend restarted"
curl -sf --max-time 10 http://127.0.0.1:8000/api/deployment/status | head -c 400 || true
echo