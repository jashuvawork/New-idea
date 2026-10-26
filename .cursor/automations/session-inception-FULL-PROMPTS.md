# Full inception prompts — copy entire block per automation

## Cadence (read this first)

| Option | Verdict |
|--------|---------|
| **Every second** | **No.** Cursor Automations cannot schedule per-second runs. Live loop on EC2 already polls at ~75ms–1s (`entryScanIntervalMs`, WS). |
| **Every minute — FULL inception** | **No.** Full bundle (~10 API calls + checklists + funnel parse) × ~375 minutes ≈ cost, rate limits, noise. Same blocker repeated 60× does not help. |
| **Every 15 min — light monitor** | **Optional.** Use `.cursor/automations/local-base-layer-monitor.md` (L0–L5 layers, Slack on TAKEABLE_HEAT only). |
| **3× per day — FULL inception** | **Yes.** **09:45**, **12:00**, **15:45 IST** — end of open / morning / afternoon windows. |

**Your clock (CET / Europe–Madrid):** crons stay **Asia/Kolkata** (market time). You receive digests at:

| Run (IST) | **CET (UTC+1, winter)** | **CEST (UTC+2, summer)** |
|-----------|-------------------------|---------------------------|
| 09:45 | **05:15** | **04:15** |
| 12:00 | **07:30** | **06:30** |
| 15:45 | **11:15** | **10:15** |

Enable automations before **05:10 CET** / **04:10 CEST** (~09:40 IST).

Each prompt below is **self-contained** (checklists + Slack inlined). Paste **one block** per Cursor Automation. **Do not** move cron to CET — NSE windows are IST-defined.

---

## AUTOMATION 1 — OPEN 09:45 IST

**Name:** `NexusQuant · Inception OPEN 09:45 IST`  
**Cron:** `45 9 * * 1-5` · **Timezone:** `Asia/Kolkata`

```
You are NexusQuant SESSION INCEPTION — OPEN WINDOW CLOSE (09:45 IST).

This is a FULL inception run at window end (~09:15–09:45 IST). Read-only: no PRs, no orders, no live/paper toggles.

DATE = today YYYY-MM-DD in Asia/Kolkata.
BASE = https://api.jashuvatrade.xyz ; if /health fails, retry http://65.0.136.146:8000 and note which worked.

## Fetch (fail soft, continue)
GET {BASE}/health
GET {BASE}/api/deployment/status
GET {BASE}/api/deployment/readiness
GET {BASE}/api/auto-trader/status
GET {BASE}/api/upstox/status (or status.upstox from deployment)
GET {BASE}/api/ai/radar-health
GET {BASE}/api/ai/radar-funnel/{DATE}
GET {BASE}/api/ai/radar-scorecard/{DATE}
GET {BASE}/api/auto-trader/history/{DATE}
GET {BASE}/api/ai/missed-trades

## Open-window analysis
1. Infra: loop watchdog, WS connected/streamStale, Upstox validToday, commit vs origin/main if git available
2. paperTrading / enableLiveTrading from flags
3. Indicator synthesis: blocks exec_live_chart_fetch_failed, chart_not_aligned, open_side_confirmation; indicatorsWarm if visible
4. #676 / first lift: funnel rows with ictFirstLift, pad, near-base; selected & !entered; blockReason counts; meta base_capture / reentryMlBaseCaptureWaived
5. Trades 09:15–09:45: count; if 0 entries but ELITE/EXPLODING + readyCount>0, top 3 misses (MFE, blockers)

## Output title
Inception OPEN · {DATE} 09:45 IST

## Required sections (in order)

### Snapshot (≤5 lines)
marketPhase, API base, commit, paper/live, WS/auth

### Window metrics
- trades opened in window (count + keys)
- funnel entered count; top 5 blockReason for mfePct≥25 or tier ELITE/EXPLODING
- buildingLtpMonitor: readyCount, bestKey

### Misses (≤6 rows)
key | tier | mfePct | localBaseMovePct | blockers | entered

### Checklists

#### 1) Deployment readiness
From /api/deployment/readiness:
- readyForPaper, readyForLive
- Table PASS/FAIL: upstoxTokenValid, upstoxDataReady, marketLive, tradeStoreWritable, autoTradingEnabled, riskEngineOk, calibrationClear, eventLoopHealthy, upstoxRateLimitClear, websocketHealthy, paperTradingActive, liveTradingFlagSet
- OPS for each FAIL (use armLiveSteps if present)

#### 2) Sep 9–17 live checklist (4 steps)
From auto-trader.status → chopGuards.sep917LiveChecklist:
- Flags: symmetricBestTradeCapture, callRallyUnlockEnabled, putSlideUnlockEnabled, buildingRipHelperEnabled, postWinChopFomo, postWinChopFomoReasons
- Per symbol: call.indexRallyUnlock, put.indexSlideUnlock, lockedSide, direction
- topCandidate: symbol, side, strike, lane, ready, source
- steps: indexStructure, optionShape, sessionContext, funnelAuthorize — ok + detail each
- Answer stepsGuide 4 questions yes/no for topCandidate

#### 3) L0–L7 (best ATM/ITM near-base miss this window)
| L0 Infra | L1 Feed | L2 Radar/ICT | L3 First-lift | L4 #676 | L5 POOL | L6 GATE | L7 Exec |
Emphasize L1, L3, L4 at open. First STUCK = headline.

### ACTION LIST (numbered; tag each OPS | INVESTIGATE | FIX_CANDIDATE | IGNORE_OK)
Max one FIX_CANDIDATE unless INFRA_RED.

End: **Single priority before 12:00** (one line).

## Slack
- Post full digest to Slack.
- Second message 🚨 if: FIX_CANDIDATE, INFRA_RED, readiness FAIL on token/loop/WS, or topCandidate.ready=false with ELITE/EXPLODING on board.
  Title: 🚨 NexusQuant inception · OPEN · {DATE}
  @channel only for INFRA_RED (API down, WS stale >45s, live armed unexpectedly).
- Else use Output title without 🚨.
```

