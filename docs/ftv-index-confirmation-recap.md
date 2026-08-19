# FTV Capture + Index Confirmation — Recap

_Last updated: 2026-08-19 (IST evening). Covers the work to catch sudden flat→vertical
(FTV) option lifts and the index-level confirmation behind them._

---

## 1. The idea in one line

A strike sits on the radar as **BUILDING**, then "suddenly something helps it go vertical."
That "something" is almost always the **index (NIFTY/SENSEX spot) thrusting**, not the option
tape (which lags). Catch the FTV **at the local base** by confirming the lift with independent
helpers — including the index move — instead of waiting for premium velocity to prove it.

---

## 2. Current state (what's live vs pending)

| Item | Status | Where |
|---|---|---|
| BUILDING→FTV **helper-confirmed lane** | **LIVE** (`commit 418f985`) | merged via PR #355 (squash took only 1st commit) |
| 9 pre-existing **test-failure fixes** | **PENDING merge** | PR #356 |
| Index **spike-history burst** confirmation | **PENDING merge** | PR #356 |
| Index **sustained-drift** confirmation | **PENDING merge** | PR #356 |

- Live deployment check: `GET https://www.jashuvatrade.xyz/api/deployment/status` → `commit`.
- Deploy is automated: merging to `main` triggers `.github/workflows/deploy-ec2.yml`
  (`deploy/ec2-update.sh` on EC2, then verifies the public deployment status endpoint).
- **PR #355** = `Catch BUILDING->FTV first lifts via helper-confirmed lane` (first commit only).
- **PR #356** = `FTV follow-up: green test suite + index spike-burst & sustained-drift`.

### Honest maturity level
- **Code**: works, 1354 tests pass.
- **Offline validation**: the sustained-drift signal fires at the exact base of the Aug 19 miss.
- **Live proof**: NOT yet demonstrated. No live session has run the full stack; the only proof
  so far is historical replay on the coarse REST archive (~1–3s), not live sub-second WS ticks.

---

## 3. Case study — SENSEX 76900 PE, 2026-08-19 (the miss we studied)

Source: live radar archive `radar-2026-08-19.zip` (`premium_tape.jsonl` has premium **and** spot
per tick; `alerts_tape.jsonl` has scored alerts). Archive tape covers **11:32–16:00**.

### Session facts
- Premium range **₹92.8 (V-base) → ₹191.9 (peak)**.
- Radar first saw the contract **11:34:58 at ₹178.15**; paper-track outcome **MFE +58.8%, MAE −40.4%**.
- Context at the rip: spot ~76,900, `spotChart=BEARISH`, `breadth=BEARISH`,
  `regime=TREND_EXPANSION`, `PCR=0.65`, `India VIX=11.34`, TQS 68.9.

### The causal driver: PE rips inversely with SENSEX spot
| time | SENSEX spot | 76900 PE |
|---|---|---|
| 14:15:41 | 76,897 | ₹152.7 (base) |
| 14:20:50 | 76,861 (−36) | ₹170.7 |
| 14:23:55 | 76,827 (−70) | ₹189.9 |
| 14:26:46 | 76,833 | **₹191.9 (peak)** |
| 14:35:46 | 76,984 (spot popped +150) | ₹116.5 (V-bottom) |

Cleanest fuel burst: **14:22:25 SENSEX 76,927 → 76,827 (−99 pts in 90s)**, PE **+6.5%** in lockstep.

### Why the system held it at BUILDING (micro-flip at 13:38:45–49, from `alerts_tape`)
- `13:38:44` WATCH, v3 0.83, **volSurge 1.0**
- `13:38:45` → **BUILDING**, v3 1.0, **volSurge 1.0→2.5** (volume awakening), tradeable
- `13:38:47` BUILDING, v3 1.99, score 45.9
- `13:38:49` BUILDING, **v9 3.13**, **ictFlatThenVertical=True**, score 61.6
- then velocity **faded within seconds** (v3 → −0.5), FTV flag dropped, spot snapped back.

Conclusion: the move was a **steady index grind with mean-reversion chop**, not a clean sustained
one-way rip — so the system correctly stayed cautious. The signal it was missing was reading the
**index thrust** as the trigger.

### Helpers that lift a strike (ranked by causal weight, from the data)
1. **Index (spot) thrust** — dominant driver (−60 to −100 pt SENSEX moves).
2. **Volume awakening** — volume bar spike flips WATCH→BUILDING (volSurge 1.0→2.5).
3. **Velocity spike** — v3 → ~2.0, v9 → ~3.1 on the thrust.
4. **Bearish chart/breadth alignment** — supports PUTs (regime TREND_EXPANSION, PCR 0.65).
5. **Flat→vertical structure** — FTV flag / quality ~70.

---

## 4. Index confirmation — the two new signals (PR #356)

### (a) Spike-history "burst"
A **cluster** of same-direction spot spikes in a short window (not a single blip).
`recent_index_spike_thrust(symbol, side)` → count / net% / burst flag.

