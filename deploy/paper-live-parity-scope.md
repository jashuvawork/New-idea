# Paper ↔ live parity scope (Frozen October)

## Mirrored on live when `entryGatesMatchPaper` / `tradingRulesMatchPaper` is true

- Entry & selection gates (pad, timing CHASE, pretrade, directional lock, symmetric capture helpers)
- Sizing from `FALLBACK_CAPITAL_INR` book — not Upstox margin (`should_use_live_broker_capital` false)
- Live-only narrowings off: best-trades-only, worst-day live block, chop-live wire, structural hold INR bypass
- Live-only early-fail scratch exits off (`live_early_fail`, `chop_live_early_fail` when paper rules active)
- Session force-flat at power-hour end (live + paper parity / frozen stack)
- Adaptive exit plans on open legs (shared path)

## Legacy live-only stack (hard-disabled on Frozen Oct)

The old ₹10k narrow profile (`env.live-10k.overlay`: grade-S gate, structural hold, chop-live wire, Upstox margin sizing) runs **only** when `LEGACY_LIVE_NARROW_STACK_ENABLED=true` **and** Frozen October is off. It cannot be combined with `env.october-frozen.overlay` (go-live script and env audit refuse).

HUD: `livePaperProfile.legacyLiveNarrowStackActive`.

## Rule-branch audit (Phase 2)

Live **rule** forks must use `trading_rules_match_paper` / `legacy_live_narrow_stack_active`, not bare `enable_live_trading`. Order placement uses [`backend/app/engines/execution_backend.py`](../backend/app/engines/execution_backend.py) (`submit_entry_order` / `submit_exit_order`) — the only swap between Upstox and paper broker sim.

Tests: `backend/tests/test_enable_live_trading_rule_parity.py`, `backend/tests/test_execution_backend.py`, `backend/tests/test_paper_live_full_parity_guards.py`.

Pretrade `armed_base_shallow_launch_blocked` (chop-live naming) is **skipped** when `trading_rules_match_paper` — same Oct armed-base path as paper.

**Pre-entry blocks inert under `tradingRulesMatchPaper` (Frozen Oct mirror live):**

| Gate | Module |
|------|--------|
| Chop-live wire (entry, second leg, session lift narrow) | `chop_live_guards.py` |
| Whipsaw session pause | `whipsaw_guards.py` |
| Power-hour top-only session block | `power_hour_guards.py` |
| Expiry worst-day declining halt | `expiry_day_guards.py` |
| Live best-trades-only order wire | `live_best_trades.py` |
| Worst-day blocks live trading | `worst_day_guard.py` |
| Sep917 four-step checklist (even if enforcement flag mis-set) | `sep917_live_checklist.py` |
| Live-entry-score **floor** for ELITE/EXPLODING ≥ min explosion score | `live_entry_score.py` (chase/dump guards still apply) |
| Selector REJECT grade for hot ELITE/EXPLODING | `trade_selector.py` `oct_keep` |
| Sep917 OTM `tradeable` wipe on open rip ELITE (score ≥90, v-rip/armed/first-lift) | `open_rip_selector.py` + `explosion_detector.py` stamp |
| Negative v3 on ELITE **with launch context** (Oct 1 paper) | `oct_paper_elite_rip_context()` — open window or small lift; **blocks late chase** after 09:45 |
| WS explosion refresh cadence | `effective_ws_overlay_interval_ms()` — no 1s floor when `LATENCY_MODE=aggressive` |

Use `legacy_live_entry_narrowings_active()` instead of bare `enable_live_trading` when adding new live-only rule forks.

## Still different (cannot fully clone)

- **Broker fill price & latency** — live uses Upstox; paper uses LTP + point slippage; **paper-live parity sim** may add `paper_live_parity_market_slippage_pct` (config) for closer PnL — does not change entry gates
- **Order reject / partial fill** — paper sim assumes fill; live may not
- **Market tape** — Oct 1 / Oct 5 are references; each session’s candidates differ
- **Capital book** — same *rules*, different lots if live book ≠ paper reference (e.g. ₹50k vs ₹150k)

## HUD

`GET /api/deployment/status` → `flags.entryGatesMatchPaper`, `flags.tradingRulesMatchPaper`, `livePaperProfile.sizesFromPaperBook`.