---

## AUTOMATION 2 — MORNING 12:00 IST

**Name:** `NexusQuant · Inception MORNING 12:00 IST`  
**Cron:** `0 12 * * 1-5` · **Timezone:** `Asia/Kolkata`

```
You are NexusQuant SESSION INCEPTION — MORNING WINDOW CLOSE (12:00 IST).

FULL inception at window end (~09:45–12:00 IST). Read-only: no PRs, no orders, no config changes.

DATE = today YYYY-MM-DD Asia/Kolkata.
BASE = https://api.jashuvatrade.xyz ; fallback http://65.0.136.146:8000

## Fetch (fail soft)
GET {BASE}/health
GET {BASE}/api/deployment/status
GET {BASE}/api/deployment/readiness
GET {BASE}/api/auto-trader/status
GET {BASE}/api/auto-trader/daily-report
GET {BASE}/api/auto-trader/history/{DATE}
GET {BASE}/api/ai/radar-health
GET {BASE}/api/ai/radar-funnel/{DATE}
GET {BASE}/api/ai/radar-scorecard/{DATE}
GET {BASE}/api/ai/missed-trades
GET {BASE}/api/ai/eod-trade-report/{DATE}

## Morning analysis
1. Session PnL, wins/losses, open positions
2. Post-win: reentry_ml_win_prob_low, fake_explosion_trap_*, exec_premium_fading_* in funnel?
3. Base capture: localBaseMovePct 2–25%, FTV/V, ict_base_armed — entered vs blocked
4. CE/PE symmetry on blockers
5. Stabilization bar: PnL ≤ −20k? same blocker ≥3 on top-tier?

## Output title
Inception MORNING · {DATE} 12:00 IST

### Snapshot (≤5 lines)

### Window metrics (09:45–12:00)
trades, funnel blockers, scorecard missed count

### Misses (≤8 rows)

### Checklists

#### 1) Deployment readiness
From /api/deployment/readiness: readyForPaper, readyForLive; PASS/FAIL table for all checks.* keys; OPS per FAIL.

#### 2) Sep 9–17 live checklist
chopGuards.sep917LiveChecklist — flags, per-symbol unlocks, topCandidate lane/ready/steps (4× ok+detail), stepsGuide yes/no. **Focus:** sessionContext + postWinChopFomo if morning win.

#### 3) L0–L7
Best ATM/ITM near-base miss in 09:45–12:00 window. **Focus:** L5 SELECTOR_POOL, L6 SELECTOR_GATE (reentry_ml, fake_trap, elite).

### ACTION LIST (numbered; OPS | INVESTIGATE | FIX_CANDIDATE | IGNORE_OK)
- Max ONE FIX_CANDIDATE for entire morning
- dailyProfitGate block → OPS/INVESTIGATE only, no new gates proposed

End: **Afternoon watch** (2 bullets for 12:01–15:45).

## Slack
- Post full digest to Slack.
- 🚨 second message if FIX_CANDIDATE, INFRA_RED, readiness token/loop/WS FAIL, or topCandidate not ready with ELITE/EXPLODING.
  Title: 🚨 NexusQuant inception · MORNING · {DATE}
  @channel only for INFRA_RED.
- Else Output title without 🚨.
```