### (b) Sustained drift (the Aug 19 fix)
Some FTVs are a **steady grind**, each 3s step below the sharp-spike bar. A longer per-symbol
index LTP buffer (every tick) + `recent_index_drift(symbol, side)` flag a confirmation when the
**NET same-direction spot move over a window** clears a threshold (net cancels chop).

Both feed: index board `confirming` → `building_lift_helpers` structure set → alert stamping
(`indexSpikeBurst`, `indexDrift`, `indexDriftNetPct`, …) → selector rank bonuses.

### Calibration + replay validation (real `recent_index_drift` on Aug 19 spot ticks)
- 45s net-move distribution: **median |move| = 0.0028%**; 95th-pct down = −0.0436%.
- Threshold **0.05% over 45s** fires **~6×/session** (18× separation from chop).
- **PUT-drift fires at 14:14:27 — the exact base of the leg that ran the PE ₹152→₹191.9**
  (also 14:22:25, 14:26:02, 14:26:33 through the rip). The sharp spike-burst alone did **not** fire.

---

## 5. Config flags added (all code-defaulted, gated)

```
# Helper-confirmed FTV lane (LIVE)
first_lift_helper_confirm_enabled = True
first_lift_helper_confirm_min_helpers = 3
first_lift_helper_strong_surge = 3.0
first_lift_helper_confirm_min_quality = 50.0
first_lift_helper_confirm_min_score = 45.0
first_lift_helper_confirm_min_velocity_3s = 1.2
first_lift_helper_confirm_min_velocity_9s = 0.6
building_rip_helper_override_worst_day = True

# Index spike-history burst (PR #356)
index_spike_history_enabled = True
index_spike_history_window_seconds = 45.0
index_spike_history_max = 40
index_spike_burst_min_count = 3
index_spike_burst_rank_bonus = 4.0

# Index sustained drift (PR #356)
index_drift_enabled = True
index_drift_history_seconds = 120.0
index_drift_window_seconds = 45.0
index_drift_min_move_pct = 0.05          # calibrated on Aug 19; confirm on live WS
index_drift_rank_bonus = 3.0
```

Pre-existing index tick monitor (already present): `index_tick_helpers_enabled`,
`index_tick_spike_abs_velocity_3s = 0.035`, `index_tick_align_abs_velocity_3s = 0.02`,
`index_tick_min_helpers_confirm = 2`, `index_tick_wake_building_cycle = True`.

---

## 6. Key files touched

| File | What |
|---|---|
| `backend/app/engines/ict_breakout_monitor.py` | `_helper_confirmed_lift`, `_option_led_first_lift_ok`, helper-confirmed lane in first-lift & building-rip readiness |
| `backend/app/engines/index_tick_helpers.py` | spike history + `recent_index_spike_thrust`, LTP buffer + `recent_index_drift`, burst/drift helpers |
| `backend/app/engines/building_lift_helpers.py` | `index_spike_burst` / `index_drift` in the structure set |
| `backend/app/engines/explosion_detector.py` | scan-time `moneyness` on `ExplosionEvent`, OTM non-tradeable guard, dead-flat WATCH drop, central index-helper stamping |
| `backend/app/engines/trade_selector.py` | option-led promotion, index burst/drift rank bonuses |
| `backend/app/engines/trade_ranking.py` | `armed_top_local` accepts confirmed FTV structure |
| `backend/app/engines/expiry_day_guards.py` | pass `flatVerticalQuality` into strict-rank-one |
| `backend/app/config.py` | all flags above |
| tests | `test_building_ftv_helper_confirmed.py`, `test_index_tick_helpers.py` (+ burst/drift), updated sizing/expiry/first-lift |

---

## 7. Open items / how to prove it live

1. **Merge PR #356 + deploy** (auto on merge to `main`). Confirm `deployment/status.commit` flips.
2. **Live session verification** — after an FTV sets up, pull the day's radar archive and check:
   - Was it entered **at the base** (low `localBaseMovePct`)?
   - Were `indexDrift` / `indexSpikeBurst` / helper stamps present at entry?
   - Did it capture the move (outcome MFE)?
3. **Threshold confirmation on live WS** — `index_drift_min_move_pct = 0.05` was tuned on the
   coarse REST archive; live sub-second ticks may warrant a small tweak. All gated by flags.
4. **Known limitation (by design)**: whipsaws that revert within the drift window net to ~0 and
   will NOT be chased — this protects against the oversized-loss reversals.

### Re-fetch the raw archive for any date
```
curl -s "https://www.jashuvatrade.xyz/api/ai/radar-archives" | python3 -m json.tool   # list dates
curl -s "https://www.jashuvatrade.xyz/api/ai/radar-archives/2026-08-19" -o radar.zip   # download
# unzip → premium_tape.jsonl (premium + spot per tick), alerts_tape.jsonl (scored alerts),
#         top_radars.json (best obs per contract + milestones + outcome)
```
Other useful endpoints: `/api/ai/missed-trades`, `/api/ai/radar-scorecard/{date}`,
`/api/auto-trader/history/{date}`, `/api/auto-trader/history/trades/closed`.
