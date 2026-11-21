#!/usr/bin/env bash
# Apply today's sizing book: env persistence + runtime API (optional backend restart).
#
# Morning default (no container recreate — updates /opt/nexusquant/env for next deploy + live sizing now):
#   echo 45000 | sudo tee /opt/nexusquant/daily-capital.book
#   sudo bash deploy/set-daily-capital.sh
#
# One-liner:
#   sudo CAPITAL_BOOK_INR=45000 bash deploy/set-daily-capital.sh
#   sudo bash deploy/set-daily-capital.sh 45000
#
# After a deploy when env must reload inside the container:
#   sudo RESTART_BACKEND=1 bash deploy/set-daily-capital.sh
#
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/nexusquant/New-idea}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
BOOK_FILE="${BOOK_FILE:-/opt/nexusquant/daily-capital.book}"
TEMPLATE="${REPO_DIR}/deploy/env.production.template"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
CAPITAL_URL="${CAPITAL_URL:-http://127.0.0.1:8000/api/auto-trader/capital}"
RESTART_BACKEND="${RESTART_BACKEND:-0}"

_template_value() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" "$TEMPLATE" 2>/dev/null | tail -1 || true)"
  [ -z "$line" ] && return 1
  printf '%s' "${line#*=}"
}

_read_book_file() {
  local f="$1"
  [ -f "$f" ] || return 1
  grep -E '^[0-9]+$' "$f" | head -1 || true
}

_resolve_amount() {
  if [ -n "${1:-}" ]; then
    printf '%s' "$1"
    return 0
  fi
  if [ -n "${CAPITAL_BOOK_INR:-}" ]; then
    printf '%s' "$CAPITAL_BOOK_INR"
    return 0
  fi
  # Legacy alias from set-paper-capital.sh
  if [ -n "${PAPER_CAPITAL_INR:-}" ]; then
    printf '%s' "$PAPER_CAPITAL_INR"
    return 0
  fi
  local from_file
  from_file="$(_read_book_file "$BOOK_FILE")"
  if [ -n "$from_file" ]; then
    printf '%s' "$from_file"
    return 0
  fi
  _template_value FALLBACK_CAPITAL_INR || echo "45000"
}

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

AMOUNT="$(_resolve_amount "${1:-}")"
if ! [[ "$AMOUNT" =~ ^[0-9]+$ ]] || [ "$AMOUNT" -le 0 ]; then
  echo "ERROR: capital must be a positive integer INR amount (got: ${AMOUNT})" >&2
  exit 1
fi

echo "=== Daily sizing book ₹${AMOUNT} $(date -Iseconds) ==="
echo "  book file: ${BOOK_FILE}"
echo "  env file:  ${ENV_FILE}"
echo "  restart:   ${RESTART_BACKEND}"

# Persist today's book (best-effort)
book_dir="$(dirname "$BOOK_FILE")"
if [ -d "$book_dir" ] && { [ -w "$book_dir" ] || [ "$(id -u)" -eq 0 ]; }; then
  mkdir -p "$book_dir"
  echo "$AMOUNT" >"$BOOK_FILE"
  echo "  wrote ${BOOK_FILE}"
fi

# Env keys require production path (root on EC2)
if [ "$(id -u)" -eq 0 ]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  touch "$ENV_FILE"
  _set_env_key FALLBACK_CAPITAL_INR "$AMOUNT"
  _set_env_key MAX_SIZING_CAPITAL_INR "$AMOUNT"
elif [ -w "$ENV_FILE" ] 2>/dev/null; then
  _set_env_key FALLBACK_CAPITAL_INR "$AMOUNT"
  _set_env_key MAX_SIZING_CAPITAL_INR "$AMOUNT"
else
  echo "  skip env file (not root and ${ENV_FILE} not writable)"
fi

if [ "$RESTART_BACKEND" = "1" ] && [ -d "$REPO_DIR" ] && command -v docker >/dev/null 2>&1; then
  if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: RESTART_BACKEND=1 requires root on EC2" >&2
    exit 1
  fi
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

echo "Setting runtime capital to ₹${AMOUNT}..."
if curl -sf -X POST "$CAPITAL_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"allocatedInr\": ${AMOUNT}}"; then
  echo ""
  echo "Runtime book OK. Verify: curl -s ${CAPITAL_URL} | python3 -m json.tool"
else
  echo "WARN: capital API failed (is backend up?)" >&2
  exit 1
fi

echo "Done."