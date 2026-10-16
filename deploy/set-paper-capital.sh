#!/usr/bin/env bash
# Set paper trading capital (default ₹2L) on EC2 — env + runtime API + backend restart.
#
# Usage (on EC2 as root):
#   sudo bash deploy/set-paper-capital.sh
#   PAPER_CAPITAL_INR=200000 sudo bash deploy/set-paper-capital.sh
#
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/nexusquant/New-idea}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PAPER_CAPITAL_INR="${PAPER_CAPITAL_INR:-200000}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
CAPITAL_URL="${CAPITAL_URL:-http://127.0.0.1:8000/api/auto-trader/capital}"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root (sudo bash deploy/set-paper-capital.sh)" >&2
  exit 1
fi

_set_env_key() {
  local key="$1"
  local val="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
  echo "  ${key}=${val}"
}

echo "=== Set paper capital to ₹${PAPER_CAPITAL_INR} $(date -Iseconds) ==="
mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"
_set_env_key FALLBACK_CAPITAL_INR "$PAPER_CAPITAL_INR"
_set_env_key MAX_SIZING_CAPITAL_INR "$PAPER_CAPITAL_INR"

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

echo "Setting runtime capital to ₹${PAPER_CAPITAL_INR}..."
curl -sf -X POST "$CAPITAL_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"allocatedInr\": ${PAPER_CAPITAL_INR}}" || echo "WARN: capital API failed"

echo "Done."
