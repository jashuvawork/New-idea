# AGENTS.md

## CE / PE symmetry (session gates & bypasses)

When changing **session gates, directional lock, breadth blocks, bypasses, or side-specific entry/exit rules**, implement **both CALL (CE) and PUT (PE)** unless there is an explicit, documented market reason not to.

| CALL (CE) | PUT (PE) mirror |
|-----------|-----------------|
| Rally off session **low** | Slide off session **high** |
| Bullish RSI / MACD / mom5 | Bearish RSI / MACD / mom5 |
| Unlock after PUT / bearish session | Unlock after CALL / bullish session |
| `hard_block_call_vs_bearish_breadth` | `hard_block_put_vs_bullish_breadth` |

**Checklist for new side logic:**
1. Add config for both sides (or one threshold with mirrored semantics, e.g. `min_rsi` / `max_rsi`).
2. Wire into `check_directional_side_lock` and `breadth_hard_blocks_side` for **both** directions.
3. Add paired tests (CE + PE) in `backend/tests/`.
4. Expose both in `directional_lock_summary` / deployment HUD when observability matters.

Reference: `backend/app/engines/index_rally_side_flip.py` (`_call_rally_bypass` / `_put_slide_bypass`).

## Cursor Cloud specific instructions

NexusQuant v2.0 is a single product split into two dev services (run both for end-to-end work). Standard commands live in `README.md`; the notes below are the non-obvious caveats for this environment.

### Services
| Service | Dir | Dev command | Port |
|---|---|---|---|
| Backend (FastAPI) | `backend/` | `.venv/bin/uvicorn app.main:app --reload --port 8000` | 8000 |
| Frontend (Vite/React) | `frontend/` | `npm run dev` | 5173 |

- The update script provisions `backend/.venv` (Python deps) and `frontend/node_modules`. Always run the backend via the venv (`backend/.venv/bin/uvicorn ...`), not a global `uvicorn`.
- Run backend from inside `backend/` — `pydantic-settings` loads `.env` relative to the current working directory.
- The Vite dev server proxies `/api` and `/health` to `http://localhost:8000`, so the frontend needs the backend running to show anything beyond the onboarding banner.
- There are no lint or automated test suites configured (frontend `package.json` only has `dev`/`build`/`preview`; backend has no test runner). "Build" check for the frontend is `npm run build` (runs `tsc -b`).

### Expected "no data" state without credentials
- `.env` is gitignored and not required to boot. With no `UPSTOX_API_KEY`/`UPSTOX_API_SECRET`, the app runs correctly but the UI stays in a "Waiting for live market data — Upstox not authenticated" state by design (the product never shows fake prices). Backend health (`/health`) and most control APIs (`/api/deployment/status`, `/api/capital`, `/api/execution/{stop,resume}`, `/api/auto-trader/status`) work without credentials. To exercise live market data, set Upstox keys in `.env` and complete OAuth at `/api/upstox/login-url`.

### Gotcha: trade-store path
- `.env.example` ships the production path `TRADE_STORE_DIR=/opt/nexusquant/data/trades`, which is NOT writable in this VM and makes `/api/deployment/status` 500. If you create a `.env` from the example, override it to a writable path (the code default is fine): `TRADE_STORE_DIR=/tmp/nexusquant/trades`. Running with no `.env` at all also works because that default is already dev-safe.
- Redis is optional: `redis_store.py` falls back to in-memory storage when Redis is unavailable, so no Redis server is needed for local dev. PostgreSQL is declared in deps but unused.

### Radar / EOD storage (analysis-only from Aug 26+)
- Intraday telemetry lives under `{TRADE_STORE_DIR}/radar_archives/telemetry/` (`*.premium.jsonl`, `*.funnel.jsonl`).
- At **16:00 IST finalize**, the daily ZIP (`radar-YYYY-MM-DD.zip`) keeps only what EOD replay needs: **premium tape**, **funnel events**, **scorecard**, and radar entries. Alerts tape and pipeline history are **not** stored by default.
- After finalize, intraday telemetry JSONL is **purged** (data remains in the ZIP). Retention is **7 days** of ZIPs.
- EOD replay reads `premium_tape.jsonl` from telemetry during the session, or from the ZIP after finalize (`/api/ai/eod-local-base-replay/{DATE}`).
