# Base capture (#676) — where we get stuck, hour by hour

**Purpose:** You can take trades, but **#676-style moments at the local base** sometimes never become entries. This guide names the **exact pipeline step** you are stuck on, what to read each hour (IST), and **why PR #676 could book at the base while today’s stack often stops later**.

**API base:** `https://api.jashuvatrade.xyz` → `http://65.0.136.146:8000`  
**Session date:** `DATE=$(TZ=Asia/Kolkata date +%F)`

Related: `/opt/cursor/artifacts/system-verification-checklist.md`, `.cursor/automations/local-base-layer-monitor.md`.

---

## One-page mental model: #676 vs “now”

| What **#676** optimized (still in code) | What **often blocks today** (after wins / afternoon) |
|----------------------------------------|------------------------------------------------------|
| **CE only**, **ATM/ITM**, tier **ELITE / EXPLODING / BUILDING** at **structural base** | Same shape still required for **+44 rank** — OTM calls never get the lane |
| **Near-base pad** (~2–15% local off session low on Sep917 profile, else ~20%) | Radar hot on **dailyMovePct** but **localBaseMovePct > pad** → you are chasing, not #676 |
| **`first_lift_entry_readiness`** + launch confirm (`ictFirstLift`, `armedBaseLaunch`, building rip) | Stuck at **L3** — BUILDING forever, or `launch_not_confirmed` in eligibility meta |
| **Rank +44** when `call_atm_itm_base_capture_eligible` is fully true (not pad alone) | Stuck at **L6** — candidate never outranks another strike / side |
| **`callAtmItmBase676Waive`** on **structured failed launch** (timing path) — full size at cold base | Does **not** waive **`reentry_ml_win_prob_low`** after you already closed a winner |
| **Macro index open-side** may be waived when #676 rank is armed (`open_side_confirmation`) | Other gates still apply: elite score, top-moment grade, fake trap, peak chase |
| **Failed launch** hard block softened when eligible | Post-win **same-strike CE** → **`ce_new_base_fresh_entry`** (#849), not quality passport ML waive |
| PE: rank penalty **−36** when CE base ready on index | PE **fresh-base ML waive** off by default (`pe_new_base_fresh_entry_enabled`) |

**Plain English:** #676 got you **to the base with size and rank** before the rip extended. **After a session win**, the dominant failure mode (e.g. **26 Oct 2026**) is no longer “failed launch at base” — it is **`reentry_ml_win_prob_low` at `SELECTOR_GATE`**, i.e. you are past the pool, ranked, then **ML re-entry** says no — and **same-strike CE** will not use the narrow quality passport for that.

---

## Pipeline steps (use this to say “stuck at step N”)

| Step | Name | PASS looks like | Typical FAIL / “stuck” signal |
|------|------|-----------------|-------------------------------|
| **L0** | Infra & loop | `/health` ok, beat age &lt; 20s, `autoTradingEnabled`, `newEntriesAllowed` | API down, loop stall, profit gate STOP |
| **L1** | Feed & phase | WS connected, `hasRecentTicks`, `marketPhase=LIVE_MARKET` | Stale chain, rate limit, CLOSED phase bug |
| **L2** | Radar / ICT stamps | `ictBaseArmed`, `ictFirstLift`, tier BUILDING→EXPLODING | No armed base on hot symbol, archive stale |
| **L3** | First-lift readiness | `first_lift_entry_readiness` → ok (not `index_turn_not_confirmed`, not `first_lift_quality<65` alone on armed base) | **ARMED_WAITING** in automation verdict |
| **L4** | **#676 eligibility** | `call_atm_itm_base_capture_eligible` true: ATM/ITM, structural/near pad, launch ok | `moneyness=OTM`, `launch_not_confirmed`, tier wrong |
| **L5** | **SELECTOR_POOL** | Funnel `timeline[].stage=SELECTOR_POOL` with reason if blocked | `entry_timing_*`, `fake_explosion_trap_*`, peak/immature — **silent** if old deploy (no pool rows) |
| **L6** | **SELECTOR_GATE** | Selected + entered, or clear rank reason | **`reentry_ml_win_prob_low`**, `elite_*`, `failed_launch`, top-moment grade |
| **L7** | Execution | `entered=true`, open trade with `localBaseBaseRelPct` in entry context | `orderRejected`, sizing, session block |

**Decision rule:** Find the **first** stage in **L0→L7** that is red for your **best ATM/ITM CE** candidate with **localBaseMovePct 2–15%**. That is your stuck step.

---

## Hourly playbook (IST, Mon–Fri)

Run the **Hour block** at the start of each hour (or automate hourly cron). Within the hour, the local-base monitor can still run every 1–2 min for heat.

### 09:00–09:14 — Pre-open (no entries yet)

| Do | Read | Stuck if |
|----|------|----------|
| `GET /api/deployment/readiness` | `readyForPaper`, `executionMode`, `checks.upstoxDataReady` | Not ready → **L0** |
| `GET /api/upstox/token/daily` | `validToday` | Token → **L0** (re-login before 09:15) |
| `GET /api/deployment/status` | `commit` vs `origin/main` | Drift → old gates (**L6** surprises) |
| `GET /api/auto-trader/status` | `dayMode`, chop guards | Wrong day mode → **L5/L6** one-sided |

**#676 note:** Open rip lanes may waive macro index from **09:20**; before that, do not expect #676 entries even if radar is warm.

---

### 09:15–10:00 — Open / first lift (highest #676 value)

| Do | Read | Stuck if |
|----|------|----------|
| `GET /api/ai/radar-health` | `feed.connected`, `lastTickAgeMs`, `cadence.buildLockHeld` | **L0/L1** |
| `GET /api/ai/radar-scorecard/$DATE` | BUILDING/EXPLODING with low `localBaseMovePct` | Only late ELITE → **L2** |
| `GET /api/execution/status` | `skipped[-3:]`, `lastEntry` | Same skip repeating → note stage |
| `GET /api/ai/radar-funnel/$DATE` | New rows; `timeline` for `SELECTOR_POOL` vs `SELECTOR_GATE` | Pool timing blocks → **L5**; no timeline → telemetry/deploy |

**#676 vs now:** First entries of the day usually **pre-date any session win**, so **`reentry_ml_win_prob_low`** is rare. Misses here are usually **L3** (lift not confirmed), **L5** (`entry_timing_cold_*` on chop open), or **L4** (OTM strike selected).

---

### 10:00–11:00 — Morning base windows

| Do | Read | Stuck if |
|----|------|----------|
| Funnel top rows by `radarOutcome.mfePct` | `blockers[]`, `entered`, `selected` | High MFE + `blocked` → read `timeline[].reason` |
| `GET /api/ai/missed-trades` | `blockers`, `localBaseMovePct` | TAKEABLE_HEAT: ready but not entered → **L6/L7** |
| Institutional readiness (optional) | MACD/RSI warm | Cold indicators → **L5/L6** timing/elite |

**#676 vs now:** Morning **multiple bases** should each get **+44 rank** when fully eligible. If only one strike ever enters, check **L6 rankedOut** (null blockers but `rankedOut=true` in funnel).

---

### 11:00–12:00 — First wins; re-entry policy starts to matter

| Do | Read | Stuck if |
|----|------|----------|
| Closed trades | First win time, strike, side | After win → expect **ML re-entry** scrutiny |
| Funnel for **same symbol/side** | `reentry_ml_win_prob_low` on timeline | **L6** — #676 rank did not waive ML |
| Cross-strike vs same-strike | CE passport: cross-strike ML waive only; same-strike → **#849 fresh base** | Same-strike afternoon CE blocked ML → intentional unless fresh-base meta |

**Live example (26 Oct 2026):** Win **NIFTY 22500 CE** ~11:55–12:01 IST; later **22500 / 22550 / 22450 CE** show funnel **`SELECTOR_GATE` / `reentry_ml_win_prob_low`** (MFE on radar still very high). Stuck step = **L6**, not L4.

---

### 12:00–13:00 — Midday chop / cold live v3

| Do | Read | Stuck if |
|----|------|----------|
| `entry_timing` reasons in pool timeline | `entry_timing_cold_*`, `chop_or_worst_cold_block` | **L5** — #676 waive covers **failed_launch**, not all cold timing |
| `callAtmItmBase676Waive` in timing meta (logs/HUD) | true on structured failed launch at pad | false while blocked → not in #676 waive path |

**#676 vs now:** At pad, **676 waive** helps **failed_launch** shape; **cold chop block** is separate unless policy allows lot_cap.

---

### 13:00–14:00 — Afternoon structural bases (#676 Oct 23 13:34 pattern)

| Do | Read | Stuck if |
|----|------|----------|
| Scorecard / ICT | Armed base at session low, `localBaseMovePct` 2–15% | **L4** `nearBasePad` without full eligibility → +44 **not** applied |
| `GET /api/ai/local-base-audit/$DATE` | layer2 pad stats | Avg entry pad &gt;&gt; 20% → not base capture |
| Funnel CE ATM/ITM keys | stage + reason | ML vs pool vs elite |

**#676 reference:** Tests cite **13:34 IST low** — armed base without hot lift can still be #676 **call** if eligibility passes. Stuck **L3** if launch never confirms.

---

### 14:00–15:20 — Post-win continuation vs FOMO

| Do | Read | Stuck if |
|----|------|----------|
| Funnel aggregate | Count by `timeline[].reason` | Dominant **`reentry_ml_win_prob_low`** → **L6** |
| Quality passport scope | FTV/V after win, **cross-strike** CE | Same-strike good moment → need **`ce_new_base_fresh_entry`** evidence in meta, not passport alone |
| Post-win guards | continuation lot cap | Continuation leg lot cap ≠ #676 full rank |

**Why #676 “took all at base” but now cannot:** #676 never promised **unlimited re-entries after ML**; it promised **rank and failed-launch relief at the base**. Post-win stack **tightened ML** and **scoped passport** — so afternoon **same-strike** bases can look identical on radar but fail at **L6**.

---

### 15:20–15:35 — Power hour / flatten

| Do | Read | Stuck if |
|----|------|----------|
| `newEntriesAllowed`, session end flags | 15:30/15:35 policy | **L0 session** — not a miss |
| EOD preview scorecard | Top MFE missed with zero `entered` | Schedule **I** blockers batch |

---

## Copy-paste: hourly diagnostic bundle

```bash
BASE=https://api.jashuvatrade.xyz
DATE=$(TZ=Asia/Kolkata date +%F)
HOUR=$(TZ=Asia/Kolkata date +%H)

curl -sS "$BASE/health" | jq '{status, loopWatchdog: .loopWatchdog.lastBeatAgeSeconds}'
curl -sS "$BASE/api/execution/status" | jq '{running, newEntriesAllowed, openTrades: (.openTrades|length), lastEntry, skipped: .skipped[-2:]}'
curl -sS "$BASE/api/ai/radar-health" | jq '{healthy, marketPhase, feed: {connected: .feed.connected, lastTickAgeMs: .feed.lastTickAgeMs}, cadence: .cadence|{buildLockHeld, lastFastCycleMs}}'
curl -sS "$BASE/api/ai/radar-funnel/$DATE" | jq '
  {detected, entered, blocked, sessionBlocks: (.sessionBlocks|length),
   gateReasons: [.rows[]? | .timeline[]? | select(.stage=="SELECTOR_GATE") | .reason] | group_by(.) | map({reason: .[0], n: length}),
   poolReasons: [.rows[]? | .timeline[]? | select(.stage=="SELECTOR_POOL") | .reason] | group_by(.) | map({reason: .[0], n: length}),
   mlBlocked: [.rows[]? | select(.blockers[]?=="reentry_ml_win_prob_low") | {key, mfe: .radarOutcome.mfePct, entered}]
  }'
curl -sS "$BASE/api/auto-trader/history/trades/closed?limit=5" | jq '[.trades[]? | {closedAt, side, strike, pnlInr}]'
```

---

## Map blocker reason → stuck step

| Reason (funnel / skipped) | Step | #676 would have helped? |
|---------------------------|------|-------------------------|
| `reentry_ml_win_prob_low` | **L6** | **No** — needs passport / fresh-base / policy change |
| `entry_timing_cold_*` / `entry_timing_late_*` | **L5** | **Partial** — 676 waive is for **failed_launch**, not all timing |
| `fake_explosion_trap_*` | **L5** | **No** — anti-FOMO (unless exempt lane applies) |
| `failed_launch` / structured launch | **L5/L6** | **Yes** — when `callAtmItmBase676Waive` true |
| `elite_score_*` / `elite_timing_*` | **L6** | **No** — quality stack |
| `launch_not_confirmed` (eligibility meta) | **L4/L3** | **Yes** — fix detection/readiness first |
| OTM / wrong strike | **L4** | **Yes** — pick ATM/ITM CE |
| `hard_block_*` / directional lock | **L6** | **Mirror CE/PE** per AGENTS.md |
| (no timeline, hot radar) | **L5 telemetry** or **L6 rankedOut** | Deploy / rank forensics |

---

## EOD: prove “stuck step” for the day (mandatory)

1. `GET /api/ai/eod-trade-report/$DATE` — captured vs missed MFE.  
2. `GET /api/ai/radar-funnel/$DATE` — entry vs re-entry reasons (pool vs gate).  
3. `python backend/scripts/blocker_audit_batch.py` — replay parity for **`reentry_ml_win_prob_blocked`**.  
4. `GET /api/ai/eod-local-base-replay/$DATE` — structural vs live-only gates.  
5. One hypothesis + at most one PR if AGENTS bar met.

---

## 26 Oct 2026 snapshot (evidence)

| Metric | Value |
|--------|--------|
| Funnel | 57 detected, 2 entered, 4 blocked with explicit blockers |
| Dominant explicit blocker | **`reentry_ml_win_prob_low`** (4 CE strikes, afternoon timeline) |
| Stuck step for those misses | **L6 SELECTOR_GATE**, after earlier win — not L4 #676 eligibility |
| Deploy commit (evening check) | `2a081d3` |

---

*Version: pipeline L0–L7 aligned with `best_trade_policy.call_atm_itm_base_capture_*`, `entry_timing.callAtmItmBase676Waive`, funnel stages `SELECTOR_POOL` / `SELECTOR_GATE`.*
