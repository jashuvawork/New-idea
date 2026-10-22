#!/usr/bin/env bash
# Set today's sizing book without a pull request and without a restart.
# Writes FALLBACK_CAPITAL_INR / MAX_SIZING_CAPITAL_INR and POSTs /api/capital.
# Deploys do not overwrite those two keys, so the number survives the next release.
#
#   sudo bash deploy/set-day-capital.sh 200000
#
set -euo pipefail

CAPITAL_INR="${1:-${CAPITAL_INR:-}}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
MIN_CAPITAL_INR=10000

if ! [[ "$CAPITAL_INR" =~ ^[0-9]+$ ]] || [ "$CAPITAL_INR" -lt "$MIN_CAPITAL_INR" ]; then
  echo "Usage: $0 <capital INR ≥ ${MIN_CAPITAL_INR}>  (got '${CAPITAL_INR}')" >&2
  exit 1
fi

if [ "$(id -u)" -ne 0 ] && [ "$ENV_FILE" = "/opt/nexusquant/env" ]; then
  echo "ERROR: run as root (sudo bash deploy/set-day-capital.sh ${CAPITAL_INR})" >&2
  exit 1
fi

mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"
for key in FALLBACK_CAPITAL_INR MAX_SIZING_CAPITAL_INR; do
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${CAPITAL_INR}|" "$ENV_FILE"
  else
    echo "${key}=${CAPITAL_INR}" >> "$ENV_FILE"
  fi
  echo "  ${key}=${CAPITAL_INR}"
done

if [ "${DAY_CAPITAL_SKIP_POST:-0}" = "1" ]; then
  echo "Skipping live POST."
  exit 0
fi

echo "Applying ₹${CAPITAL_INR} to the running backend..."
curl -sf -X POST "${BASE_URL}/api/capital" \
  -H 'Content-Type: application/json' \
  -d "{\"allocatedInr\": ${CAPITAL_INR}}"
echo
