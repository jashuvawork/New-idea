#!/usr/bin/env bash
# Set today's capital without re-arming (no session reset, no restart).
# Writes FALLBACK_CAPITAL_INR / MAX_SIZING_CAPITAL_INR (survives restarts and deploys) and
# POSTs /api/capital so sizing and the % risk limits re-fit immediately.
#
#   sudo bash deploy/set-day-capital.sh 120000
#
set -euo pipefail

CAPITAL_INR="${1:-${CAPITAL_INR:-}}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

if ! [[ "$CAPITAL_INR" =~ ^[0-9]+$ ]] || [ "$CAPITAL_INR" -lt 45000 ]; then
  echo "Usage: $0 <capital INR ≥ 45000>  (got '${CAPITAL_INR}')" >&2
  exit 1
fi
if ! grep -q '^CAPITAL_SCALED_RISK_LIMITS_ENABLED=true' "$ENV_FILE" 2>/dev/null; then
  echo "ERROR: $ENV_FILE has no CAPITAL_SCALED_RISK_LIMITS_ENABLED=true — arm with" >&2
  echo "  LIVE_OVERLAY=deploy/env.live-capital.overlay LIVE_CAPITAL_INR=$CAPITAL_INR \\" >&2
  echo "    sudo bash deploy/go-live-10k-monday.sh --arm-live" >&2
  exit 1
fi

for key in FALLBACK_CAPITAL_INR MAX_SIZING_CAPITAL_INR; do
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${CAPITAL_INR}|" "$ENV_FILE"
  else
    echo "${key}=${CAPITAL_INR}" >> "$ENV_FILE"
  fi
  echo "  ${key}=${CAPITAL_INR}"
done

echo "Applying ₹${CAPITAL_INR} to the running backend..."
curl -sf -X POST "${BASE_URL}/api/capital" \
  -H 'Content-Type: application/json' \
  -d "{\"allocatedInr\": ${CAPITAL_INR}}" | python3 -c "
import json, sys
d = json.load(sys.stdin).get('capitalRiskLimits') or {}
print('  book:', d.get('bookCapitalInr'))
for k, v in (d.get('limitsInr') or {}).items():
    print(f'  {k}: {v}')
"
