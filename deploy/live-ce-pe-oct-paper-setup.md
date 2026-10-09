# Live setup — CE + PE like Oct 1 / Oct 5 paper

Use this when arming **live** so execution uses the **same rule stack** that produced Oct 1 / Oct 5 paper results (base → lift, both sides, no legacy ₹10k narrow stack).

**Rules (one file):** [`env.october-frozen.overlay`](env.october-frozen.overlay)  
**Capital (pick one):** [`env.live-150k.overlay`](env.live-150k.overlay) · [`env.live-50k.overlay`](env.live-50k.overlay) · [`env.live-200k.overlay`](env.live-200k.overlay)  
**Scope doc:** [`paper-live-parity-scope.md`](paper-live-parity-scope.md)

## What “Oct paper results” mean in code (not calendar dates)

| Outcome we want | Env / code (from merged PRs) |
|-----------------|------------------------------|
| **CE + PE same day** — rally unlock + slide unlock, mirror after trail wins | `SYMMETRIC_BEST_TRADE_CAPTURE`, `INDEX_RALLY_SIDE_FLIP`, `MIRROR_WIN_*` in frozen overlay (#678, #706) |
| **Enter at pad / local base**, block session-high chase | `LIVE_PAPER_PARITY_PAD_ENTRY_GUARD`, `BEST_TRADE_BASE_FIRST`, `PREMIUM_VERTICAL_CHASE_BLOCK` (#669-670, #707) |
| **9:15 open first rip** per side, not afternoon rank-#1 chase | `SEP09/SEP917_OPEN_PREMIUM_FIRST_RIP_WAIVE_*` (#651-656) |
| **After PUT win**, block cross-index PUT chase; prefer CE mirror | `PE_WIN_CE_MIRROR_BLOCK_PUT_CHASE` (#674, #677) |
| **After morning win on same strike**, allow afternoon V-rip | `SAME_STRIKE_POST_WIN_V_RIP_REENTRY_WAIVE_*` (#683-684) |
| **No live-only session halts** that paper skips | `EXPIRY_WORST_DAY_HALT_ENTRIES=false`, parity flags (#718-719) |
| **Hold to 15:35** like Upstox tail | `POWER_HOUR_END_MINUTE=35` (#679) |
| **Stage lock must not freeze entries** after MTM peak on flat book | `DAILY_PROFIT_STAGE_BLOCK_ENTRIES_MIN_STAGE=3` (#682) |
| **Book 2×+ fast-fade exits** on rip legs | `EXPLOSION_MULTIPLE_FAST_FADE_ENABLED` (#680-681) |

Live must **not** use [`env.live-10k.overlay`](env.live-10k.overlay) with Frozen October (`go-live` refuses the combo).

## EC2 — standard path (₹1.5L live / ₹1.5L paper)

Run on the instance as **root**, after `main` is deployed (CI green):

```bash
cd /opt/nexusquant/New-idea   # or your REPO_DIR

# 1) Rules + paper capital (still paper execution)
sudo bash deploy/go-live-10k-monday.sh --prepare

# 2) Pre-open verify (read-only API + env audit)
sudo EXPECT_LIVE=false bash deploy/verify-oct-live-ready.sh

# 3) Upstox OAuth if needed — browser: https://www.jashuvatrade.xyz → login URL

# 4) Arm live before 09:15 IST
sudo LIVE_OVERLAY=deploy/env.live-150k.overlay LIVE_CAPITAL_INR=150000 \
  bash deploy/go-live-10k-monday.sh --arm-live

# 5) Fail-closed gate
sudo EXPECT_LIVE=true LIVE_CAPITAL_INR=150000 bash deploy/verify-oct-live-ready.sh
```

**HUD must show:** `frozenOctoberProfile.profileOk`, `livePaperProfile.profileOk`, `flags.entryGatesMatchPaper: true`, `flags.tradingRulesMatchPaper: true`, `enableLiveTrading: true`, `paperTrading: false`.

## ₹50k live (Frozen Oct + scaled risk)

```bash
sudo PAPER_OVERLAY=deploy/env.paper-50k.overlay PAPER_CAPITAL_INR=50000 \
  LIVE_OVERLAY=deploy/env.live-50k.overlay LIVE_CAPITAL_INR=50000 \
  bash deploy/go-live-10k-monday.sh --prepare

sudo LIVE_OVERLAY=deploy/env.live-50k.overlay LIVE_CAPITAL_INR=50000 \
  bash deploy/go-live-10k-monday.sh --arm-live

sudo EXPECT_LIVE=true LIVE_CAPITAL_INR=50000 \
  CAPITAL_OVERLAY=deploy/env.live-50k.overlay \
  bash deploy/verify-oct-live-ready.sh
```

Daily loss stop should be **10% of book** (₹5k on ₹50k).

## After deploy / template sync (no arm)

GitHub Actions `deploy-ec2.yml` re-applies frozen rules + paper capital via [`apply-live-paper-parity-env.sh`](apply-live-paper-parity-env.sh) so template keys like `WORST_DAY_BLOCKS_LIVE=true` do not stick. If env drifted:

```bash
sudo ENV_FILE=/opt/nexusquant/env bash deploy/apply-live-paper-parity-env.sh
sudo docker compose -f docker-compose.prod.yml up -d --force-recreate backend
sudo bash deploy/audit-live-paper-env.sh
```

## End of session — back to paper

```bash
sudo PAPER_OVERLAY=deploy/env.paper-150k.overlay PAPER_CAPITAL_INR=150000 \
  bash deploy/go-live-10k-monday.sh --paper
```

Includes `POST /api/auto-trader/reset` so daily loss stop does not block next paper session.

## Intraday checklist

Full gate list: [`october-live-session-checklists.md`](october-live-session-checklists.md)

**Quick CE/PE sanity at open:** funnel should show `SELECTED` → `ENTERED` on ELITE **armed_base_launch / first_lift / v_rip** near **pad**, not only on radar. Block reasons like `live_oct1_chase_at_session_high` or `negative_velocity` without structural context mean location or feed — not “wrong calendar day.”
