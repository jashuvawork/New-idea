# Daily sizing book

Each session, set how much capital the bot may size from (paper book / live parity book — not broker equity unless `USE_UPSTOX_CAPITAL_FOR_SIZING=true`).

## Production (EC2) — recommended

1. **Write today's amount** (one number, INR):

   ```bash
   echo 45000 | sudo tee /opt/nexusquant/daily-capital.book
   ```

2. **Apply** (updates `/opt/nexusquant/env` + live runtime; no container restart by default):

   ```bash
   cd /opt/nexusquant/New-idea
   sudo bash deploy/set-daily-capital.sh
   ```

3. **Verify**:

   ```bash
   curl -s http://127.0.0.1:8000/api/auto-trader/capital | python3 -m json.tool
   ```

   In the UI, **Capital alignment** on the analysis page should show runtime and env matching.

### Shortcuts

| You have | Command |
|----------|---------|
| Amount on CLI | `sudo bash deploy/set-daily-capital.sh 50000` |
| Env var | `sudo CAPITAL_BOOK_INR=50000 bash deploy/set-daily-capital.sh` |
| After deploy (reload env in container) | `sudo RESTART_BACKEND=1 bash deploy/set-daily-capital.sh` |

Legacy scripts `deploy/set-capital-book.sh` and `deploy/set-paper-capital.sh` forward here (`RESTART_BACKEND=1` for post-deploy).

## Local dev

Runtime only (until restart):

```bash
cd backend
./scripts/set_daily_capital.sh 45000
```

Or patch `backend/.env` with `FALLBACK_CAPITAL_INR` / `MAX_SIZING_CAPITAL_INR` and restart uvicorn.

## What gets updated

- `FALLBACK_CAPITAL_INR` and `MAX_SIZING_CAPITAL_INR` in production env
- In-memory sizing via `POST /api/auto-trader/capital` (`allocatedInr`). Runtime book cannot exceed env `MAX_SIZING_CAPITAL_INR` until env is updated (use `set-daily-capital.sh` for both).
- Daily loss stop uses **35%** of this book when `DAILY_LOSS_STOP_CAPITAL_PCT=0.35`
- Per-trade sleeve uses **90%** of the book when `PER_TRADE_CAPITAL_PCT=0.90`