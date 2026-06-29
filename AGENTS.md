# AGENTS.md

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
