#!/usr/bin/env bash
# Set sizing book on EC2 (live or paper): env FALLBACK/MAX_SIZING + backend restart + runtime API.
#
# Usage:
#   sudo bash deploy/set-capital-book.sh
#   CAPITAL_BOOK_INR=39000 sudo bash deploy/set-capital-book.sh
#
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/nexusquant/New-idea}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
TEMPLATE="${REPO_DIR}/deploy/env.production.template"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
CAPITAL_URL="${CAPITAL_URL:-http://127.0.0.1:8000/api/auto-trader/capital}"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root (sudo bash deploy/set-capital-book.sh)" >&2
  exit 1
fi

_template_value() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" "$TEMPLATE" 2>/dev/null | tail -1 || true)"
  [ -z "$line" ] && return 1
  printf '%s' "${line#*=}"
}

CAPITAL_BOOK_INR="${CAPITAL_BOOK_INR:-$(_template_value FALLBACK_CAPITAL_INR || echo 39000)}"

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

echo "=== Set capital book to ₹${CAPITAL_BOOK_INR} $(date -Iseconds) ==="
mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"
_set_env_key FALLBACK_CAPITAL_INR "$CAPITAL_BOOK_INR"
_set_env_key MAX_SIZING_CAPITAL_INR "$CAPITAL_BOOK_INR"

if [ -d "$REPO_DIR" ] && command -v docker >/dev/null 2>&1; then
  cd "$REPO_DIR"
  echo "Restarting backend (reload env)..."
  docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-deps backend
  for _i in $(seq 1 30); do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
fi

echo "Setting runtime capital to ₹${CAPITAL_BOOK_INR}..."
curl -sf -X POST "$CAPITAL_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"allocatedInr\": ${CAPITAL_BOOK_INR}}" || echo "WARN: capital API failed"

echo "Done."