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

## Stabilization playbook (owner mindset)

**Goal:** Stop daily firefighting. Tune on **evidence**, deploy **once**, protect production uptime. Rule changes are expensive — default to **no change** unless the bar below is met.

### Operating phases

| Phase | When | Agent behavior |
|-------|------|----------------|
| **Tuning** | After a bad/missed session, or before next expiry | EOD replay + radar first; **at most one focused PR** per incident |
| **Stabilization** | Chasing 50-trade batch with clean deploys | Bugfixes + infra only; **no new gates** unless PnL/miss threshold hit |
| **Maintenance** | Batch criteria met, live armed | Monitoring, OAuth, deploys for real bugs — **no reactive gate stacking** |

We are in **Tuning → Stabilization**. Expect high churn to **drop sharply** after 2–3 clean expiry sessions without a “rewrite the gates” incident.

### When to change trading rules (bar must be met)

Do **not** stack same-day guard PRs after every session. Open a rule-change PR only if **one** of:

1. **Session PnL ≤ −₹20k** and radar/EOD shows a **named miss** (e.g. top ELITE blocked by `DAILY_LOSS_STOP`, post-win FOMO re-entry).
2. **Missed top trade** with **MFE ≥ +150%** on radar and **zero execution attempts** in funnel (not “we would have liked more”).
3. **Repeat failure** — same block reason **≥ 3 times** in one session on trades that would have been top-tier.

If none apply: **analysis-only** (scorecard, funnel, EOD replay). No production code.

### Post-session workflow (mandatory order)

1. **Read-only production** — `/health`, `/api/deployment/status`, closed trades, radar scorecard. Never place orders or change config from the monitor.
2. **EOD / radar** — `/api/ai/eod-trade-report/{DATE}`, funnel, premium tape. Quantify: captured vs missed vs added losers.
3. **One hypothesis** — single root cause (e.g. “post-win afternoon FOMO”, not five unrelated tweaks).
4. **One PR** — minimal diff; CE/PE symmetry if side-specific; paired tests.
5. **Deploy** — merge to `main` only when `backend/.venv/bin/python -m pytest tests/ -q` passes locally; CI deploy-ec2 must go green before calling it done.
6. **Verify production** — `commit` on `/api/deployment/status` matches merged `main`; spot-check the gate in flags/HUD if relevant.

### Deploy discipline

- **Single path:** push to `main` → GitHub Actions `deploy-ec2.yml` → SSM → `deploy/ec2-update.sh`. No orphan fix branches for the same issue.
- **Before merge:** full backend pytest green. Deploy failures from mock drift are preventable — see test rules below.
- **Never merge duplicate PRs** for the same fix (#548 vs #549). If a branch is superseded, **close it**; do not merge both.
- **Merge conflicts on tests:** prefer values that match **`Settings()` / `config.py` defaults**, not arbitrary literals (e.g. expiry morning end **13:30**, not 12:00).
- **After deploy:** confirm `https://api.jashuvatrade.xyz/api/deployment/status` `commit` matches `git rev-parse --short origin/main`.

### Test mock rules (prevents #548 / #549 drift)

When production changes function signatures or adds gate fields:

1. Use **`backend/tests/mock_defaults.py`** — `settings_mock()` and `profit_gate_stub()`, not hand-rolled `MagicMock()` missing new fields.
2. **`settings_mock()`** copies all fields from `Settings()` — defaults stay aligned with production.
3. **`profit_gate_stub()`** mirrors `DailyProfitGate` (`status="ACTIVE"`, `dailyLossStopExpiryTopOnly`, etc.).
4. If you patch `update_daily_profit_gate`, accept **`(state, snapshots)`** — use `lambda *_a, **_k: profit_gate_stub()`.
5. Run **`pytest tests/ -q`** before push; do not rely on CI as the first test run.

### Production infra

- **Endpoints (in order):** `https://api.jashuvatrade.xyz` → `http://65.0.136.146:8000` → `https://www.jashuvatrade.xyz`.
- **Healthy:** `/health` returns `status: ok`; loop watchdog beat age &lt; 20s.
- **Backend down pattern:** ports 80/443 open, **8000 closed**, nginx hangs — backend container crashed. Recommend on EC2:
  ```bash
  docker ps -a
  docker compose -f docker-compose.prod.yml restart backend
  curl http://localhost:8000/health
  docker logs --tail 100 <backend-container>   # if exited
  ```
- **Upstox:** token expires **03:30 IST** daily — re-login before open via `/api/upstox/login-url`.
- **50-trade milestone:** `POST /api/auto-trader/milestone/reset` archives batch; does **not** delete trade logs.

### PR / agent hygiene

- Branch names: `cursor/<descriptive-name>-f5cb`.
- **One logical change per commit/PR** unless explicitly batched by the user.
- Session gate changes: **CE + PE** (see top of this file).
- Do not force-push or amend unless asked.
- Live monitor timers are **read-only** — report infra, open PnL, closed net, new trades; recommend restart if down.

### What “done” looks like (exit tuning phase)

- [ ] **2–3 expiry sessions** without a new “Sep03-style” gate stack
- [ ] **Deploy green** on every `main` push (no mock/signature surprises)
- [ ] **50-trade batch** progressing with PF ≥ 2.5, WR ≥ 50%, DD ≤ 5%
- [ ] **Production uptime** — no multi-hour backend outages without restart
- [ ] **Top misses** either captured or documented as intentional blocks with evidence

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
