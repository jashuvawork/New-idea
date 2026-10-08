# FTV policy audit (Frozen October / live)

## Production book (Oct 2026)

| Switch | Typical prod (Sep917 / Frozen Oct) |
|--------|--------------------------------------|
| `ftv_elite_top_only_enabled` | **false** (`Settings` default; overlays do not enable it) |
| `top_moments_only_enabled` | **false** on Sep917 legacy summary |
| `top_ftv_a_enabled` | **true** (fallback lanes exist but only run when FTV elite-top is on) |

**Implication:** Intraday **`SELECTOR_GATE` / `elite_signal`** on today’s funnel is **not** `ftv_authorization_policy` failing — it is **causal grade `REJECT`** with the **first ranking tag** (`elite_signal`) logged as the gate reason.

## When `ftv_elite_top_only_enabled=true`

1. **`ftv_authorization_policy`** must pass (modes: `S_STRICT`, `TOP_FTV_A`, `WINNER_LOCAL_BASE`, `BUILDING_RIP_FTV`, pad lanes, etc.).
2. **`requires_ftv`** — needs flat→vertical + active breakout, armed/elite/v-rip/building rip, pad lane, or **first lift + partial structure** (not bare ELITE tier alone).
3. **Expiry worst-day floor** — extra quality/score/v3 floors when day mode is expiry worst.
4. **Selector order (fixed)** — if FTV policy **passed**, candidate is kept even when causal grade is `REJECT` (policy is authoritative when enabled).

## Observability (fixed)

- Funnel **`SELECTOR_GATE`** now uses **`selector_rejection_reason()`** — prefers **`penalties[].code`** (e.g. `negative_velocity`) over **`elite_signal`**.

## Verify on prod (read-only)

```bash
curl -sS https://api.jashuvatrade.xyz/api/deployment/readiness | jq '.tradingPolicy.allowedAuthorizationModes, .checks'
curl -sS "https://api.jashuvatrade.xyz/api/ai/radar-funnel/$(date +%Y-%m-%d)" | jq '.rows[0].timeline[-5:]'
```

Look for `ftv_elite_top_only_*` in pretrade blocks only when FTV elite-top is enabled in env.
