#!/usr/bin/env bash
# Local dev: set runtime sizing book without EC2 env paths.
# Usage: ./scripts/set_daily_capital.sh 45000
set -euo pipefail

AMOUNT="${1:-${CAPITAL_BOOK_INR:-}}"
if [ -z "$AMOUNT" ] && [ -f "${BOOK_FILE:-/tmp/nexusquant/daily-capital.book}" ]; then
  AMOUNT="$(grep -E '^[0-9]+$' "${BOOK_FILE:-/tmp/nexusquant/daily-capital.book}" | head -1 || true)"
fi
if ! [[ "${AMOUNT:-}" =~ ^[0-9]+$ ]] || [ "$AMOUNT" -le 0 ]; then
  echo "Usage: CAPITAL_BOOK_INR=45000 $0" >&2
  echo "   or: $0 45000" >&2
  exit 1
fi

BASE="${API_BASE:-http://127.0.0.1:8000}"
curl -sf -X POST "${BASE}/api/auto-trader/capital" \
  -H 'Content-Type: application/json' \
  -d "{\"allocatedInr\": ${AMOUNT}}"
echo ""
curl -sf "${BASE}/api/auto-trader/capital" | python3 -m json.tool 2>/dev/null || curl -sf "${BASE}/api/auto-trader/capital"
echo ""