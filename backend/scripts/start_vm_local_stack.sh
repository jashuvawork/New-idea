#!/usr/bin/env bash
# Start local paper + Upstox stack on Cloud VM (port 8001). Requires env secrets on agent start.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export VM_UPSTOX_LOCAL_ENABLED="${VM_UPSTOX_LOCAL_ENABLED:-true}"
export PAPER_LAB_USE_PROD_SNAPSHOTS="${PAPER_LAB_USE_PROD_SNAPSHOTS:-true}"
export PAPER_LAB_PROD_API_BASE="${PAPER_LAB_PROD_API_BASE:-http://65.0.136.146:8000}"
export TRADE_STORE_DIR="${TRADE_STORE_DIR:-/tmp/nexusquant/vm-local-trades}"

if [[ -z "${UPSTOX_API_KEY:-}" || -z "${UPSTOX_API_SECRET:-}" ]]; then
  echo "UPSTOX_API_KEY / UPSTOX_API_SECRET not in environment."
  echo "Add them as Runtime Secrets on this Cloud Environment, then start a NEW agent run."
  echo "Until then: prod snapshot paper only (PAPER_LAB_USE_PROD_SNAPSHOTS=true)."
fi

if [[ -z "${PAPER_LAB_VM_TOKEN_SYNC_KEY:-}" ]]; then
  echo "PAPER_LAB_VM_TOKEN_SYNC_KEY missing — VM will not sync prod token until set (match EC2)."
fi

PORT="${VM_LOCAL_API_PORT:-8001}"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload