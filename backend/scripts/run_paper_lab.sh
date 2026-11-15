#!/usr/bin/env bash
# Local paper @ ₹30k mirroring EC2 snapshot feed — port 8001 (prod API stays on 8000 path separately).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ ! -f .env ]; then
  "$ROOT/scripts/setup_paper_lab_env.py" --write --capital-inr 30000
fi
export LAB_EXPERIMENT_NOTES="${LAB_EXPERIMENT_NOTES:-}"
"$ROOT/.venv/bin/python" -c "
import json, urllib.request
u='http://127.0.0.1:8001/api/auto-trader/capital'
try:
    urllib.request.urlopen(urllib.request.Request(u, data=json.dumps({'allocatedInr':30000}).encode(), headers={'Content-Type':'application/json'}, method='POST'), timeout=3)
except Exception:
    pass
" 2>/dev/null || true
exec "$ROOT/.venv/bin/uvicorn" app.main:app --reload --port 8001