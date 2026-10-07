# Frozen October — session checklists (entry → exit)

Operational checklists for **live and paper** when [`env.october-frozen.overlay`](env.october-frozen.overlay) is active. Use with [`verify-oct-live-ready.sh`](verify-oct-live-ready.sh) before open and the **post-session audit** at the bottom after close.

**What is / isn’t mirrored paper↔live:** [`paper-live-parity-scope.md`](paper-live-parity-scope.md)

**HUD (read-only):** `GET https://api.jashuvatrade.xyz/api/deployment/status`  
**Readiness:** `GET /api/deployment/readiness`  
**Sep917 four-step lane vocabulary:** `backend/app/engines/sep917_live_checklist.py` (overlay has `SEP917_LIVE_CHECKLIST_ENFORCEMENT_ENABLED=false`; lanes still appear in funnel/HUD context).

---

## 0. Pre-session (infra + profile)

| # | Check | Pass when |
|---|--------|-----------|
| 0.1 | Backend healthy | `/health` → `status: ok`, loop watchdog age &lt; 20s |
| 0.2 | Rules deployed | `commit` on `/api/deployment/status` = merged `main` (includes Oct 1 **pad guard on live+frozen**, #707+). **Do not arm live** if commit is behind `main` or pad/timing parity fixes are missing. |
| 0.2b | Entry gate parity | When live armed: `flags.entryGatesMatchPaper: true` (paper entry rules on live — Frozen Oct + auto, or explicit parity flags) |
| 0.3 | Frozen October | `frozenOctoberProfile.profileOk: true`, `cePeSymmetricOk: true` |
| 0.4 | Parity book | `livePaperProfile.profileOk: true`, `fallbackCapitalInr` = intended (e.g. 150000), `sizesFromPaperBook: true` |
| 0.5 | Pad guard | `padEntryGuardEnabled: true` |
| 0.6 | Symmetric capture | `symmetricBestTradeCaptureEnabled`, `indexRallySideFlipEnabled`, `directionalSideLockEnabled` all true |
| 0.7 | Live vs paper intent | Paper: `enableLiveTrading: false`, `paperTrading: true`. Live: opposite + `readyForLive: true` after arm |
| 0.8 | Upstox | Token valid pre-open (`/api/upstox/login-url` if expired) |
| 0.9 | Session reset | After live→paper or new batch: `POST /api/auto-trader/reset` so daily loss stop does not block paper |

```bash
# EC2
sudo EXPECT_LIVE=false bash deploy/verify-oct-live-ready.sh
# After arm-live
sudo EXPECT_LIVE=true LIVE_CAPITAL_INR=150000 bash deploy/verify-oct-live-ready.sh
# ₹50k live: CAPITAL_OVERLAY=deploy/env.live-50k.overlay and LIVE_CAPITAL_INR=50000
```

---

## 1. Entry checklist (open a leg)

**Goal:** Oct 1-style **pad / base**, not session-high **chase**. CE and PE use the **same** location rules (`live_oct1_pad_entry_guard.py`, `symmetric_best_trade_at_base_capture`).

| # | Gate | What to verify | Fail / block signals |
|---|------|----------------|----------------------|
| 1.1 | **Explosion-only elite path** | Mode `explosion`, tier ELITE or EXPLODING | Scalp/OTM/shallow OTM disabled in overlay |
| 1.2 | **Sep917 / near-base shape** | Evidence: local base move ~≤20% (shape), ICT/base fields present | `live_oct1_not_near_base_shape` |
| 1.3 | **Pad location (critical)** | `drawdownFromHighPct` ≤ about −6% (off session high); session range position ≤ ~0.52 | `live_oct1_chase_at_session_high`, `live_oct1_chase_session_range_high` |
| 1.4 | **Timing vs pad** | If timing was GOOD but 1.3 fails → must become **CHASE / block** (#707) | `oct1PadTimingBlock: true`, timing `action: block` |
| 1.5 | **Entry timing assessment** | Prefer GOOD at **pad**; COLD/LATE capped lots; CHASE blocked | `timing_blocks_entry`, lot caps on timing |
| 1.6 | **No extended chase (chop-live)** | Pad % vs session move within chop limits | `chop_live_extended_chase_*` |
| 1.7 | **Pretrade / rank** | Score ≥ floor; symbol PF/net not blocked | `pretrade_*`, `pretrade_rank_below_*` |
| 1.8 | **Chart / execution chart** | Chart gate pass or documented bypass (base, v_rip, pad lane) | `pretrade_*chart*`, funnel `EXEC_CHART_*` |
| 1.9 | **Breadth / directional hard block** | CE vs bearish breadth / PE vs bullish breadth | `hard_block_call_*` / `hard_block_put_*` |
| 1.10 | **Directional side lock** | Side allowed for session (unless rally/slide unlock) | `directional_side_lock_*` |
| 1.11 | **Post-win / same-strike** | After trail win, re-entry caps and FOMO guards | `same_strike_post_win_*`, post-win afternoon blocks |
| 1.12 | **Risk / lots** | Per-trade risk, daily loss stop, FTV max positions (3) / same side (2) | `per_trade_risk_exceeded`, `DAILY_LOSS_STOP` |
| 1.13 | **Live leg metadata** | `executionMode` LIVE or paper parity; **`paperLiveParity: true`** when parity stack intended | Parity false on live → pad guard was skipped pre-#707 |

**Oct 7 anti-pattern (must NOT repeat):** NIFTY CE 22700 — local base ~7%, fill at session high (`drawdownFromHighPct: 0`), timing GOOD → **−₹31k**. Checklist **1.3–1.4** exist to block this after #707 deploy.

**Quick entry sanity on a candidate (mental Sep917 steps):**

1. Index structure — CE rally off session **low** / PE slide off session **high** (or unlock armed)?  
2. Option shape — near-base FTV/V/elite, not naked +40% chase?  
3. Session context — chop, post-win FOMO, side blocks OK?  
4. Funnel — rank + timing + pad guard authorize?

---

## 2. Selection checklist (which strike / leg)

**Goal:** **Top moments at ATM/ITM**, rank-1 explosion, not cheap OTM stack.

| # | Check | Pass when |
|---|--------|-----------|
| 2.1 | **Sep917 legacy profile** | ATM/ITM preference; no shallow OTM explosion entries |
| 2.2 | **Best trade base-first** | Base-first ranking when symmetric capture on |
| 2.3 | **Elite / exploding only** | `EXPLOSION_ELITE_EXPLODING_ONLY`; no explosion-only bypass to weak tiers |
| 2.4 | **Rank / score** | Top radar / selection score justifies full or max lots |
| 2.5 | **FTV allocation** | ≤3 open FTV slots; ≤2 same side unless policy allows |
| 2.6 | **Instrument / symbol cooldown** | Not in loss cooldown on same instrument |
| 2.7 | **Duplicate open leg** | No duplicate symbol+side+strike open |
| 2.8 | **Opposite dominant rip** | If radar top is **opposite side** same strike window, ask: should mirror/flip lane take **PE** instead of **CE** at peak? (selection, not automatic) |

---

## 3. Flipping & switching checklist (CE ↔ PE, session side)

**Goal:** Same-day **best CE and best PE** without sticky one-side book; flips **unlock**, they do not **force** the best leg.

| # | Mechanism | CE | PE (mirror) |
|---|-----------|----|----|
| 3.1 | **Index rally side flip** | Rally off session low → CE unlock path | Slide off session high → PE unlock path |
| 3.2 | **Directional side lock** | Blocks CE when session bearish-locked | Blocks PE when session bullish-locked |
| 3.3 | **Mirror after win** | PE win → CE mirror arm (`pe_win_ce_mirror`) | CE win → PE mirror arm (`put_slide_ce_mirror`) |
| 3.4 | **Mirror threshold** | Trail win ≥ `MIRROR_WIN_MIN_*` (e.g. 0.2% capital, ₹250 floor) | Same |
| 3.5 | **Loss-triggered flip** | After same-side loss, opposite side unlock cooldown | Paired in `loss_triggered_side_flip` |
| 3.6 | **Chop mirror waive** | Near-base Sep917 shape waive on chop-live | Same (`CHOP_LIVE_WAIVE_NEAR_BASE_SEP917_SHAPE`) |
| 3.7 | **Breadth hard block** | Do not flip into blocked side vs breadth | Both directions |

**Verify in session:** `/api/deployment/status` flags above; funnel events for `mirror*`, `side_flip`, `directional_lock`, `index_rally*`.

**Switching is not entry:** A flip **allows** the opposite side; you still must pass **Section 1** (pad, timing, rank) on the new candidate.

---

## 4. Holding checklist (open position)

**Goal:** Let **runners** run from **good entries**; do not confuse **hold** with **fixing a bad entry**.

| # | Check | Notes |
|---|--------|------|
| 4.1 | **Exit plan stamped** | `entryContext.exitPlan` with `stopPoints`, `adaptiveStop: true` when adaptive exits on |
| 4.2 | **Adaptive SL active** | `ADAPTIVE_EXITS_ENABLED`; losers exit `adaptive_stop_loss` / structural SL, not scratch FOMO (`EXECUTED_ENTRY_SL_ONLY_LOSS_EXITS`) |
| 4.3 | **No live-only early scratch** | `LIVE_EARLY_FAIL_EXIT_ENABLED=false`, `CHOP_LIVE_EARLY_FAIL_EXIT_ENABLED=false` in overlay |
| 4.4 | **Defer rules** | High conviction / base-rip / confidence-hold may **defer** adaptive SL — acceptable only if entry was **pad/base** |
| 4.5 | **Stage ladder / elite runner** | `momentStageLadder`, peak keep, reversal keep — watch giveback vs projected max |
| 4.6 | **LTP sanity** | Open marks sanitized (`open_trade_ltp_sanity`) — spikes must not fake trail/peak |
| 4.7 | **Live velocity** | `liveVelocity3s` on context — expansion may defer trail; **loss** must still respect hard SL when defer ends |
| 4.8 | **Session close** | Force-flat live / parity at 15:30 IST (`live_session_close_force_exit`) |

**Red flag while holding:** Entry was at session high (0% off high) but position still full size — **exit limits damage**; next session fix is **entry 1.3**, not tighter hold alone.

---

## 5. Exit checklist (close a leg)

**Goal:** **Structural / adaptive SL** for losers; **peak keep / stage trail** for winners — aligned with Oct paper profile.

| # | Exit type | Typical reason | When |
|---|-----------|----------------|------|
| 5.1 | **Adaptive stop** | `adaptive_stop_loss` | Loss beyond plan `stopPoints` after min hold |
| 5.2 | **Chop second tier** | `chop_second_tier_stop_loss` | Chop-live tier structural breach |
| 5.3 | **Fixed explosion SL** | `explosion_stop_loss` | Non-adaptive path / legacy params only |
| 5.4 | **Peak / velocity keep** | `explosion_peak_velocity_reversal_keep`, `explosion_peak_keep_trail` | Winner giveback after meaningful peak |
| 5.5 | **Stage trail** | `explosion_stage_trail`, `explosion_stage_trail_lock` | Stage ladder ratchet |
| 5.6 | **Session close** | Session close guard reason | 15:30 IST live/parity |
| 5.7 | **Daily profit / loss stop** | `DAILY_LOSS_STOP`, profit gate | Session-level — no new entries |

**After close:** Record `exitReason`, `entryTiming`, `drawdownFromHighPct` / pad meta for post-session audit.

---

## 6. Post-session audit (repeatable, read-only)

Run in order **after** close — no config changes from monitor.

| Step | Action | Purpose |
|------|--------|---------|
| A | `/health`, `/api/deployment/status` | Uptime + commit + profile flags |
| B | Closed trades | `GET /api/auto-trader/history/trades/closed?limit=100` — PnL, `exitReason`, `entryContext` |
| C | EOD report | `GET /api/ai/eod-trade-report/{DATE}` — replay PnL, `scorecard.overall` captured vs **addedLosers** |
| D | Funnel / blocks | Radar ZIP or telemetry funnel — top misses, block reason counts |
| E | Loss autopsy (each loss &gt; ₹3k or top miss) | Map to **Section 1–5** — which checklist row failed? |
| F | Hypothesis | **One** root cause; rule change only if stabilization bar met (`AGENTS.md`) |

### Loss → checklist mapping (quick reference)

| Symptom | Likely failed rows |
|---------|-------------------|
| Big loss, timing GOOD, at session high | **1.3, 1.4, 1.13** |
| Wrong side (CE when PE rip dominant) | **2.8, 3.x** (unlock without pad entry on correct side) |
| Many small scratch losses | **4.2, 5.1** (sl-only vs early exit config) |
| Re-entry after win blew up | **1.11, 3.4** |
| OTM / cheap premium chase | **2.1, 1.2** |
| Blocked top ELITE all day | **1.7, 1.9, 1.12** — intentional vs bug (funnel evidence) |

### Example commands (replace `DATE`)

```bash
BASE=https://api.jashuvatrade.xyz
curl -sS "$BASE/health" | jq '.status,.loopWatchdog.lastBeatAgeSeconds'
curl -sS "$BASE/api/deployment/status" | jq '{commit, frozen: .frozenOctoberProfile, live: .flags.enableLiveTrading, parity: .flags.livePaperProfile}'
curl -sS "$BASE/api/auto-trader/history/trades/closed?limit=50" | jq '[.trades[] | {closedAt, symbol, side, strike, pnlInr, exitReason}]'
curl -sS "$BASE/api/ai/eod-trade-report/DATE" | jq '{netPnlInr, wins, losses, scorecard: .scorecard.overall}'
```

---

## 7. “Would live gates block this loss?” (evidence bar)

Use this when reviewing a **specific** loss (e.g. Oct 7 live −₹31k):

1. Reconstruct **entry** premium vs session low/high and **timing** / **parity** flags from trade JSON.  
2. Run mental **Section 1** — if **1.3** fails, **post-#707 live+frozen** should **block at entry** (see `tests/test_live_oct1_pad_frozen_live.py`).  
3. If entry would still pass, **exit** checklist explains INR loss (**5.1**), not prevention.  
4. Do **not** claim “all historical losses blocked” without per-day funnel + EOD **addedLosers** count.

---

## Related files

| Area | Path |
|------|------|
| Frozen rules | `deploy/env.october-frozen.overlay` |
| Pad guard | `backend/app/engines/live_oct1_pad_entry_guard.py` |
| Pretrade | `backend/app/engines/pretrade_validator.py` |
| CE/PE flip | `backend/app/engines/index_rally_side_flip.py`, `directional_lock.py` |
| Mirror wins | `backend/app/engines/pe_win_ce_mirror.py`, `put_slide_ce_mirror.py` |
| Exits | `backend/app/engines/explosion_profit.py`, `adaptive_exits.py` |
| Agent playbook | `AGENTS.md` |
