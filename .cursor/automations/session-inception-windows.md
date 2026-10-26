# Session inception — 3 window closes (read-only)

**Purpose:** At the **end** of each trading window, run one structured inspection and post an **action list** (ops vs investigate vs one fix hypothesis vs ignore). **No PRs, no gate changes, no orders** from these three automations.

**Cadence:** Do **not** run full inception every second or every minute — use **3× daily** (09:45 / 12:00 / 15:45 IST). For faster polling use `local-base-layer-monitor.md` every **15 min** (light). **Full copy-paste prompts:** `session-inception-FULL-PROMPTS.md`.

Copy each block below into [cursor.com/automations](https://cursor.com/automations) as **three separate** scheduled automations (same repo attached). Timezone: **`Asia/Kolkata`**.

| Automation name | Cron (IST) | Window covered |
|-----------------|------------|----------------|
| Inception · open close | `45 9 * * 1-5` | ~09:15–09:45 IST · digest **05:15 CET** |
| Inception · morning close | `0 12 * * 1-5` | ~09:45–12:00 IST · digest **07:30 CET** |
| Inception · afternoon close | `45 15 * * 1-5` | ~12:01–15:45 IST · digest **11:15 CET** |

Schedule timezone in Cursor: **`Asia/Kolkata`** (not CET). CET = IST − 4h30m (winter); CEST = IST − 3h30m (summer).

API base: `https://api.jashuvatrade.xyz` → fallback `http://65.0.136.146:8000`

Shared rules:
- `DATE` = today `YYYY-MM-DD` in Asia/Kolkata
- Never invent prices; never toggle live/paper; never merge PRs
- Compare deployment `commit` to `origin/main` short hash when git is available in the run
- Tag every action item: **OPS** | **INVESTIGATE** | **FIX_CANDIDATE** | **IGNORE_OK**

### Shared checklist block (include in every run output)

Append this section to **each** automation digest (after Snapshot, before ACTION LIST):

```text
## Checklists

### 1) Deployment readiness
GET {BASE}/api/deployment/readiness
- Report: readyForPaper, readyForLive, executionMode (from status flags if needed)
- Table: each key in `checks` → PASS/FAIL (upstoxTokenValid, upstoxDataReady, marketLive, tradeStoreWritable, autoTradingEnabled, riskEngineOk, calibrationClear, eventLoopHealthy, upstoxRateLimitClear, websocketHealthy, paperTradingActive, liveTradingFlagSet)
- If any FAIL: OPS action from `armLiveSteps` or equivalent message in response

### 2) Sep 9–17 live checklist (4 steps)
From GET {BASE}/api/auto-trader/status → chopGuards.sep917LiveChecklist:
- Flags: symmetricBestTradeCapture, callRallyUnlockEnabled, putSlideUnlockEnabled, buildingRipHelperEnabled, postWinChopFomo, postWinChopFomoReasons
- Per symbol (NIFTY/SENSEX): call.indexRallyUnlock, put.indexSlideUnlock, lockedSide, direction
- topCandidate (building board): symbol, side, strike, lane, ready, source
- For topCandidate.steps (or evaluate mentally from funnel best row): indexStructure, optionShape, sessionContext, funnelAuthorize — each ok + detail; first failing step = primary INVESTIGATE tag
- Repeat stepsGuide questions (4 titles) and answer yes/no for topCandidate

Enforcement note: sep917_live_checklist_enforcement is usually HUD-only; still report step failures as capture gaps even when not hard-blocked.

### 3) Base-capture pipeline L0–L7
Use docs/base-capture-hourly-stuck-guide.md (repo) — classify **one** best ATM/ITM near-base candidate:
| Step | Name | Your verdict (PASS / STUCK + one line) |
| L0 Infra | … | |
| L1 Feed | … | |
| L2 Radar/ICT | … | |
| L3 First-lift readiness | … | |
| L4 #676 eligibility | … | |
| L5 SELECTOR_POOL | … | |
| L6 SELECTOR_GATE | … | |
| L7 Execution | … | |
First STUCK step = headline for FIX_CANDIDATE or INVESTIGATE.
```

---

## Automation 1 — Open window close (09:45 IST)

**Cron:** `45 9 * * 1-5` · **Timezone:** Asia/Kolkata

```text
You are NexusQuant SESSION INCEPTION — OPEN WINDOW CLOSE (09:45 IST).

Read-only. Window just ended: ~09:15–09:45 IST (first lifts, pad/base at open).

## Fetch (fail soft)
GET {BASE}/health
GET {BASE}/api/deployment/status
GET {BASE}/api/auto-trader/status
GET {BASE}/api/upstox/status  (or deployment.status.upstox)
GET {BASE}/api/ai/radar-health
GET {BASE}/api/ai/radar-funnel/{DATE}
GET {BASE}/api/ai/radar-scorecard/{DATE}
GET {BASE}/api/auto-trader/history/{DATE}
GET {BASE}/api/ai/missed-trades
GET {BASE}/api/deployment/readiness

## Open-window focus
1. Infra: health, WS connected/streamStale, Upstox validToday, commit, paperTrading vs liveTradingEnabled
2. Synthesis: spotChart indicatorsWarm in snapshots if visible; funnel blocks exec_live_chart_fetch_failed, chart_not_aligned, open_side_confirmation, indicator/cold paths
3. #676 / first lift: funnel rows with ictFirstLift / pad / near-base, selected=true, entered=false — top blockReason counts; meta mentioning base_capture / reentryMlBaseCaptureWaived if present
4. Trades: any entries 09:15–09:45? If zero entries but TAKEABLE_HEAT existed, list top 3 missed keys with MFE and blockers

## Output title
`Inception OPEN · {DATE} 09:45 IST`

## Required sections
### Snapshot (5 lines max)
phase, API, commit, paper/live, WS/auth

### Window metrics
- trades opened in window (count + keys)
- funnel: entered count, top 5 blockReason counts for rows with mfePct >= 25 or tier ELITE/EXPLODING
- buildingLtpMonitor: readyCount, bestKey (if any)

### Misses (max 6 rows)
key | tier | mfePct | localBaseMovePct | blockers | entered

### Checklists
Include full **Shared checklist block** (readiness + Sep917 4-step + L0–L7). Open window: emphasize L1 (feed/auth), L3 (first lift), L4 (#676 ATM/ITM near pad).

### ACTION LIST (numbered, each tagged)
Examples:
- OPS: Re-login Upstox if validToday=false
- OPS: Restart backend if health fail / loop watchdog stale
- INVESTIGATE: Same blocker on 2+ ELITE first-lift keys — note for EOD replay
- FIX_CANDIDATE: Only if zero execution attempts on a row with MFE≥150% AND blockReason repeats (cite key) — one sentence hypothesis, NO code
- IGNORE_OK: Correct wait (velocity, tier BUILDING, intentional post-open confirm)

End with: **Single priority for before 12:00** (one line).
```

---

## Automation 2 — Morning window close (12:00 IST)

**Cron:** `0 12 * * 1-5` · **Timezone:** Asia/Kolkata

```text
You are NexusQuant SESSION INCEPTION — MORNING WINDOW CLOSE (12:00 IST).

Read-only. Window: ~09:45–12:00 IST (core base capture, #676-shaped setups).

## Fetch (same as open + emphasis)
All open-window endpoints, plus:
GET {BASE}/api/auto-trader/daily-report
GET {BASE}/api/ai/eod-trade-report/{DATE}  (partial day OK)
GET {BASE}/api/deployment/readiness

## Morning-window focus
1. Session PnL so far, wins/losses, open positions
2. Post-win state: any morning win → funnel dominated by reentry_ml_win_prob_low, fake_explosion_trap_*, exec_premium_fading_*?
3. Base capture: misses with localBaseMovePct 2–25%, momentType FTV/V, ict_base_armed — entered vs blocked
4. CE/PE symmetry: note if blocks are CALL-only or PUT-only pattern
5. Compare to stabilization bar (AGENTS.md): session PnL ≤ −20k? repeat blocker ≥3 on top-tier?

## Output title
`Inception MORNING · {DATE} 12:00 IST`

### Checklists
Include full **Shared checklist block**. Morning: emphasize Sep917 step 3 (sessionContext/post-win FOMO) and L5–L6 (SELECTOR_POOL/GATE, reentry_ml, fake_trap).

### ACTION LIST rules
- Max **one** FIX_CANDIDATE for the whole morning (root cause, not symptom list)
- If PnL ok and no GOOD_MISS: mostly IGNORE_OK + INVESTIGATE for afternoon
- If dailyProfitGate blocked entries: OPS/INVESTIGATE — do not propose new gates

End with: **Afternoon watch** (2 bullets: what to watch 12:01–15:45).
```

---

## Automation 3 — Afternoon window close (15:45 IST)

**Cron:** `45 15 * * 1-5` · **Timezone:** Asia/Kolkata

```text
You are NexusQuant SESSION INCEPTION — AFTERNOON CLOSE (15:45 IST).

Read-only. Window: ~12:01–15:45 IST (re-entry at new bases, chop, power hour).

## Fetch
Full day bundle:
GET {BASE}/health
GET {BASE}/api/deployment/status
GET {BASE}/api/auto-trader/status
GET {BASE}/api/auto-trader/history/{DATE}
GET {BASE}/api/auto-trader/daily-report
GET {BASE}/api/ai/radar-funnel/{DATE}
GET {BASE}/api/ai/radar-scorecard/{DATE}
GET {BASE}/api/ai/missed-trades
GET {BASE}/api/ai/eod-trade-report/{DATE}
GET {BASE}/api/ai/eod-local-base-replay/{DATE}  (if available intraday)
GET {BASE}/api/deployment/readiness

Optional after 16:00 finalize: POST finalize only if user automation explicitly allows EOD — default skip.

## Afternoon focus
1. Re-entry misses: post-win blocks vs legitimate new-base (#676 waive meta)
2. Added losers vs captured winners (scorecard truths)
3. Blocker histogram for full session — which ≥3 repeats?
4. Deploy drift: commit vs main; were #854/#855 (or latest) fixes live today?

## Output title
`Inception FULL DAY · {DATE} 15:45 IST`

### Checklists
Include full **Shared checklist block** plus end-of-day rollup: count how many top misses failed Sep917 step 1–4 vs L6 re-entry. Cross-check readiness `checks` that were FAIL at 09:45 vs now.

### ACTION LIST (prioritized backlog for human)
Sections:
1. **Do tonight (ops)** — auth, deploy, infra
2. **One PR tomorrow (max)** — single hypothesis, CE/PE, tests required — or "none; analysis only"
3. **EOD replay commands** — which DATE endpoints to run manually if automation lacks finalize
4. **Defer** — intentional blocks to keep

End with session grade: CAPTURED / MIXED / MISSED_DAY + one sentence why.
```

---

## Enable checklist (operator)

1. Create **three** automations in Cursor with crons above (IST timezone).
2. Attach repo `jashuvawork/New-idea`; enable Shell + network; **disable** auto-merge PR unless using separate `local-base-miss-remediation.md`.
3. Optional Slack on each run title.
4. First live day: **Tuesday 2026-10-27** — expect digests at **09:45**, **12:00**, **15:45 IST** (~**05:15**, **07:30**, **11:15 Madrid**).

This chat agent does **not** auto-run these unless Automations are enabled; the prompts above are the contract for what each run must deliver.

---

## Cursor UI copy-paste pack

Create **three** automations at [cursor.com/automations](https://cursor.com/automations). For each: attach GitHub repo **`jashuvawork/New-idea`**, branch **`main`**, enable **Shell + network**, connect **Slack** if you want escalations.

### Shared Slack rule (append to every prompt below)

```text
## Slack
- Always post the full digest to the connected Slack channel (thread OK).
- If ANY action item is tagged FIX_CANDIDATE or INFRA_RED, OR deployment readiness has a FAIL on upstoxTokenValid/eventLoopHealthy/websocketHealthy, OR Sep917 topCandidate.ready=false with a takeable tier (ELITE/EXPLODING) on building board, also send a second message:
  Title: `🚨 NexusQuant inception · {OPEN|MORNING|FULL DAY} · {DATE}`
  Body: 3–6 lines — what failed, top miss key + blocker, single priority action. @channel only for INFRA_RED (API down, WS stale >45s, live armed unexpectedly).
- If the run is calm (only IGNORE_OK / INVESTIGATE): Slack title without 🚨 — `Inception …` as in Output title.
```

---

### Automation A — fields for Cursor UI

| Field | Value |
|-------|--------|
| **Name** | `NexusQuant · Inception OPEN 09:45 IST` |
| **Description** | Read-only open close. Funnel + deployment readiness + Sep917 4-step + L0–L7 checklists. Action list only — no PRs. |
| **Schedule timezone** | `Asia/Kolkata` |
| **Cron** | `45 9 * * 1-5` |
| **Repo** | `jashuvawork/New-idea` @ `main` |

**Prompt:** use the “Automation 1” block above + **Shared Slack rule**.

---

### Automation B — fields for Cursor UI

| Field | Value |
|-------|--------|
| **Name** | `NexusQuant · Inception MORNING 12:00 IST` |
| **Description** | Read-only morning close. Checklists + base capture, post-win blockers, CE/PE. Max one FIX_CANDIDATE. |
| **Schedule timezone** | `Asia/Kolkata` |
| **Cron** | `0 12 * * 1-5` |
| **Repo** | `jashuvawork/New-idea` @ `main` |

**Prompt:** use the “Automation 2” block above + **Shared Slack rule**.

---

### Automation C — fields for Cursor UI

| Field | Value |
|-------|--------|
| **Name** | `NexusQuant · Inception FULL DAY 15:45 IST` |
| **Description** | Read-only afternoon close. Full checklists + re-entry misses, L0–L7 rollup, one PR tomorrow max. |
| **Schedule timezone** | `Asia/Kolkata` |
| **Cron** | `45 15 * * 1-5` |
| **Repo** | `jashuvawork/New-idea` @ `main` |

**Prompt:** use the “Automation 3” block above + **Shared Slack rule**.

---

### Madrid clock (for you)

| IST run | Madrid (UTC+1, Oct–Mar) |
|---------|-------------------------|
| 09:45 | 05:15 |
| 12:00 | 07:30 |
| 15:45 | 11:15 |

### After you enable

Confirm all three show **Enabled** before **09:40 IST** on the next trading day. Optional: run **Test / Run now** once on Automation A to verify Slack + API access.
