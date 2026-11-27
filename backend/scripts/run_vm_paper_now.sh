#!/usr/bin/env bash
# Restart local paper API (:8001), bootstrap Upstox token, resume auto-trader.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${VM_LOCAL_API_PORT:-8001}"
API="http://127.0.0.1:${PORT}"

PID="$(pgrep -f "uvicorn app.main:app.*--port ${PORT}" | head -1 || true)"
if [[ -n "${PID}" ]]; then
  kill "$PID" 2>/dev/null || true
  sleep 2
fi

# Runtime secrets (Cursor Cloud Environment) must be present in this shell.
SESSION=vm-paper-${PORT}
tmux -f /exec-daemon/tmux.portal.conf has-session -t "=$SESSION" 2>/dev/null && \
  tmux -f /exec-daemon/tmux.portal.conf kill-session -t "=$SESSION" || true
tmux -f /exec-daemon/tmux.portal.conf new-session -d -s "$SESSION" -c "$ROOT" -- \
  "${SHELL:-bash}" -l -c 'exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port '"$PORT"' --reload'

for _ in $(seq 1 40); do
  curl -sf "${API}/health" >/dev/null && break
  sleep 1
done

echo "=== bootstrap Upstox ==="
curl -sS -X POST "${API}/api/paper-lab/bootstrap-upstox" | python3 -m json.tool || true

echo "=== paper lab status ==="
curl -sS "${API}/api/paper-lab/status" | python3 -m json.tool

echo "=== upstox status ==="
curl -sS "${API}/api/upstox/status" | python3 -m json.tool || true

echo "=== resume auto-trader ==="
curl -sS -X POST "${API}/api/execution/resume" | python3 -m json.tool || true

echo "=== one paper cycle (prod snapshots if no local token) ==="
curl -sS -X POST "${API}/api/paper-lab/sync-prod-once" | python3 -m json.tool || true