# NexusQuant v2.0 — Enhanced Indian Index Options Scalping Terminal

Institutional-style scalping terminal for **NIFTY**, **SENSEX**, and **BANKNIFTY** index options. Built for quick small-profit scalping with real Upstox data only — no dummy prices.

## Core Rule

**No fake or random prices.** If Upstox or the backend is unavailable, the UI shows an explicit waiting/error state.

## What's More Powerful Than v1

| Feature | Base Spec | NexusQuant v2.0 Enhanced |
|---------|-----------|--------------------------|
| TQS entry threshold | 72 | **68** — more scalp opportunities |
| Velocity gate | 2.0% | **1.8%** — faster entries |
| Micro profit lock | 3.0pt | **2.5pt** — quicker booking |
| Tick momentum | — | **Multi-timeframe fusion** in orderflow |
| Targets | Static session | **Adaptive targets** based on velocity |
| Orderflow | 4 metrics | **5 metrics** incl. tick momentum |

## Stack

- **Frontend:** React + TypeScript + Vite + Tailwind
- **Backend:** FastAPI + asyncio + Docker
- **Data:** Upstox (primary), Finnhub (news), Redis (tokens/state)

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env with your Upstox API key/secret and Finnhub key
```

### 2. Run with Docker

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Health: http://localhost:8000/health

### 3. Development (local)

**Backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

### 4. Authenticate Upstox

1. Open http://localhost:8000/api/upstox/login
2. Complete OAuth → token stored in Redis
3. Snapshots will show real LTP within ~3s

## Architecture

```
IN (inputs)                    PROCESSING                     OUT (outputs)
─────────────                  ────────────                   ─────────────
Upstox OAuth/token      →      realtime_engine         →      HTTP snapshots → React UI
Option chain/LTP/candles       ai_engine (TQS)                Paper trade events
Finnhub news                   auto_trader                    Daily PF reports
Operator settings              simple_profit (enhanced)       Status APIs
IST session clock              risk_engine                    Live orders (if enabled)
                               daily_calibration
```

## Active Trading Mode

**Enhanced Simple Profit Mode** (default):
- Entry: velocity ≥ 1.8%, TQS ≥ 68, breadth-aligned
- Sizing: 6 / 10 / 14 lots
- Targets: 5–7pt by session (adaptive)
- Micro lock: +2.5pt with 1.25pt trail
- Stop: −3pt after 30s min hold
- Max hold: 180s

## Safety Defaults

```
ENABLE_LIVE_TRADING=false
PAPER_TRADING=true
SHADOW_TRADE_ALL_SIGNALS=true
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/market/snapshots` | GET | Multi-symbol snapshot (poll every 3s) |
| `/api/upstox/login-url` | GET | OAuth login URL |
| `/api/execution/stop` | POST | Halt auto-trading |
| `/api/execution/resume` | POST | Resume auto-trading |
| `/api/auto-trader/status` | GET | Open trades, mode flags |
| `/api/auto-trader/reset` | POST | Clear calibration blocks |
| `/api/capital` | POST | Set paper capital |
| `/api/risk/profile` | POST | Set risk thresholds |
| `/health` | GET | Health check |
| `/api/deployment/status` | GET | Commit, token, flags |

## Frontend Modules (18)

Execution HUD · Explosive Runner · Option Heatmap · Orderflow Analytics · AI Matrix · Greeks & IV · Strategy Router · Paper Trading · Risk Engine · Trade Journal · Live Trading Gate · Morning Checklist · Market Profile · News & Events

## Production Deployment

- Frontend: Vercel (`VITE_API_URL=https://api.nexusquant.uk`)
- Backend: AWS EC2 behind ALB with Docker
- Env: `/opt/nexusquant/env`

## License

Private — for personal/educational trading use only. Not financial advice.
