#!/usr/bin/env bash
# Start paper lab stack on the Cloud Agent desktop (NOT EC2).
# - Backend paper @ 8001 (prod snapshot mirror)
# - Optional compare loop vs EC2 live
# - Frontend dev UI @ 5173 (if not already running)
set -euo pipefail

REPO="/workspace"
BACKEND="$REPO/backend"
FRONTEND="$REPO/frontend"
TMUX="tmux -f /exec-daemon/tmux.portal.conf"

new_session() {
  local name="$1"
  local dir="$2"
  local cmd="$3"
  if $TMUX has-session -t "=$name" 2>/dev/null; then
    echo "Session $name already running"
    return 0
  fi
  $TMUX new-session -d -s "$name" -c "$dir" -- bash -lc "$cmd"
  echo "Started tmux session: $name"
}

if [ ! -f "$BACKEND/.env" ]; then
  "$BACKEND/.venv/bin/python" "$BACKEND/scripts/setup_paper_lab_env.py" --write --capital-inr 30000
fi

new_session "paper-lab-8001" "$BACKEND" "bash scripts/run_paper_lab.sh"
new_session "paper-lab-compare" "$BACKEND" \
  "$BACKEND/.venv/bin/python scripts/compare_ec2_vs_local_paper.py --interval 60"

if ! curl -sf http://127.0.0.1:5173/ >/dev/null 2>&1; then
  new_session "vite-paper-lab-ui" "$FRONTEND" \
    "VITE_API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1 --port 5173"
else
  echo "Port 5173 in use — if UI shows wrong mode, restart Vite with VITE_API_PROXY_TARGET=http://127.0.0.1:8001"
fi

sleep 6
curl -sf -X POST "http://127.0.0.1:8001/api/auto-trader/capital" \
  -H 'Content-Type: application/json' -d '{"allocatedInr": 30000}' >/dev/null || true
curl -sf -X POST "http://127.0.0.1:8001/api/execution/resume" >/dev/null || true

echo "=== Desktop paper lab ==="
echo "Paper API:  http://127.0.0.1:8001  (PAPER ₹30k, mirrors api.jashuvatrade.xyz ticks)"
echo "UI:         http://127.0.0.1:5173  (proxies /api -> 8001 — set VITE_API if needed)"
echo "Compare log: /opt/cursor/artifacts/paper-lab-compare/"
curl -sS http://127.0.0.1:8001/api/paper-lab/status | python3 -m json.tool 2>/dev/null || true