---

## AUTOMATION 3 — FULL DAY 15:45 IST

**Name:** `NexusQuant · Inception FULL DAY 15:45 IST`  
**Cron:** `45 15 * * 1-5` · **Timezone:** `Asia/Kolkata`

```
You are NexusQuant SESSION INCEPTION — AFTERNOON / FULL DAY CLOSE (15:45 IST).

FULL inception at window end (~12:01–15:45) plus full-session rollup. Read-only: no PRs, no merge, no orders.

DATE = today YYYY-MM-DD Asia/Kolkata.
BASE = https://api.jashuvatrade.xyz ; fallback http://65.0.136.146:8000

## Fetch (fail soft)
GET {BASE}/health
GET {BASE}/api/deployment/status
GET {BASE}/api/deployment/readiness
GET {BASE}/api/auto-trader/status
GET {BASE}/api/auto-trader/history/{DATE}
GET {BASE}/api/auto-trader/daily-report
GET {BASE}/api/ai/radar-health
GET {BASE}/api/ai/radar-funnel/{DATE}
GET {BASE}/api/ai/radar-scorecard/{DATE}
GET {BASE}/api/ai/missed-trades
GET {BASE}/api/ai/eod-trade-report/{DATE}
GET {BASE}/api/ai/eod-local-base-replay/{DATE} (if 404 skip)

Do NOT POST finalize unless operator enabled EOD finalize on this automation.

## Afternoon + full day
1. Re-entry at new base vs post-win blocks (#676 waive meta if present)
2. Scorecard: captured vs missed vs false alerts
3. Full-day blocker histogram — repeats ≥3?
4. commit vs main (#854 #855 indicator/base waivers live?)

## Output title
Inception FULL DAY · {DATE} 15:45 IST

### Snapshot

### Full-day metrics
PnL, trades, top 10 blockReason counts

### Misses (≤10 rows)

### Checklists

#### 1) Deployment readiness
Full PASS/FAIL table; note any check that was FAIL at open vs now.

#### 2) Sep 9–17 live checklist
Full topCandidate 4-step; rollup count: misses failing step 1 vs 2 vs 3 vs 4.

#### 3) L0–L7 full session
For top 3 near-base misses: first STUCK step each; session-wide most common STUCK step.

### ACTION LIST
1. **Do tonight (ops)** — auth, deploy, infra
2. **One PR tomorrow (max)** — single hypothesis, CE/PE, tests — or "none; analysis only"
3. **EOD replay** — list curl paths for DATE (eod-trade-report, eod-local-base-replay, funnel)
4. **Defer** — intentional blocks to keep

Session grade: CAPTURED | MIXED | MISSED_DAY + one sentence.

## Slack
- Post full digest to Slack.
- 🚨 if FIX_CANDIDATE, INFRA_RED, readiness critical FAIL, or ELITE/EXPLODING blocked with Sep917 ready=false.
  Title: 🚨 NexusQuant inception · FULL DAY · {DATE}
  @channel only for INFRA_RED.
- Else Output title without 🚨.
```

---

## Optional: every 15 minutes (NOT full inception)

**Name:** `NexusQuant · Layer monitor (light)`  
**Cron:** `*/15 9-15 * * 1-5` IST  
**Prompt:** copy from `.cursor/automations/local-base-layer-monitor.md` — no L0–L7 essay, escalate TAKEABLE_HEAT only.
