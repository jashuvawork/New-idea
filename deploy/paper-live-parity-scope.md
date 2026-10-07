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

## Still different (cannot fully clone)

- **Broker fill price & latency** — live uses Upstox; paper uses LTP ± optional slippage sim
- **Order reject / partial fill** — paper sim assumes fill; live may not
- **Market tape** — Oct 1 / Oct 5 are references; each session’s candidates differ
- **Capital book** — same *rules*, different lots if live book ≠ paper reference (e.g. ₹50k vs ₹150k)

## HUD

`GET /api/deployment/status` → `flags.entryGatesMatchPaper`, `flags.tradingRulesMatchPaper`, `livePaperProfile.sizesFromPaperBook`.
