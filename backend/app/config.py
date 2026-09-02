"""NexusQuant configuration — all settings from environment."""

import os
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Cadence presets — explicit env vars (e.g. ENTRY_SCAN_INTERVAL_MS) override preset values.
LATENCY_PRESETS: dict[str, dict[str, Any]] = {
    "low": {
        "market_poll_interval_ms": 300,
        "market_poll_interval_ws_ms": 75,
        "entry_scan_interval_ms": 1000,
        "expiry_entry_scan_interval_ms": 500,
        "explosion_open_scan_interval_ms": 750,
        "tick_wake_debounce_ms": 15,
        "snapshot_cache_interval_ms": 150,
        "ws_snapshot_cache_interval_ms": 600,
        "sse_heartbeat_seconds": 0.5,
        "tick_snapshot_interval_ms": 75,
    },
    "aggressive": {
        "market_poll_interval_ms": 250,
        "market_poll_interval_ws_ms": 50,
        "entry_scan_interval_ms": 500,
        "expiry_entry_scan_interval_ms": 350,
        "explosion_open_scan_interval_ms": 400,
        "tick_wake_debounce_ms": 10,
        "snapshot_cache_interval_ms": 100,
        "ws_snapshot_cache_interval_ms": 400,
        "sse_heartbeat_seconds": 0.5,
        "tick_snapshot_interval_ms": 50,
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "NexusQuant"
    environment: str = "development"
    commit_sha: str = "dev"

    # Upstox
    upstox_api_key: str = ""
    upstox_api_secret: str = ""
    upstox_redirect_uri: str = "http://localhost:8000/api/upstox/callback"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Postgres (optional)
    postgres_url: str = ""

    # News intelligence. "auto" combines Upstox's instrument/position News API
    # with Finnhub global cues when configured; either source can operate alone.
    news_provider: Literal["auto", "upstox", "finnhub", "none"] = "auto"
    finnhub_api_key: str = ""
    news_intraday_max_age_minutes: int = 360
    news_next_session_max_age_hours: int = 36
    news_upstox_positions_enabled: bool = True

    # Safety
    enable_live_trading: bool = False
    paper_trading: bool = True
    auto_trading_enabled: bool = True
    shadow_trade_all_signals: bool = True
    # Live: skip INR force-stops / scratch exits — let open trades hit structural SL.
    live_hold_to_structural_sl: bool = True
    # Live chop guards — hard blocks at order wire + early-fail exits on worst/chop days.
    chop_live_guards_enabled: bool = True
    chop_live_block_immature_local_base: bool = True
    chop_live_block_premium_5m_fade: bool = True
    chop_live_premium_5m_fade_min_mom_pct: float = -0.12
    chop_live_second_leg_block_enabled: bool = True
    chop_live_second_leg_cooldown_seconds: int = 900
    chop_live_early_fail_exit_enabled: bool = True
    chop_live_early_fail_min_hold_seconds: int = 30
    chop_live_early_fail_max_hold_seconds: int = 180
    chop_live_early_fail_max_best_points: float = 0.5
    chop_live_early_fail_min_loss_points: float = 3.0
    chop_live_early_fail_max_velocity_3s: float = 0.0
    live_broker_reconciliation_enabled: bool = True
    # Live worst/chop: session lift must NOT bypass worst-day live blocks.
    chop_live_disable_session_lift: bool = True
    # Hard block all live explosion entries on identified worst/chop days (₹10k live).
    chop_live_hard_block_worst_day: bool = True
    # Block faded-vertical-rip and extended session chase at live order wire.
    chop_live_block_faded_rip: bool = True
    chop_live_block_extended_chase: bool = True
    chop_live_extended_chase_min_session_move_pct: float = 28.0
    chop_live_min_trusted_local_base_pct: float = 15.0
    # Live best-trades-only — strict real-money quality bar (₹10k book).
    live_best_trades_only_enabled: bool = True
    live_best_trades_min_grade: str = "S"
    live_best_trades_min_explosion_score: float = 200.0
    live_best_trades_tiers_csv: str = "ELITE,EXPLODING"
    live_best_trades_require_first_lift: bool = True
    live_best_trades_min_local_base_pct: float = 15.0
    live_best_trades_require_chart_aligned: bool = True
    live_max_open_positions: int = 1
    live_max_same_side_positions: int = 1
    live_pause_after_session_losses: int = 1
    live_disable_session_lift: bool = True
    live_early_fail_exit_enabled: bool = True
    live_early_fail_min_hold_seconds: int = 45
    live_early_fail_max_hold_seconds: int = 240
    live_early_fail_max_best_points: float = 1.0
    live_early_fail_min_loss_points: float = 2.5
    live_early_fail_max_velocity_3s: float = 0.5
    # Legacy flag — milestone is advisory-only and never blocks live arming.
    live_milestone_required: bool = False

    # Latency profile — normal uses field defaults; low/aggressive apply cadence presets
    latency_mode: Literal["normal", "low", "aggressive"] = "low"

    # Data cadence — sub-second when WebSocket active; ms intervals override *_seconds
    market_poll_seconds: int = 1
    snapshot_cache_seconds: int = 1
    market_poll_interval_ms: int = 300
    market_poll_interval_ws_ms: int = 75
    tick_snapshot_interval_ms: int = 75
    ws_snapshot_cache_interval_ms: int = 2000  # full REST snapshot TTL when WS feed is active
    snapshot_cache_interval_ms: int = 150
    tick_wake_debounce_ms: int = 15
    tick_fast_exit_enabled: bool = True
    trade_mark_persist_seconds: float = 2.0
    entry_scan_interval_ms: int = 1000
    expiry_entry_scan_interval_ms: int = 500
    # Runner velocity compares consecutive snapshots only while the feed is fresh.
    runner_velocity_history_max_age_seconds: float = 15.0
    # Cap full REST rebuild so background monitor never stalls UI for minutes.
    full_rest_rebuild_timeout_seconds: float = 25.0
    full_rest_min_seconds: float = 45.0
    full_rest_backoff_slow_ms: float = 15000.0
    full_rest_backoff_seconds: float = 75.0
    expiry_atm_tier_velocity_mult: float = 0.85
    aligned_explosion_rip_bypass_enabled: bool = True
    aligned_explosion_rip_min_score: float = 45.0
    aligned_explosion_rip_min_velocity_3s: float = 2.0
    aligned_explosion_rip_min_velocity_9s: float = 3.0
    aligned_explosion_rip_interval_seconds: int = 30
    directional_lock_aligned_rip_bypass_enabled: bool = True
    tick_overlay_max_age_seconds: float = 1.0
    news_cache_seconds: int = 300  # dashboard + engine refresh cadence (5 min)
    background_market_monitor_enabled: bool = True

    # Event-loop hang recovery — Aug6: TCP:8000 open but /health never answered.
    # Heartbeat task + daemon thread exits the process so Docker restarts it.
    event_loop_watchdog_enabled: bool = True
    event_loop_watchdog_stale_seconds: float = 20.0
    event_loop_watchdog_check_seconds: float = 2.0
    event_loop_watchdog_beat_interval_seconds: float = 1.0
    event_loop_watchdog_grace_seconds: float = 45.0

    # Cursor Composer 2.5 — session market monitor + trading advisory
    composer_monitor_enabled: bool = True
    composer_monitor_use_ai: bool = True
    composer_monitor_interval_seconds: int = 180
    composer_on_new_trade: bool = True

    # Interval AI market analysis — stored reports for missed-move post-mortems
    ai_analysis_monitor_enabled: bool = True
    ai_analysis_monitor_interval_seconds: int = 120
    ai_analysis_monitor_use_ai: bool = True

    # EOD next-day playbook — generated after 15:20 IST
    eod_playbook_enabled: bool = True
    eod_playbook_start_hour: int = 15
    eod_playbook_start_minute: int = 20
    eod_playbook_use_ai: bool = True
    # EOD learning is DISABLED by default. It distilled radar OUTCOMES (mfe/mae) into a
    # knowledge profile, but that pipeline did NOT re-run the live entry gate stack, so its
    # numbers/recommendations did not reflect real live behaviour. Applying an unvalidated
    # learning loop to live risk is off until it can be validated against the actual gates.
    # The code remains, dormant, behind these flags. Trading runs purely on the deterministic
    # detector + gates.
    eod_learning_enabled: bool = False
    eod_learning_real_leg_min_mfe_pct: float = 50.0
    eod_learning_cleanup_enabled: bool = False
    eod_learning_raw_retention_days: int = 7
    # Do NOT apply any learned value to live entries/exits/sizing.
    eod_learning_apply_enabled: bool = False
    eod_learning_apply_min_samples: int = 5
    # Entry-side loop: tighten the ELITE/EXPLODING near-base entry ceiling toward the learned
    # per-moment value (tighten-only), but never below this floor so genuine near-base first
    # lifts still qualify. Biases entries nearer the local base without over-blocking.
    eod_learning_near_base_floor_pct: float = 25.0
    cursor_api_key: str = ""
    cursor_api_base_url: str = "https://api.cursor.com"
    cursor_chat_completions_path: str = "/v1/chat/completions"
    cursor_http_auth: str = "bearer"  # bearer | basic
    cursor_composer_model: str = "composer-2.5"
    cursor_composer_use_standard_tier: bool = True
    cursor_composer_runtime: str = "cloud"  # cloud | local — cloud for Docker/EC2
    cursor_composer_workspace: str = "/app"
    composer_temperature: float = 0.2
    composer_max_tokens: int = 1200

    # Upstox WebSocket real-time feed + SSE push to UI
    upstox_ws_enabled: bool = True
    upstox_ws_mode: str = "ltpc"  # ltpc | full | full_d30 | option_greeks
    upstox_ws_reconnect_seconds: int = 5
    upstox_ws_resubscribe_seconds: int = 30
    tick_snapshot_seconds: int = 1  # legacy; tick_snapshot_interval_ms preferred
    market_poll_seconds_ws: int = 1  # legacy; market_poll_interval_ws_ms preferred
    sse_enabled: bool = True
    sse_heartbeat_seconds: float = 0.5

    # Upstox rate limiting / caching
    # 160ms ≈ 6 req/s — well under Upstox's 25 req/s ceiling; cuts the full-rebuild
    # throttle floor vs the old 250ms. A 429 auto-doubles the interval (recovery), so
    # this stays self-protecting.
    upstox_min_request_interval_ms: int = 160
    # Market-quote batch size — endpoint accepts up to 500 keys. 100 lets NIFTY(52)/
    # SENSEX(30) constituents fetch in ONE call each instead of 3+2 (fewer throttled calls).
    upstox_quote_batch_size: int = 100
    upstox_request_retries: int = 2
    upstox_rate_limit_cooldown_seconds: int = 45
    upstox_chain_cache_seconds: int = 20
    upstox_ltp_cache_seconds: int = 2
    upstox_expiries_cache_seconds: int = 600
    upstox_funds_cache_seconds: int = 90
    upstox_candles_cache_seconds: int = 120
    upstox_max_expiry_probes: int = 2
    capital_refresh_seconds: int = 90
    fetch_constituents_in_snapshot: bool = True
    fetch_constituents_interval_seconds: int = 45
    constituent_stock_breadth_override_enabled: bool = True
    index_pin_put_block_enabled: bool = True
    index_pin_min_stock_breadth_pct: float = 58.0
    index_momentum_enabled: bool = True
    open_caution_moment_min_rank: float = 48.0

    # Trading mode
    paper_simple_profit_mode: bool = True
    paper_dual_strategy_enabled: bool = False
    explosion_capture_mode: bool = True  # PRIMARY — capture daily premium explosions
    # Explosion-only book — skip quick/swing. Jul29 scalps bled while explosive
    # ELITE was the edge; stop guarded scalps under explosion-only.
    explosion_only_trading_enabled: bool = True
    # Jul29: stop scalp entries entirely (guarded scalp sleeve was net negative).
    explosion_only_allow_guarded_scalp: bool = False
    # Master switch — when false, no scalp-mode / SCALP strategy entries at all.
    scalp_entries_enabled: bool = False
    # Explosion entries: only ELITE + EXPLODING (no soft BUILDING / premium-capture).
    explosion_elite_exploding_only: bool = True
    # Master hard policy. Strict causal S and final-policy-authorized rank-1
    # TOP_FTV_A are the only full-sleeve paths.
    ftv_elite_top_only_enabled: bool = True
    # Product focus: only top FTV, V-rip, ELITE, and EXPLODING moments (grade A/S).
    # Blocks B/C sleeves, generic BUILDING without FTV/V triggers, and non-explosion modes.
    top_moments_only_enabled: bool = True
    top_moments_min_grade: str = "A"  # A or S; set S for strictest book
    # Reserve capital-max lots for grade-A+ FTV / V / ELITE / EXPLODING only.
    top_moments_max_lots_only_enabled: bool = True
    # One-week validation: lower local-base floors so detection, grading, and entry
    # can fire at 2–15% pad. Use /api/ai/local-base-audit/{date} to score each day.
    local_base_audit_week_enabled: bool = False
    # S_STRICT = top ELITE/EXPLODING at local base only — mid armed prints must
    # not auto-grade S from the +12 armed-launch boost alone (Aug18 mid EXPLODING).
    ftv_s_strict_min_explosion_score: float = 85.0
    ftv_s_strict_min_quality: float = 70.0
    ftv_s_strict_min_velocity_3s: float = 2.5
    ftv_s_strict_min_velocity_9s: float = 1.75
    ftv_s_strict_require_cvd_buying: bool = True
    ftv_s_strict_min_local_base_move_pct: float = 5.0
    ftv_s_strict_max_local_base_move_pct: float = 25.0
    # Winner-like ELITE/EXPLODING at local base (historical book winners) — ordinary
    # sleeve. Clears past winners that miss CVD-acceleration TOP_FTV_A / full S, while
    # still rejecting Aug18 mid EXPLODING (~71 / quality B).
    winner_local_base_enabled: bool = True
    winner_local_base_min_explosion_score: float = 75.0
    winner_local_base_min_quality: float = 70.0
    winner_local_base_min_tqs: float = 50.0
    winner_local_base_min_velocity_3s: float = 2.2
    winner_local_base_min_velocity_9s: float = 1.5
    winner_local_base_min_local_base_move_pct: float = 5.0
    winner_local_base_max_local_base_move_pct: float = 25.0
    winner_local_base_max_capital_pct: float = 0.35
    # Early FTV in the 5–25% pad with heat counts as a fresh causal trigger for
    # WINNER / TOP_FTV_A even when armed (≤15%) has expired and first-lift (≥15%)
    # has not flipped yet — closes the radar-sees-it / auth-says-chase lag.
    # Floors stay ≥75/70 so Aug18 mid EXPLODING (~71/B) stays blocked.
    winner_local_base_early_ftv_fresh_enabled: bool = True
    # On WORST / EXPIRY WORST days, WINNER sleeve also needs real option CVD buying
    # (volume-surge alone is too soft for chop).
    winner_local_base_require_cvd_on_worst: bool = True
    # Prefer winner-shaped local-base prints in selector rank so they clear rank-1
    # while still inside the 5–25% catch window (before 100%+ FTV leaves the pad).
    winner_local_base_rank_bonus: float = 28.0
    # Final ftv_authorization_policy mirrors ICT #334 floors on EXPIRY WORST so
    # afternoon mid-EXPLODING cannot clear WINNER / S_STRICT outside midday trap.
    ftv_policy_expiry_worst_block_enabled: bool = True
    ftv_policy_expiry_worst_min_tier: str = "ELITE"
    ftv_policy_expiry_worst_min_quality: float = 85.0
    ftv_policy_expiry_worst_min_score: float = 90.0
    ftv_policy_expiry_worst_min_velocity_3s: float = 3.0
    # Separate rank-1 authorization for winner-like ELITE/EXPLODING current-data FTV A.
    # Historical profiles are not treated as proof because old rows lack v9/CVD.
    top_ftv_a_enabled: bool = True
    top_ftv_a_min_explosion_score: float = 90.0
    top_ftv_a_min_quality: float = 70.0
    top_ftv_a_min_tqs: float = 50.0
    top_ftv_a_min_velocity_3s: float = 2.5
    top_ftv_a_min_velocity_9s: float = 1.75
    top_ftv_a_normal_max_move_pct: float = 25.0
    top_ftv_a_max_capital_pct: float = 0.90
    # Extension from 25–40% requires exceptional acceleration and stronger quality.
    top_ftv_a_exceptional_min_explosion_score: float = 95.0
    top_ftv_a_exceptional_min_quality: float = 85.0
    top_ftv_a_exceptional_min_tqs: float = 55.0
    top_ftv_a_exceptional_min_velocity_3s: float = 5.0
    top_ftv_a_exceptional_min_velocity_9s: float = 2.5
    top_ftv_a_exceptional_max_move_pct: float = 40.0
    # When index spot helpers confirm the lift, waive CVD-acceleration for TOP_FTV_A
    # (accel often prints after the first take window — Aug19 shape).
    top_ftv_a_index_helpers_waive_cvd_accel: bool = True
    # Inside the early local-base pad (8–25%), soften TOP_FTV_A velocity and CVD
    # when v-rip / volume awakening already proved causal heat (Aug24 misses).
    top_ftv_a_pad_velocity_min_move_pct: float = 8.0
    top_ftv_a_pad_velocity_max_move_pct: float = 25.0
    top_ftv_a_pad_waive_cvd_when_volume_awake: bool = True
    # WINNER sleeve → max lots when index helpers confirm (else stays 35%).
    winner_local_base_index_helpers_max_lots: bool = True
    # Exception: BUILDING only as "elite build" — chart-aligned ICT flat→vertical
    # with ELITE-grade score + hot velocity. Aug7 cold BUILDING (score 56, v3 1.7)
    # must wait for ELITE print or upgrade into these bars.
    explosion_building_aligned_ict_enabled: bool = True
    explosion_building_elite_min_score: float = 62.0
    explosion_building_elite_min_velocity_3s: float = 2.5
    # Sustained heat — Aug10 BUILDING CE spiked v3 then died (v9≈0). Require hot v9.
    explosion_building_elite_min_velocity_9s: float = 2.5
    explosion_building_elite_min_ict_score: float = 35.0
    # WORST / BREAKOUT_ONLY: never admit BUILDING ICT flat→vertical (fake elite-build).
    # ELITE/EXPLODING still take at local-base pad levels.
    worst_day_block_building_ict: bool = True
    # Non-must-take ELITE/EXPLODING: prefer early local-base pad (must-take may go to 65%).
    elite_local_base_max_move_pct: float = 40.0
    # GainzAlgo-style Smart Ichimoku — HMA cloud + logistic break-P confirm on
    # ICT flat→vertical ELITE/EXPLODING (and elite-BUILDING). Filters shallow fakes.
    smart_ichimoku_use_hma: bool = True
    smart_ichimoku_tenkan_period: int = 9
    smart_ichimoku_kijun_period: int = 26
    smart_ichimoku_senkou_b_period: int = 52
    smart_ichimoku_displacement: int = 26
    smart_ichimoku_break_min_probability: float = 0.60
    smart_ichimoku_continuation_min_probability: float = 0.55
    smart_ichimoku_flat_vertical_confirm_enabled: bool = True
    # Index candlestick patterns (engulfing, marubozu, pin bar, stars, soldiers/crows)
    # confirm FTV/V premium structure when the 5m spot chart label lags the turn.
    ftv_candlestick_confirm_enabled: bool = True
    ftv_candlestick_min_pattern_strength: float = 68.0
    ftv_candlestick_require_ftv_structure: bool = True
    ftv_candlestick_min_flat_vertical_quality: float = 50.0
    ftv_candlestick_chart_bypass_enabled: bool = True
    ftv_candlestick_chart_bypass_min_score: float = 25.0
    ftv_candlestick_max_adverse_mom5_pct: float = 0.08
    ftv_candlestick_rank_bonus_enabled: bool = True
    ftv_candlestick_rank_bonus_max: float = 10.0
    smart_ichimoku_weight_rsi: float = 0.85
    smart_ichimoku_weight_stoch: float = 0.65
    smart_ichimoku_weight_zscore: float = 0.90
    smart_ichimoku_weight_depth: float = 1.10
    # Explosion entries only when index chart agrees with option side (CALL↔BULLISH,
    # PUT↔BEARISH). No counter-trend FOMO; flat→vertical is taken only when aligned.
    explosion_require_chart_align_enabled: bool = True
    # Selector parity: let a CONFIRMED local base off which the side is breaking survive
    # the selection-time chart-align drop, the same way check_explosion_entry already
    # honors local_base_ichimoku_chart_bypass. Without this, a genuine base rip whose 5m
    # spot chart hasn't flipped yet (e.g. SENSEX PE at a tight base) is silently dropped
    # in _explosion_candidates before the downstream local-base bypass can admit it. The
    # bypass still requires a confirmed base AND non-adverse live momentum, so this can
    # never admit counter-trend chop.
    explosion_selector_local_base_chart_bypass_enabled: bool = True
    # Never block ELITE explosions — skip extended-chase / live-confirm /
    # composer stand-down. Fake-trap + late-fade still apply (real PF killers).
    # Premium band still applies (no ₹3 OTM). Timing COLD/LATE/CHASE still
    # refuses the bypass when elite_bypass_requires_hot.
    explosion_elite_never_block_enabled: bool = True
    # Top ELITE/EXPLODING ATM/ITM inside near-base window → never block (Aug5 24500).
    explosion_top_must_take_enabled: bool = True
    explosion_top_must_take_tiers_csv: str = "ELITE,EXPLODING"
    explosion_top_must_take_min_score: float = 55.0
    explosion_top_must_take_require_atm_itm: bool = True
    explosion_top_must_take_require_chart_align: bool = True
    # Soft: index tick helpers confirm side even when 5m chart label lags.
    explosion_top_must_take_allow_index_helpers: bool = True
    # Must-take may skip window/live/timing/composer only after anti-chase + coil confirm.
    explosion_top_must_take_require_expansion_confirm_enabled: bool = True
    # Soft bypass fake-trap block for must-take ELITE/EXPLODING (still evaluates).
    top_must_take_bypasses_fake_trap: bool = True
    top_must_take_fake_trap_requires_index: bool = False
    # Per-trade timing quality (GOOD/OK/COLD/LATE/CHASE) — blocks cold ELITE fills.
    entry_timing_assessment_enabled: bool = True
    entry_timing_cold_max_velocity_3s: float = 1.5
    entry_timing_ok_min_velocity_3s: float = 1.5
    entry_timing_good_min_velocity_3s: float = 2.0
    entry_timing_late_min_peak_pct: float = 55.0
    entry_timing_late_max_live_velocity_3s: float = 1.0
    entry_timing_cold_block_on_chop: bool = True
    entry_timing_cold_lot_cap: int = 3
    entry_timing_elite_bypass_requires_hot: bool = True
    # A structured pause may be watched/taken small only while premium velocity remains
    # positive. Negative velocity is a failed launch, not a max-size local-base entry.
    entry_timing_structured_cold_base_allow: bool = True
    entry_timing_structured_cold_min_velocity_3s: float = 0.5
    entry_timing_structured_cold_lot_cap: int = 3
    entry_timing_structured_cold_max_lots: bool = False
    entry_timing_structured_cold_require_heat: bool = True
    entry_timing_structured_cold_require_aligned: bool = True
    # Ordinary entries use at most 35% capital. The configured 90% sleeve is reserved
    # for a proven armed-base launch with positive v3/v9, CVD buying and acceleration.
    ordinary_entry_max_capital_pct: float = 0.35
    full_sleeve_requires_armed_launch: bool = True
    full_sleeve_requires_cvd: bool = True
    full_sleeve_requires_cvd_acceleration: bool = True
    # Promote high-confidence radar explosions the missed-trade monitor flags as bullish/base-window.
    # Does NOT trade premium_out_of_band cheap OTM chases (Jul20 24550 @ ₹3 — correctly blocked).
    missed_explosion_promote_enabled: bool = True
    missed_explosion_promote_min_score: float = 70.0
    missed_explosion_promote_min_move_pct: float = 28.0
    missed_explosion_promote_max_move_pct: float = 65.0
    missed_explosion_promote_rank_bonus: float = 22.0

    # Paper should mirror live execution (broker flow + slippage) before going live
    paper_live_parity_enabled: bool = True
    paper_simulate_broker_orders: bool = True  # resolve instrument + paper order ids in parity mode

    # Paper slippage — realistic fills for milestone / PnL (ignored on live broker fills)
    paper_slippage_enabled: bool = True
    paper_slippage_entry_points: float = 1.0
    paper_slippage_exit_points: float = 0.75
    paper_slippage_explosion_mult: float = 1.5
    paper_slippage_swing_mult: float = 0.85
    paper_brokerage_round_trip_inr: float = 40.0
    # Realistic Indian options charges (F&O buy) — replaces flat brokerage so paper P&L
    # matches live net, esp. once positions size up. Turnover-based: brokerage + STT +
    # exchange txn + SEBI + stamp + GST. Rates ~Zerodha 2024-25 (configurable).
    realistic_charges_enabled: bool = True
    charge_brokerage_per_order_inr: float = 20.0     # ₹20/order cap
    charge_brokerage_pct: float = 0.0003             # or 0.03% of turnover, whichever lower
    charge_stt_pct_sell: float = 0.000625            # 0.0625% on SELL premium
    charge_exchange_txn_pct: float = 0.00035         # ~0.035% of premium turnover (both sides)
    charge_sebi_pct: float = 0.000001                # ₹10 per crore
    charge_stamp_pct_buy: float = 0.00003            # 0.003% on BUY premium
    charge_gst_pct: float = 0.18                     # 18% on brokerage+exchange+SEBI

    # Explosion capture — Jun 25 +₹66K profile: micro locks, trails, 12pt standard target
    explosion_min_velocity_3s: float = 2.0
    explosion_min_velocity_9s: float = 3.0
    explosion_early_velocity_3s: float = 3.0
    explosion_early_volume_surge: float = 1.5
    explosion_scan_range: int = 800
    explosion_sensex_scan_range: int = 1500
    explosion_worst_day_scan_range: int = 500
    explosion_sensex_worst_day_scan_range: int = 500
    explosion_atm_proximity_bonus_max: float = 8.0
    explosion_otm_depth_penalty_per_step: float = 3.0
    explosion_peak_chase_guard_enabled: bool = True
    explosion_peak_chase_min_premium_mom_pct: float = 15.0
    explosion_peak_chase_max_otm_steps: int = 3
    explosion_peak_chase_min_session_move_pct: float = 40.0
    # Extended-session chase hard block — PF killer (Jul17 24250 CE entered +91%).
    # Hard ceiling aligned to early/must-take window max (10–65%) — book: 70–100% WR=0.
    explosion_extended_chase_block_enabled: bool = True
    explosion_extended_chase_min_move_pct: float = 65.0
    # Soft zone: shrink size approaching the hard ceiling.
    explosion_extended_soft_min_move_pct: float = 55.0
    # Don't chase the EXHAUSTION of a completed move (symmetric CE/PE). If the contract's
    # premium already ran >= min_run in the recent window AND we'd enter within near_top_frac
    # of that window's peak, the leg is spent — block (today's live PUT 23950: bought near the
    # low at 10:47 as the down-move exhausted, V-reversed, stopped). Near-base entries are
    # exempt by construction (current sits at the window low, not its peak), so this never
    # blocks a genuine base entry — only the late/mid-rip chase.
    explosion_post_peak_chase_guard_enabled: bool = True
    explosion_post_peak_chase_lookback_seconds: float = 900.0
    explosion_post_peak_chase_min_run_pct: float = 0.25
    explosion_post_peak_chase_near_top_frac: float = 0.12
    # Session-level post-peak: a slow-grind rip (PE 15->100 over hours) shows only a small run
    # in the short window, so buying near the top slips through. Also reject entries within
    # near_top_frac of the SESSION peak after a big session run (Sep 1 live PUT 24050: entry
    # 94.8 vs ~100 session peak, +500% -> never green -> -19k). Near-base entries sit near the
    # session LOW, so this only blocks the exhausted-top chase.
    explosion_post_peak_chase_session_enabled: bool = True
    # Base-relative chase bypass — a fresh flat→vertical break off a consolidation base
    # (SENSEX 76300 PE: 30-100 range then 100-144 break) reads as high day-move but the
    # move FROM THE BASE is still early. Allow it when volume is rising + base move in window.
    ict_base_relative_chase_bypass_enabled: bool = True
    ict_base_relative_chase_max_move_pct: float = 65.0
    ict_base_relative_chase_abs_move_cap_pct: float = 160.0
    # Jul23 SENSEX 76400 PE: day-move +471% after an earlier run-up/dump, but the NEW leg
    # launched from the 14:35 local V-bottom (~42). Chase/entry must use that local base.
    # Tradeable local window aligned to early band 15–65% (Aug4 78700 PE entered ~54%).
    explosion_chase_use_local_base: bool = True
    explosion_local_base_chase_max_move_pct: float = 65.0
    # Local-base floor for structured ICT / immature — Aug7 BUILDING 24550 PE entered
    # at 13% off base and failed; require clearer break before sizing in (was 10).
    explosion_local_base_entry_min_move_pct: float = 15.0
    # Adaptive local-base entry window by tier/volume: ELITE + strong volume widens the
    # ceiling slightly inside the hard 65% cap; EXPLODING keeps the structured floor.
    local_base_adaptive_window_enabled: bool = True
    local_base_elite_chase_max_move_pct: float = 65.0
    local_base_exploding_entry_min_move_pct: float = 15.0
    local_base_wide_window_min_vol_surge: float = 3.0
    # Ignore micro baseRel (<8%) for immature/chase — Jul24 PUTs showed ~1–2%
    # "local base" noise while day-move was already mature (~28%).
    explosion_local_base_trust_min_move_pct: float = 8.0
    ict_local_base_lookback_polls: int = 16
    ict_local_base_min_dump_pct: float = 25.0
    # Medium-horizon local base: measure entry/chase from the recent ~30-min swing low
    # (the real "local base"), not the far full-session low. Aug5 24500 PE: 72 was ~9%
    # off the ~66 local base but read ~80% off the ~40 session low → wrongly a chase.
    # Preferred over off-session-low whenever local-base history exists.
    explosion_local_base_recent_window_enabled: bool = True
    explosion_extended_soft_lot_cap: int = 6
    explosion_hard_lot_cap: int = 10
    # Early capture window — HARD entry gate for unstructured ELITE/EXPLODING.
    # Book (lots≤20): mid-band winners; <22% and 70–100% lose. Ceiling 55→65 so
    # Aug4-style local-base rips (~54%) stay inside the pad (still hard-cut at 65+).
    # Structured ICT flat→vertical / swing V-base uses ict_structured_early_* (10–65).
    explosion_early_window_min_move_pct: float = 28.0
    explosion_early_window_max_move_pct: float = 65.0
    explosion_entry_window_hard_enabled: bool = True
    # Structured near-base path: ICT + heat may enter 15–65% off local base.
    # Aug4 SENSEX 78700 PE entered ~54% off local base (+₹18k) — old 45% ceiling
    # treated that as chase. Floor 10→15 so Aug7-style 13% BUILDING noise is skipped.
    ict_structured_early_entry_enabled: bool = True
    ict_structured_early_min_move_pct: float = 15.0
    ict_structured_early_max_move_pct: float = 65.0
    # Measure flat→vertical from the lowest premium in the flat window (true local base),
    # not the average — so the first lift appears at ~15% off the trough, not mid-chase.
    ict_flat_base_use_lowest: bool = True
    # Arm FTV / radar as soon as pad is in the structured entry band with heat.
    ict_first_lift_appear_enabled: bool = True
    ict_first_lift_min_velocity_3s: float = 1.2
    # Early momentum-ignition at the LOCAL BASE — catch the FTV as it ignites (1-10% off the
    # confirmed base) instead of waiting for the ~15% structured first-lift floor, which is why
    # entries land late (Aug31 24150 CE only caught at ~18% off base). Fires only for a top-tier
    # ELITE/EXPLODING contract at a confirmed base with a genuine ignition: v3 >= floor AND
    # accelerating (v3 >= v9) AND volume/CVD confirmation AND ATM/ITM. OPT-IN (default off) — it
    # admits earlier entries on the live path. ENABLED — the sole purpose is to catch these
    # ignitions at the base; the size/loss backstops (per-trade INR cap, daily stop, base-retest
    # sizing, fake-trap size caps) still bound each trade, they just don't block the entry.
    early_momentum_ignition_enabled: bool = True
    early_momentum_ignition_min_move_pct: float = 1.0
    early_momentum_ignition_max_move_pct: float = 10.0
    early_momentum_ignition_min_velocity_3s: float = 1.0
    early_momentum_ignition_min_vol_surge: float = 2.0
    # Catch FAST FTVs at the base: a 20->60 rip grades BUILDING at 1-10% off base and only
    # prints ELITE after it has already run 25%+ (a chase). Allow the ignition lane on BUILDING
    # too — but only on a STRONG, volume-backed accelerating ignition off a TIGHT base (the
    # signature a real fast FTV has at the base and a chop dud does not). This substitutes for
    # the quality/score floor, which lags at the base (score/quality rise WITH the move). Chase
    # guards (post-peak, timing, extended-chase) are untouched — this only opens the base window.
    early_momentum_ignition_allow_building: bool = True
    early_momentum_ignition_strong_velocity_3s: float = 2.5
    early_momentum_ignition_strong_vol_surge: float = 2.5
    early_momentum_ignition_tight_base_range_pct: float = 5.0
    # Flat-base coil breakout PREDICTOR — flag the setup while it's still flat (before the
    # tier/grade upgrades, which lag). Composes armed-base tightness + index squeeze/VWAP +
    # option CVD accumulation + side-regime into {coiling, readinessScore, predictedSide}.
    # Stamped on every alert (coilBreakoutPrediction) for radar visibility; a ripe coil whose
    # predicted side matches gets a soft rank nudge so the ignition lane can take it at the
    # first real move. Selection-only; never gates the live trigger/exit.
    coil_breakout_prediction_enabled: bool = True
    coil_prediction_influences_ranking: bool = True
    coil_prediction_max_range_pct: float = 5.0
    # GainzAlgo V2 Alpha-style decisive breakout candle — a strong-bodied engulfing bar with
    # RSI agreeing after a pullback (a genuine turn off the base, not chop). Non-repainting,
    # fires right as the coil breaks (earlier than the 45s smoothed drift on a grind-then-pop).
    # Used as a coil-predictor direction vote; additive selection signal, never a hard gate.
    decisive_candle_enabled: bool = True
    decisive_candle_body_ratio_min: float = 0.6
    decisive_candle_rsi_ceiling: float = 80.0
    decisive_candle_pullback_lookback: int = 5
    # GainzAlgo V2 Alpha on the OPTION premium (not just the index). An index-level candle
    # barely registers a huge option rip (₹15->100 is a small % on the index), so run the same
    # decisive-breakout detector on the contract's own premium tape (bucketed into OHLC bars).
    # A decisive BULLISH bar on the premium = the option broke decisively off its base. Added
    # as a coil-predictor direction vote (additive; the coil-armed lane still needs readiness +
    # quality + CVD), so it strengthens base-catch without loosening any gate.
    option_decisive_breakout_enabled: bool = True
    option_decisive_breakout_lookback_seconds: float = 900.0
    option_decisive_breakout_bucket_seconds: float = 30.0
    coil_prediction_min_direction_votes: int = 2
    coil_prediction_min_readiness_for_rank: float = 60.0
    coil_prediction_rank_bonus: float = 10.0
    # Coil-armed LOW-SCORE base entry — take a top FTV/V/ELITE/EXPLODING at the local base
    # while its score/grade is still LOW (they lag the move), when the coil predictor is
    # strongly ripe + directional + near-base. Bounded by a hard noise floor (never trades
    # junk). ENABLED — this is the lane that takes CE/PE AT the flat base before the score/thrust
    # catches up. Size/loss backstops still apply (they cap size, not entry).
    coil_armed_low_score_entry_enabled: bool = True
    coil_armed_low_score_min_readiness: float = 72.0
    coil_armed_low_score_min_direction_votes: int = 3
    coil_armed_low_score_max_base_move_pct: float = 12.0
    coil_armed_low_score_min_score: float = 40.0
    coil_armed_low_score_min_vol_surge: float = 1.5
    # Near-base loss filter (data-calibrated on 11 days). The base zone is where DUDS cluster:
    # near-base signals are ~50-59% duds unfiltered. FTV quality is the proven separator
    # (Q>=70: 42% win vs Q<50: 6%), and near-base winners carried score ~100 / Q ~70 while
    # duds were score ~76 / Q <50. So the near-base lanes (coil-armed, early-ignition) require
    # EITHER strong FTV quality OR a strong score — blocking the low-Q + low-score dud bucket
    # while keeping the genuine base winners. Applies only near the base (where duds live).
    near_base_lane_min_quality: float = 70.0
    near_base_lane_strong_score: float = 90.0
    # Let a strongly-ripe coil-armed top setup LIFT a chop/worst-day session halt (to
    # elite-only mode) so the early lanes can fire on a chop day instead of the session block
    # vetoing the near-base winner. Session-level — ENABLED so a chop/worst-day halt never
    # blocks a genuinely ripe near-base setup; the HIGH readiness floor keeps ordinary chop
    # coils from re-opening the session.
    coil_armed_session_lift_enabled: bool = True
    coil_armed_session_lift_min_readiness: float = 75.0
    coil_armed_session_lift_max_base_move_pct: float = 12.0
    index_confirmed_local_base_enabled: bool = True
    index_confirmed_local_base_max_off_low_pct: float = 22.0
    index_confirmed_local_base_min_explosion_score_floor: float = 5.0
    index_confirmed_local_base_waives_near_miss: bool = True
    index_confirmed_local_base_waives_timing: bool = True
    index_confirmed_local_base_premium_fade: bool = True
    # Armed first-lift at pad + agreeing breadth — index mom5 turn may lag mom15 (Sep01).
    index_confirmed_local_base_armed_pad_bypass: bool = True
    # Deep session trough — mom5 still negative but recovering vs mom15 (Sep01 morning CALLs).
    index_trough_deep_recovery_enabled: bool = True
    index_trough_deep_recovery_max_mom15_pct: float = -0.20
    # FTV authorization sleeve for index-confirmed pad captures (grade B flat-velocity lag).
    index_confirmed_ftv_auth_enabled: bool = True
    index_confirmed_ftv_min_explosion_score: float = 35.0
    index_confirmed_ftv_min_quality: float = 55.0
    index_confirmed_ftv_min_local_base_move_pct: float = 4.0
    index_confirmed_ftv_max_local_base_move_pct: float = 25.0
    index_confirmed_ftv_max_capital_pct: float = 0.90
    # Index-confirmed pad capture — deep ITM at trough/peak and shallow OTM reversal (Sep01).
    index_confirmed_moneyness_bypass_enabled: bool = True
    index_confirmed_max_itm_steps: int = 12
    index_confirmed_max_otm_steps: int = 2
    # OTM reversal entry — the #1 cause of explosion_near_miss on today's CALL winners was
    # armed_base_requires_atm_itm_otm: they were 2-3 strikes OTM (spot below the strike on the
    # 'bearish' day) and the 1-step shallow allowance rejected them, then spot rallied UP
    # through them (24150 CE +105%). This lifts the OTM depth to otm_reversal_max_steps ONLY
    # when the index is CONFIRMED reversing toward that side (side-regime / drift / breakout) —
    # so it catches the reversal-rally winner, not an OTM lottery ticket. ENABLED — gated on a
    # confirmed index reversal, so it only opens depth for the real reversal-rally moment.
    otm_reversal_entry_enabled: bool = True
    otm_reversal_max_steps: int = 2
    # Size so a normal retest to the local base cannot exceed this % of capital — otherwise a
    # full-capital near-base entry on a cheap option gets shaken out on the ordinary base retest
    # before the move runs (Aug31 24150 CE: −₹21k on the retest at ₹2L before +185%). Protective
    # (only reduces lots); on by default. Matters most as capital scales up.
    size_to_base_retest_enabled: bool = True
    size_to_base_retest_max_pct_of_capital: float = 0.10
    size_to_base_retest_break_buffer_pct: float = 0.15
    # EOD "would-have-traded" replay near-base entry window (fraction off the local base).
    # Winners across the 11-day replay cluster ≤~13% off base; losers that never ignite cluster
    # later (~17%+). Tightening the ceiling to 15% keeps the near-base winners while dropping the
    # late/chase-ier cold entries that fade — the dominant EOD loss bucket.
    eod_near_base_min_off_pct: float = 0.10
    eod_near_base_max_off_pct: float = 0.15
    # EOD replay entry realism — approximate the live confirmation the simple near-base+drift
    # rule lacks, so the report stops taking entries live would reject.
    #  - post-peak guard (ON): reject buying near the top of a run that already happened in the
    #    recent window — drops late second-leg chases (e.g. 24050 CE at 125 after the 133 peak).
    #    Validated across 11 days: net +50.4k -> +61.1k, fewer losers, winners preserved.
    #  - ignition gate (OFF): "premium actively lifting" is too coarse on the sampled tape — it
    #    also rejects genuine winners that enter on a slow/flat base lift (11-day net collapsed
    #    to -32k, winners 20 -> 9). The live early-ignition lane uses velocity accel + volume +
    #    CVD, which the tape lacks, so this proxy can't reproduce it. Kept opt-in, default off.
    eod_replay_post_peak_enabled: bool = True
    eod_replay_post_peak_lookback_s: float = 900.0
    eod_replay_post_peak_min_run_pct: float = 0.25
    eod_replay_post_peak_near_top_frac: float = 0.12
    eod_replay_ignition_enabled: bool = False
    eod_replay_ignition_window_s: float = 45.0
    eod_replay_ignition_min_rise_pct: float = 0.012
    # Per-trade INR loss cap for the replay. The EOD loss is ~99% cold near-base entries that
    # never ignite (peak ~3%); at ₹2L full-lot a single cold entry can lose 40k+. Capping does
    # two things (11-day validated): bounds the blowup AND frees the one-position slot fast so
    # the day's later winners get taken instead of being blocked by a slow bleeder — net
    # +59k->+148k, worst single -44k->-19k, winners 18->23. 0 = off. Mirrors a live per-trade
    # backstop; the same slot-bleed cost applies live, so this is also a live tuning signal.
    eod_replay_per_trade_max_loss_inr: float = 15_000.0
    # EOD replay concurrency: how many positions may run at once, splitting capital into that
    # many slots (each position sized to capital/slots). 1 = one full-capital position at a time
    # (rides one runner to max TP but skips concurrent winners). The 11-day replay shows 2 slots
    # captures ~2x the winners for ~+40% net vs 1; 3+ slots decays as per-slot size shrinks and
    # losers scale up. Mirrors the live risk engine's ftv_allocation_max_positions concurrency,
    # but ties it to capital slots so per-trade size stays honest. Default 1 = today's behaviour.
    eod_report_max_concurrent: int = 1
    eod_report_same_side_cap: int = 2
    # Causal pre-breakout base: repeated past samples arm a contract-local denominator.
    # It is sticky upward across REST/WS observations and may only ratchet to a proven low.
    ict_armed_base_enabled: bool = True
    ict_armed_base_lookback_seconds: float = 900.0
    ict_armed_base_exclude_recent_seconds: float = 3.0
    ict_armed_base_min_samples: int = 6
    ict_armed_base_min_span_seconds: float = 15.0
    ict_armed_base_max_range_pct: float = 5.0
    ict_armed_base_horizon_seconds: float = 1800.0
    ict_armed_base_min_ratchet_pct: float = 2.0
    # Reject mid-rip pause coils as a "new base" after a real trough expansion
    # (Aug19 SENSEX 76900 PE: re-armed ~162 after ~90 trough, pad looked 2.6%
    # "early" while session was already ~42% off the true base).
    ict_armed_base_block_mid_rip_coil_enabled: bool = True
    ict_armed_base_mid_rip_min_above_session_low_pct: float = 25.0
    ict_armed_base_mid_rip_min_off_low_pct: float = 30.0
    ict_armed_base_mid_rip_min_peak_pullback_pct: float = 35.0
    # V-bottom: when day-OHLC / session low is known and live premium is still
    # near that trough, arm it as the launch pad even if sparse LTP never formed
    # a tight poll coil (Aug19 76900 PE V-base ~125 → 220).
    ict_armed_base_session_low_arm_enabled: bool = True
    ict_armed_base_session_low_arm_max_move_pct: float = 12.0
    # Conservative pre-first-lift launch. Absolute chain volume (or explicit CVD/
    # orderflow proof) replaces the lagging 2x REST surge requirement.
    ict_armed_base_launch_min_move_pct: float = 5.0
    # Overlap first-lift floor (15%) so 12–15% early FTV is not a dead auth zone.
    ict_armed_base_launch_max_move_pct: float = 15.0
    # Top-only at local base — mid EXPLODING armed spikes stay watch-only.
    # Floors stay above Aug18 mid losers but admit prior ELITE/EXPLODING winners.
    ict_armed_base_launch_min_velocity_3s: float = 2.0
    ict_armed_base_launch_min_velocity_9s: float = 1.5
    ict_armed_base_launch_min_absolute_volume: float = 25000.0
    ict_armed_base_launch_min_quality: float = 65.0
    # Detector emits one-decimal scores; keep the 64.5 armed-launch boundary executable.
    ict_armed_base_launch_min_score: float = 64.5
    ict_armed_base_launch_min_tqs: float = 50.0
    ict_armed_base_launch_rank_bonus: float = 16.0
    # Pre-lift pad: volume awakening + first lift can show flat/negative v3 before
    # the vertical leg — chart/defensive gates must not demand spike velocity yet.
    ict_armed_base_launch_cold_velocity_3s: float = -0.5
    # first_lift_local_base at the 2–25% pad may show cold v3 pre-vertical (Aug26 SENSEX PUT 77800).
    ict_first_lift_local_base_cold_velocity_3s: float = -1.5
    # Narrow pre-launch authorization: a stable ATM/ITM base may become executable
    # before +5%, but only with the same live velocity/orderflow quality as a launch.
    ict_elite_base_ready_enabled: bool = True
    ict_elite_base_ready_min_move_pct: float = 2.0
    ict_elite_base_ready_max_move_pct: float = 5.0
    ict_elite_base_ready_min_velocity_3s: float = 1.5
    ict_elite_base_ready_min_velocity_9s: float = 1.5
    ict_elite_base_ready_min_quality: float = 55.0
    ict_elite_base_ready_min_score: float = 45.0
    # Continuous V-rip sleeve off the session/day trough. Sparse polls often skip
    # the narrow 2–5% elite window (125→140); keep auth open through 2–25% so we
    # do not fail to capture genuine V rips while mid-rip coils stay blocked.
    ict_v_rip_ready_enabled: bool = True
    ict_v_rip_min_move_pct: float = 2.0
    ict_v_rip_max_move_pct: float = 25.0
    ict_v_rip_min_velocity_3s: float = 1.2
    ict_v_rip_min_velocity_9s: float = 0.8
    ict_v_rip_cold_velocity_3s: float = -1.5
    ict_v_rip_min_quality: float = 45.0
    ict_v_rip_min_score: float = 12.0
    ict_v_rip_base_near_session_low_pct: float = 2.0
    # Slow grind anywhere in the 2–25% V-rip pad may show volume awakening before
    # v3 clears the default 1.2% bar — align pad floor with ict_v_rip_min_move_pct.
    ict_v_rip_pad_min_move_pct: float = 2.0
    ict_v_rip_volume_awake_min_velocity_3s: float = 0.85
    # BUILDING bullish-rip sleeve: when radar is stuck BUILDING but premium is
    # actively ripping (positive live velocity + volume), take mid-rip toward max.
    # Cold/negative-v3 BUILDING stays blocked. Does not require session-trough arm.
    building_rip_bullish_enabled: bool = True
    building_rip_min_velocity_3s: float = 1.5
    building_rip_min_velocity_9s: float = 0.8
    building_rip_min_volume_surge: float = 1.8
    building_rip_min_score: float = 28.0
    building_rip_min_move_pct: float = 2.0
    building_rip_max_move_pct: float = 55.0
    building_rip_fade_peak_gap_pct: float = 12.0
    building_rip_promote_to_exploding: bool = True
    building_rip_rank_bonus: float = 14.0
    # Local-base early lift: radar already sees the local base as BUILDING; a
    # measured little lift off that base + positive live velocity = take.
    building_rip_local_base_lift_enabled: bool = True
    building_rip_local_base_min_move_pct: float = 2.0
    building_rip_local_base_max_move_pct: float = 15.0
    building_rip_local_base_min_velocity_3s: float = 1.2
    # Align with aggressive_min_explosion_score so ready lifts clear selector floor.
    building_rip_local_base_min_score: float = 12.0
    # Precise BUILDING radar LTP monitor: every meaningful WS LTP print on a
    # BUILDING name re-scans explosions and may take — do not wait for the
    # slower full entry-scan cadence.
    building_ltp_monitor_enabled: bool = True
    building_ltp_monitor_min_ms: float = 75.0
    building_ltp_min_change_pct: float = 0.15
    building_ltp_min_change_abs: float = 0.05
    # After scoring every watched BUILDING name on an LTP cycle, take only the
    # single best ready name (not the first that happened to print).
    building_ltp_best_pick_enabled: bool = True
    building_ltp_best_pick_rank_bonus: float = 48.0
    building_ltp_only_best_ready: bool = True
    # Aug19 sudden-lift helper board — monitor what actually helps BUILDING move.
    building_sudden_lift_monitor_enabled: bool = True
    building_sudden_lift_min_helpers: int = 3
    building_sudden_lift_min_pct: float = 0.4
    building_sudden_lift_min_velocity_3s: float = 1.2
    building_sudden_lift_min_peak_velocity_3s: float = 3.0
    building_sudden_lift_min_ftv_quality: float = 55.0
    building_sudden_lift_min_absolute_volume: float = 25_000.0
    building_lift_helper_point: float = 3.5
    building_lift_helping_bonus: float = 18.0
    building_sudden_ltp_lift_bonus: float = 8.0
    # Force an entry cycle when helpers flip on even without a large LTP tick.
    building_helper_flip_triggers_cycle: bool = True
    # FTV sleeve for confirmed BUILDING lifts: when helpers prove something is
    # helping (vol / CVD / chart / breadth), authorize without waiting for ELITE.
    building_rip_ftv_enabled: bool = True
    building_rip_ftv_min_explosion_score: float = 12.0
    building_rip_ftv_min_velocity_3s: float = 1.2
    building_rip_ftv_min_local_base_move_pct: float = 2.0
    building_rip_ftv_max_local_base_move_pct: float = 55.0
    # Max lots when helpers confirm the sudden BUILDING lift (same sleeve as TOP_FTV_A).
    building_rip_ftv_max_capital_pct: float = 0.90
    building_rip_ftv_force_max_lots: bool = True
    # Pre-lift slow-coil pad sleeve — authorize BUILDING/EXPLODING flat base before
    # velocity spikes (Aug24 24200 PE ₹18–23 coil → sudden lift).
    slow_grind_ftv_enabled: bool = True
    slow_grind_ftv_min_explosion_score: float = 12.0
    slow_grind_ftv_min_flat_quality: float = 40.0
    slow_grind_ftv_armed_trough_min_explosion_score: float = 5.0
    slow_grind_ftv_consolidation_base_min_explosion_score: float = 12.0
    slow_grind_ftv_consolidation_base_min_flat_quality: float = 35.0
    slow_grind_ftv_max_capital_pct: float = 0.90
    slow_grind_ftv_force_max_lots: bool = True
    # Fast-bullish pad sleeve — momentum turn + volume awakening as lift starts.
    fast_bullish_ftv_enabled: bool = True
    fast_bullish_ftv_min_explosion_score: float = 12.0
    fast_bullish_ftv_min_velocity_3s: float = 0.5
    fast_bullish_ftv_max_capital_pct: float = 0.90
    fast_bullish_ftv_force_max_lots: bool = True
    building_rip_bypasses_extended_chase: bool = True
    building_rip_bypasses_fake_trap: bool = True
    # Index tick helpers — NIFTY/SENSEX spot tape that drives strike lifts.
    index_tick_helpers_enabled: bool = True
    index_tick_wake_building_cycle: bool = True
    index_tick_align_abs_velocity_3s: float = 0.02
    index_tick_spike_abs_velocity_3s: float = 0.035
    index_tick_mom_shift_pct: float = 0.03
    index_tick_min_helpers_confirm: int = 2
    index_tick_confirm_bonus: float = 10.0
    top_explosion_force_max_allow_index_helpers: bool = True
    # History of index spike MOMENTS: a burst of same-direction spot spikes in a short
    # window is a much stronger "the index is thrusting" confirmation than a single blip,
    # and is exactly what precedes a BUILDING strike suddenly going flat->vertical.
    index_spike_history_enabled: bool = True
    index_spike_history_window_seconds: float = 45.0
    index_spike_history_max: int = 40
    index_spike_burst_min_count: int = 3
    index_spike_burst_rank_bonus: float = 4.0
    # Sustained index DRIFT: some FTVs are driven by a steady grind in the spot (not sharp
    # spikes), e.g. Aug19 SENSEX 76900 PE where the index bled ~-99pts/90s below the sharp
    # 3s spike bar. Track a longer index LTP buffer and confirm when the NET same-direction
    # spot move over a window clears a threshold. Net move cancels chop (mean-reversion), so
    # a modest 0.05% clears only genuine directional grinds. Calibrated on Aug19 replay:
    # a 45s net move of 0.05% fires ~6x/session (median chop 45s move ~0.003%).
    index_drift_enabled: bool = True
    index_drift_history_seconds: float = 120.0
    index_drift_window_seconds: float = 45.0
    index_drift_min_move_pct: float = 0.05
    index_drift_rank_bonus: float = 3.0
    # Sparse-feed fallback: a stable ATM/ITM base may launch on sustained 2-minute
    # premium progress even when 3s/9s velocity samples are unavailable.
    ict_armed_sustained_lift_min_move_pct: float = 8.0
    ict_armed_sustained_lift_max_move_pct: float = 25.0
    ict_armed_sustained_lift_lookback_seconds: float = 120.0
    ict_armed_sustained_lift_min_samples: int = 3
    ict_armed_sustained_lift_min_span_seconds: float = 15.0
    ict_armed_sustained_lift_min_progress_pct: float = 3.0
    ict_armed_sustained_lift_max_fade_pct: float = 2.5
    # Durable 5m-style premium base confirmation from the 30-minute tape. Repeated
    # support samples prevent a single bad tick from becoming a launch pad.
    ict_recent_base_window_seconds: int = 1800
    ict_recent_base_exclude_seconds: int = 45
    ict_recent_base_min_samples: int = 6
    ict_recent_base_support_band_pct: float = 8.0
    ict_recent_base_min_support_samples: int = 3
    ict_recent_base_min_support_span_seconds: float = 30.0
    ict_recent_base_max_age_seconds: float = 900.0
    explosion_first_lift_rank_bonus: float = 24.0
    explosion_first_lift_sweet_max_move_pct: float = 25.0
    # Actionable first lift: a strict subset of radar first-lifts may enter before
    # BUILDING upgrades when the base, volume, sustained premium lift and live index
    # turn all agree. This closes the WATCH/BUILDING dead zone without trading every low.
    first_lift_trade_enabled: bool = True
    # Structured local-base first lift — ELITE/EXPLODING winners in the 15–25% pad
    # (aligned with must-take min score 62; quality keeps mid B-grade out).
    first_lift_trade_min_score: float = 35.0
    first_lift_trade_min_quality: float = 55.0
    first_lift_trade_min_volume_surge: float = 2.0
    first_lift_trade_min_velocity_3s: float = 1.5
    first_lift_trade_min_velocity_9s: float = 1.0
    # Match the detector's causal first-lift band; >40% remains a chase.
    first_lift_trade_max_move_pct: float = 40.0
    # Helper-confirmed lane: "on the radar as BUILDING and suddenly something is helping to
    # go FTV." When enough INDEPENDENT confirmations agree (volume surge/awaken, displacement,
    # premium FVG, flat->vertical structure, chart-align, breadth-align) on a name at its
    # local base with positive live velocity, that IS the confirmed FTV — so it may enter on
    # a LOWER quality/score/velocity bar than a bare first lift, and (BUILDING) may override
    # the worst-day / BREAKOUT_ONLY block. Un-helped first lifts still hit the strict bar.
    first_lift_helper_confirm_enabled: bool = True
    first_lift_helper_confirm_min_helpers: int = 3
    first_lift_helper_strong_surge: float = 3.0
    first_lift_helper_confirm_min_quality: float = 45.0
    first_lift_helper_confirm_min_score: float = 12.0
    first_lift_helper_confirm_min_velocity_3s: float = 1.2
    first_lift_helper_confirm_min_velocity_9s: float = 0.6
    # Shallow v3 dip on confirmed first-lift/V-rip at local base — ICT pad is
    # proven; do not treat a micro pullback as FAILED_LAUNCH (Aug24 PUT 24450).
    first_lift_local_base_micro_pullback_enabled: bool = True
    first_lift_local_base_micro_pullback_min_velocity_3s: float = -1.2
    first_lift_local_base_micro_pullback_min_velocity_9s: float = -0.5
    building_rip_helper_override_worst_day: bool = True
    first_lift_trade_min_momentum_shift_pct: float = 0.03
    # ATM/ITM premium-led first lift: stronger option evidence may lead a lagging
    # bearish/bullish spot chart, symmetrically for CE/PE.
    first_lift_option_led_enabled: bool = True
    first_lift_option_led_min_quality: float = 65.0
    first_lift_option_led_min_velocity_3s: float = 1.5
    first_lift_option_led_min_velocity_9s: float = 1.5
    first_lift_option_led_rank_bonus: float = 12.0
    # A strict first lift has stronger early evidence than the generic COLD timing
    # classifier. Do not wait for lagging breadth/chart state after the measured
    # local pad, quality, sustained velocity, volume and live momentum turn pass.
    # Chase, fake-trap, expiry, risk and execution-price checks still apply.
    first_lift_bypasses_cold_timing_enabled: bool = True
    # Carry the same strict first-lift proof through the final live chart/MTF
    # monitor. Premium fading and all non-chart execution checks remain active.
    first_lift_bypasses_execution_chart_enabled: bool = True
    # ICT-confirmed first lift at local base when v3 snapshot is flat (0) — volumeAwaken
    # + flat→vertical structure already prove the pad; do not downgrade to B grade.
    first_lift_local_base_flat_velocity_enabled: bool = True
    # First-lift pad cold score — first-lift or V-rip at 2–25% lb with peak ≥25% but
    # composite score still warming (Aug25 NIFTY PUT 24250: score 26; PUT 24150: grade B).
    first_lift_pad_explosion_bypass_enabled: bool = True
    first_lift_pad_explosion_min_peak_pct: float = 25.0
    first_lift_pad_explosion_min_score: float = 8.0
    first_lift_pad_local_base_min_pct: float = 2.0
    first_lift_pad_local_base_max_pct: float = 25.0
    # Immature floor matches unstructured early-window min (was 22% — still let noise through).
    explosion_immature_block_enabled: bool = True
    explosion_immature_min_session_move_pct: float = 28.0
    # Live confirmation — sticky ELITE / displacement spikes without live heat+structure
    # (Jul23 NIFTY 23900 PE v3=0.26 watch, SENSEX 76200 PE midday displacement-only).
    explosion_live_confirm_enabled: bool = True
    explosion_live_confirm_min_velocity_3s: float = 1.5
    explosion_live_confirm_ict_min_velocity_3s: float = 1.5
    # Structured near-ATM CE/PE may use softer live/peak velocity (key name kept for compat).
    explosion_live_confirm_structured_ce_min_velocity_3s: float = 1.0
    structured_near_atm_max_otm_steps: int = 3
    explosion_live_confirm_require_structure: bool = True
    explosion_live_confirm_hot_velocity_3s: float = 8.0
    # Premium/afternoon captures are slow volume-backed grinds (low velocity by design,
    # e.g. NIFTY 24250 PE 1pm consolidation breakout). They are already validated by the
    # capture criteria (window+score+volume+consolidation+chart), so a genuine one with a
    # real volume surge is live-confirmed by that — don't re-block it on the velocity
    # floor. A structure-less displacement spike (low volume) still gets blocked.
    explosion_live_confirm_premium_capture_bypass: bool = True
    explosion_live_confirm_premium_min_vol_surge: float = 1.3
    # Peak-hold the explosion score for a short window so bursty velocity doesn't flicker
    # it below entry gates mid-rip (SENSEX 76500 PE Jul23: 27→71→36 in one sustained move).
    explosion_score_sticky_enabled: bool = True
    explosion_score_sticky_seconds: float = 45.0
    # CHOP/RANGE — stricter floor than immature (false EXPLODING is common).
    explosion_chop_min_session_move_pct: float = 28.0
    # Faded vertical rip — peak move huge but live velocity cooled (caution sizing)
    explosion_faded_rip_caution_enabled: bool = True
    explosion_faded_rip_min_peak_pct: float = 35.0
    # Catch cold fills like Aug4 v3=0.8 (was 0.5 — missed the caution band).
    explosion_faded_rip_max_live_velocity_3s: float = 1.0
    explosion_faded_rip_lot_cap: int = 6
    explosion_faded_rip_tighter_stop_mult: float = 0.85
    explosion_faded_rip_no_green_exit_enabled: bool = False
    explosion_faded_rip_no_green_seconds: int = 45
    explosion_faded_rip_min_green_points: float = 0.5
    faded_rip_no_green_hold_min_session_move_pct: float = 60.0
    # Peak-fade profit lock — Jul31 NIFTY 24500 CE: best +12.5pt then fade toward
    # losses while trailArm (~23pt) never armed. Book remaining green / breakeven
    # instead of waiting for hard SL.
    explosion_peak_fade_lock_enabled: bool = False
    explosion_peak_fade_min_best_points: float = 6.0
    explosion_peak_fade_giveback_ratio: float = 0.55
    explosion_peak_fade_min_giveback_points: float = 4.0
    explosion_peak_fade_min_remain_points: float = 0.4
    explosion_peak_fade_breakeven_lock: bool = True
    explosion_peak_fade_breakeven_buffer: float = 0.5
    # Small winners must not become meaningful losses when live premium rolls over.
    explosion_early_green_lock_enabled: bool = False
    explosion_early_green_lock_min_best_points: float = 3.5
    explosion_early_green_lock_buffer_points: float = 0.5
    explosion_early_green_lock_max_velocity_3s: float = 0.0
    # Near-base max-profit FTV: do NOT scratch a tiny +3–5pt early fade to BE
    # (Aug19 SENSEX 76900 PE: best +5 → early_green_breakeven in ~4m). Use the
    # near-base hold floor so these runners can extend like prior max winners.
    explosion_early_green_lock_near_base_max_profit_min_best_points: float = 55.0
    # ICT max-profit / flat→vertical runners: hold through early pullbacks.
    # Aug6 SENSEX 78700 CE: best +15 → soft-locked +6.5 (OVERCONFIDENCE tightened
    # giveback to 50%) then LTP ran to ~460. Require a real expansion peak first.
    explosion_peak_fade_max_profit_min_best: float = 28.0
    explosion_peak_fade_max_profit_giveback_ratio: float = 0.80
    # Still-bullish continuation can defer the soft giveback lock (healthy pullback).
    # Near-breakeven lock after a real peak ALWAYS fires — chart lag must not
    # turn winners into hard-SL losses.
    explosion_peak_fade_defer_when_bullish: bool = True
    explosion_peak_fade_bullish_min_remain_points: float = 3.0
    explosion_peak_fade_bullish_min_velocity_3s: float = 1.5
    # Peak capture — bank near the top once a real peak prints and premium rolls over.
    # Jul31 NIFTY 24500 CE: best ~+10–12pt, trailArm ~23 never armed, time-stop −0.6.
    # After best ≥8pt, a small giveback + dying live tape confirms the observed top.
    explosion_peak_capture_enabled: bool = False
    explosion_peak_capture_min_best_points: float = 8.0
    explosion_peak_capture_giveback_ratio: float = 0.12
    explosion_peak_capture_min_giveback_points: float = 1.0
    # Never wait through an unbounded percentage giveback on a large spike.
    explosion_peak_capture_max_giveback_points: float = 8.0
    explosion_peak_capture_min_remain_points: float = 1.0
    explosion_peak_capture_max_live_velocity_3s: float = 1.0
    explosion_peak_capture_max_premium_mom_pct: float = 0.15
    explosion_peak_capture_max_profit_min_best: float = 28.0
    explosion_peak_capture_max_profit_giveback_ratio: float = 0.35
    # Large confirmed-rollover peaks bank near the top instead of giving back a
    # third of a big rip. Ordinary trades tighten at +25pt (keep ~94%).
    explosion_peak_capture_big_peak_points: float = 25.0
    explosion_peak_capture_big_peak_giveback_ratio: float = 0.06
    # Max-profit FTV / local-base winners: do NOT clip at +25pt — those rips often
    # continue to 100%+ points. Only apply a soft near-top bank after a true
    # expansion peak (≥80pt), and keep more room than the ordinary 6% band.
    explosion_peak_capture_max_profit_big_peak_points: float = 80.0
    explosion_peak_capture_max_profit_big_peak_giveback_ratio: float = 0.28
    # Absolute giveback ceiling for max-profit AFTER the big-peak threshold only.
    # Mid-leg FTV (<80pt) uses ratio-only so an 8pt dip cannot bank before 100%+.
    # 0 = uncapped (ratio-only even after big peak). Default keeps a near-top bank
    # once the rip has fully expanded.
    explosion_peak_capture_max_profit_max_giveback_points: float = 24.0
    # Hold near-base top rips for the max move: an ELITE/EXPLODING entered very near the
    # local base (entry base-rel ≤ 20%) has the whole rip ahead, so don't soft-lock a
    # small early peak — require a bigger peak before peak-capture/peak-fade profit-lock.
    # Breakeven lock + armed-trail-into-loss still protect the downside. (Aug5 78400 PE:
    # entered 11% off base, peak-fade booked +₹149 instead of riding the base rip.)
    explosion_near_base_hold_enabled: bool = True
    explosion_near_base_hold_max_entry_rel_pct: float = 20.0
    # ICT flat→vertical / maxProfitCapture: hold further into the pad so mid-window
    # base entries (e.g. 25–40% off) still ride toward max TP instead of soft-locking.
    explosion_near_base_hold_ict_max_entry_rel_pct: float = 40.0
    # Align with max-profit fade floor — small +10–15pt peaks are still the base leg.
    # Local-base FTV aiming at 100%+ needs a higher soft-lock floor before banking.
    explosion_near_base_hold_min_best_points: float = 40.0
    explosion_near_base_hold_max_profit_min_best_points: float = 55.0
    # V / FTV from local base: expect ~100%+ premium expansion (e.g. 68→140).
    # Soft peak-capture must wait until that expansion prints, then trail for max TP.
    # Absolute point floors alone clip cheap ATM options too early (68→+28 is only ~41%).
    ftv_vbase_hundred_pct_hold_enabled: bool = True
    ftv_vbase_hundred_pct_min_move_pct: float = 100.0
    ftv_vbase_hundred_pct_max_entry_rel_pct: float = 25.0
    ftv_vbase_hundred_pct_min_best_points_floor: float = 40.0
    # After the 100% leg prints, allow a wider giveback so multi-bagger extensions
    # (68→220) are not banked on the first 28% dip off a mid peak.
    ftv_vbase_after_hundred_giveback_ratio: float = 0.25
    ftv_vbase_after_hundred_max_giveback_points: float = 36.0
    ftv_vbase_after_hundred_big_peak_points: float = 100.0

    # Peak prediction — index impulse × gamma + historical analogues + live ratchet.
    # NIFTY and SENSEX only; stamps predictedMaxLtp on entry for stage-ladder exits.
    peak_prediction_enabled: bool = True
    peak_prediction_gamma_weight: float = 0.35
    peak_prediction_analogue_weight: float = 0.40
    peak_prediction_structure_weight: float = 0.25
    peak_prediction_impulse_horizon_seconds: float = 90.0
    peak_prediction_nifty_max_impulse_pts: float = 120.0
    peak_prediction_sensex_max_impulse_pts: float = 180.0
    peak_prediction_min_move_pct: float = 15.0
    peak_prediction_max_move_pct: float = 250.0
    peak_prediction_sensex_max_move_pct: float = 300.0
    peak_prediction_analogue_min_samples: int = 3
    peak_prediction_live_ratchet_enabled: bool = True
    peak_prediction_ratchet_trigger_frac: float = 0.85
    peak_prediction_ratchet_hot_velocity_3s: float = 2.0
    peak_prediction_ratchet_hot_stretch: float = 1.12

    # Moment stage trail ladder — flat→vertical / FVG / mega-rip projections.
    # Project max TP from fib/base-extension/heat, split into stages (~50pt on
    # large moves), ratchet SL after each stage (250→225, 400→350) and hold
    # toward projectedMaxTp while above the stage floor.
    moment_stage_trail_enabled: bool = True
    moment_stage_count: int = 8
    moment_stage_min_size: float = 5.0
    moment_stage_max_size: float = 55.0
    # FTV runner %-of-peak-gain trailing floor. V/FTV moments run in big % from the local
    # base (e.g. Rs68 -> Rs140 = +106%). The absolute stage ladder is tuned for mega point
    # moves and under-protects modest-but-real % moves (a +40% peak can give back to +4%).
    # This trails a consistent fraction BEHIND the peak GAIN (keep 72% => exit ~28% off the
    # top) and is max'd WITH the stage ladder — so mega runners still ride the stages while
    # every real % move locks in the best TP it reached. Arms only after a real move.
    ftv_runner_pct_trail_enabled: bool = True
    ftv_runner_pct_trail_arm_pct: float = 25.0
    ftv_runner_pct_trail_keep_ratio: float = 0.75
    ftv_runner_pct_trail_min_best_points: float = 6.0
    moment_stage_min_projected_tp: float = 40.0
    # Allow rare 50→650 LTP mega rips (+600pt); live extension ratchets toward this.
    moment_stage_max_projected_tp: float = 800.0
    moment_stage_max_tp_frac_of_premium: float = 12.0
    moment_stage_mega_max_tp_frac_of_premium: float = 16.0
    moment_stage_base_extension_mult: float = 3.0
    moment_stage_mega_extension_mult: float = 4.0
    # Early vertical: project absolute premium targets (base×mult / entry×mult)
    # so entry ~50 from base ~40 aims for ~210, not a tiny leg-extension TP.
    moment_stage_base_premium_mult: float = 5.5
    moment_stage_entry_premium_mult: float = 4.2
    # Mega / parabolic: 50×14 ≈ 700 premium target (room for 50→650 LTP).
    moment_stage_mega_base_premium_mult: float = 16.0
    moment_stage_mega_entry_premium_mult: float = 14.0
    moment_stage_parabolic_entry_premium_mult: float = 13.0
    moment_stage_parabolic_min_velocity_3s: float = 8.0
    moment_stage_parabolic_min_volume_surge: float = 2.5
    moment_stage_early_vertical_min_tp: float = 160.0
    moment_stage_early_base_frac: float = 0.40
    moment_stage_early_max_already_points: float = 30.0
    moment_stage_ict_target_floor_frac: float = 0.90
    moment_stage_heat_velocity_3s: float = 3.0
    moment_stage_heat_volume_surge: float = 1.8
    moment_stage_giveback_ratio: float = 0.50
    moment_stage_late_giveback_ratio: float = 1.0
    moment_stage_late_progress: float = 0.70
    moment_stage_min_remain_points: float = 1.0
    moment_stage_extend_trigger_frac: float = 0.92
    # Live extension headroom (stages beyond best). Hot mega rips use the larger one.
    moment_stage_extend_stages: float = 2.0
    moment_stage_extend_hot_stages: float = 4.0
    moment_stage_extend_hot_velocity_3s: float = 2.5
    # While live heat is still expanding, do not squeeze late-stage giveback.
    moment_stage_hot_hold_velocity_3s: float = 2.5
    # Max-profit OTM sibling legs (Aug28 24100 PE +33 vs stage 40): arm stage trail
    # when best reaches this fraction of stageSize so same-cycle legs exit together.
    moment_stage_near_complete_frac: float = 0.82
    # Share observed peak PnL across open legs from the same entry cycle (symbol+side).
    cycle_moment_peak_sync_enabled: bool = True
    cycle_moment_peak_sync_min_gain_pct: float = 50.0
    # Before the first stage completes, suppress the micro step trail (best−3.5pt)
    # so a normal dip cannot cut a still-projecting ICT rip (e.g. 392→500).
    explosion_trail_pre_stage_suppress_step: bool = True
    # While live velocity is still hot and below projected max, defer explosion_trail_sl.
    explosion_trail_hot_defer_enabled: bool = True

    # Fake explosion trap — Jul20 NIFTY 24300 CE: RANGE + midday_chop + ELITE vel spike,
    # session~30%, live premium mom≈0, OTM inside OR after small win → never-green −₹18k.
    # Market harvests FOMO; system must not treat post-extension spikes as ELITE full-size.
    fake_explosion_trap_enabled: bool = True
    fake_explosion_trap_min_session_move_pct: float = 28.0
    # Chase / extension threshold for trap flags (defaults to early-window max 55%).
    # Must stay ABOVE base-window entries — 28% wrongly blocked Jul15 ATM ELITE winners.
    fake_explosion_trap_extended_move_pct: float = 55.0
    fake_explosion_trap_max_premium_mom_pct: float = 0.15
    fake_explosion_trap_block_on_conflict: bool = True
    fake_explosion_trap_min_conflict_flags: int = 3
    # Aug18: EXPIRY WORST + midday chop + EXPLODING only soft-capped; restore hard block.
    fake_explosion_trap_block_worst_midday_chop: bool = True
    fake_explosion_trap_chop_elite_lot_cap: int = 6
    fake_explosion_trap_otm_requires_or_breakout: bool = True
    fake_explosion_trap_post_win_lot_cap: int = 8
    fake_explosion_trap_post_win_max_pnl_inr: float = 3_000.0
    fake_explosion_trap_post_win_lookback: int = 1
    # Aug28: post-win 8-lot probe on v3=-0.38 micro-pullback → adaptive SL −₹3.5k.
    # Hard-block re-entry when live v3 is dead; midday chop needs hot re-acceleration.
    fake_explosion_trap_post_win_velocity_block_enabled: bool = True
    fake_explosion_trap_post_win_min_velocity_3s: float = 0.0
    fake_explosion_trap_post_win_midday_min_velocity_3s: float = 1.0
    # Aug28 12:55: armed-base prelaunch must not bypass post-win cold-velocity block.
    fake_explosion_trap_post_win_armed_base_bypass_enabled: bool = False
    # Post-win re-entry only when top-rank / full-sleeve OR hot re-acceleration — no 8-lot FOMO probes.
    fake_explosion_trap_post_win_require_top_confidence: bool = True
    fake_explosion_trap_post_win_hc_min_velocity_3s: float = 2.0
    fake_explosion_trap_psychology_escalate: bool = True
    # Midday/chop ELITE without ICT structure → hard block (not soft lot-cap).
    fake_explosion_trap_midday_require_structure: bool = True
    # Size until first green — no full-size explosions before a proven green (Jul20 FOMO).
    size_until_first_green_enabled: bool = True
    size_until_first_green_lot_cap: int = 6
    # Modes capped until a green print in that mode (Jul20 never-green oversize: explosion + scalp).
    size_until_first_green_modes_csv: str = "explosion,scalp"
    # Unlock only on a closed winner (pnl>0). Fleeting best≥1pt on a red scalp
    # (Jul29 NIFTY 24100 best+1.5 then −₹72) must NOT unlock 32-lot SENSEX size.
    size_until_first_green_require_closed_win: bool = True
    # Scalp never-green grace — high-conf ITM dips (Jul29 77500 CE 279→273→286)
    # get a short wider floor before simple_stop_loss kills the rip.
    scalp_never_green_grace_enabled: bool = True
    scalp_never_green_grace_seconds: float = 150.0
    scalp_never_green_stop_mult: float = 2.5
    scalp_never_green_min_chart_confidence: float = 55.0
    scalp_never_green_min_premium_inr: float = 80.0
    # Size-tune must not crush premium-based SL below this fraction (oversized lots).
    position_sl_preserve_natural_frac: float = 0.45
    # High-conviction override — take MAX lots + hold longer when a genuine base rip is
    # very high confidence (ELITE, score≥90, chartConf≥85, matched side, 28-55% window).
    # Bypasses the first-green + defensive throttles; fake-trap chop cap still applies.
    high_conviction_sizing_enabled: bool = True
    high_conviction_min_score: float = 90.0
    # Cold ELITE must not force max lots (Aug4 24550 PUT v3=0.8 + HC → −₹22k).
    high_conviction_min_velocity_3s: float = 2.0
    # Rescaled chartConf cutover (was 85 on the old 20–95 clamp). Same raw gate after
    # linear map raw[40,200]→[40,100]: rescale(85)≈56.9.
    high_conviction_min_chart_confidence: float = 56.9
    # Wider trail so high-conviction runners hold the move instead of booking at ~38% of peak.
    high_conviction_trail_keep_ratio: float = 0.30
    high_conviction_defer_profit_lock: bool = True
    # Never-green grace for ICT/HC ATM base rips (Jul23 76300 PE killed ~90s at best=0).
    # 150s gives the vertical a bit more room to print first green before adaptive SL.
    base_rip_never_green_grace_seconds: float = 150.0
    base_rip_never_green_stop_mult: float = 2.0
    # Composer bias: allow ICT flat→vertical explosions (not only ELITE).
    composer_ict_flat_vertical_bias_bypass: bool = True
    # Base-relative chase: ignore huge session % when base_rel is still early-window.
    ict_base_relative_ignore_abs_cap: bool = True
    # Elevated size tier — strong EXPLODING/ELITE base rip below full high-conviction.
    # 1.5x base size when score>=65 + chartConf>=58.8 + matched + 28-55% window.
    # (was chartConf>=90 on the old clamp; rescale(90)≈58.8)
    elevated_size_enabled: bool = True
    elevated_size_min_score: float = 65.0
    elevated_size_min_chart_confidence: float = 58.8
    elevated_size_lot_scale: float = 1.5
    # Confirmed flat→vertical base rips (qualified via base-relative move) are the genuine
    # runners — scale them harder (~2x) to actually double the capture vs a base-size entry.
    elevated_size_base_relative_lot_scale: float = 2.0
    # Top explosion (ELITE/EXPLODING) → always capital max lots on first take.
    # Jul29 77500 CE ELITE score 47.8 missed HC/elevated windows → 6-lot first-green
    # scratch of a +54pt rip; re-entry ELITE 100 finally max-sized and lost.
    top_explosion_force_max_lots_enabled: bool = True
    top_explosion_force_max_tiers_csv: str = "ELITE,EXPLODING"
    top_explosion_force_max_min_chart_confidence: float = 55.0
    top_explosion_force_max_require_aligned: bool = True
    top_explosion_force_max_bypasses_first_green: bool = True
    top_explosion_force_max_bypasses_fake_trap_lot_cap: bool = True
    # Every explosion entry uses full capital max lots — no 6-lot first-green / 3-lot
    # cold-timing / 35% ordinary-cap throttles (Aug25 EXPLODING 100 took 3 lots).
    explosion_always_force_max_lots: bool = True
    # Only block force-max on true CHOP/WORST days — not mere RANGE_BOUND (Jul29 #8).
    top_explosion_force_max_block_day_types_csv: str = "CHOP,WORST"
    # After booking profit on an explosive at symbol+side+strike, next entry on that
    # exact strike is lot-capped (Jul29 77500 CE +₹5.8k @6 → re-entry 29 lots −₹11k).
    # After a same-strike win, allow full capital lots on the next vertical
    # (multiple flat→vertical moments in one day). Set true only if you want
    # the old Jul29 protective soft-cap behavior.
    explosion_post_win_same_strike_lot_cap_enabled: bool = False
    explosion_post_win_same_strike_lot_cap: int = 6
    # Session mode feedback — promote/demote modes from today's PF (closes learning loop).
    session_mode_feedback_enabled: bool = True
    session_mode_feedback_min_trades: int = 2
    # Composer advisory → hard gate (standDown / side bias).
    composer_hard_gate_enabled: bool = True
    composer_bias_gate_enabled: bool = True
    # A confirmed TOP explosion (ELITE/EXPLODING) off a local base overrides advisory
    # stand-asides on ANY day — composer stand-down, composer opposing-bias, and the
    # worst-day PAUSED halt (Jul24: composer STAND_ASIDE on a chop day buried 17/18
    # flat→vertical rips incl. NIFTY 24000 CE +61%). "Never miss the best base rips."
    # Bounded: top tier + score≥floor + confirmed local base in the early window (which
    # enforces the 15–40% base-relative window + adverse-momentum cap). Scalps, low
    # tiers/scores, late chases, and hard live-dumps still respect every gate.
    top_explosion_local_base_bypass_enabled: bool = True
    top_explosion_local_base_bypass_tiers_csv: str = "ELITE,EXPLODING"
    top_explosion_local_base_bypass_min_score: float = 62.0
    # Never force ICT max lots on chop/RANGE (good-day override was Jul49-lot hole).
    ict_force_max_lots_block_on_chop: bool = True
    # High-mover / all-in bypasses must not reopen late chases.
    high_mover_bypass_max_move_pct: float = 55.0
    extreme_all_in_bypass_max_move_pct: float = 55.0
    explosion_macd_alignment_required: bool = True
    # Sub-band deep-OTM scan bypass floor. With ATM+ITM-only scan this is inert;
    # keep aligned to min_option_premium so cheap OTM never re-enters radar.
    explosion_deep_otm_min_premium_inr: float = 18.0
    # Enter ATM/ITM by default, but retain premium tape for one liquid listed strike
    # beyond the ATM band so a contract that rotates ATM does not lose its real base.
    # Deep OTM and sub-band premiums remain excluded.
    explosion_scan_atm_itm_only: bool = True
    explosion_shallow_otm_history_steps: int = 1
    explosion_shallow_otm_history_min_volume: int = 25000
    explosion_volume_awaken_min: int = 25000
    explosion_volume_awaken_min_velocity_3s: float = 1.0
    explosion_target_elite: float = 25.0
    explosion_target_standard: float = 12.0
    explosion_micro_target_points: float = 3.0
    explosion_trail_arm_points: float = 4.0
    explosion_trail_keep_ratio: float = 0.65
    explosion_trail_step_points: float = 3.5
    explosion_trail_tight_arm: float = 12.0
    explosion_trail_tight_points: float = 5.0
    explosion_initial_stop_points: float = 6.0
    # Soft ceiling for explosion SL (points). Absolute last-resort cap only —
    # prefer premium-relative ceiling so high-premium ELITE/EXPLODING keeps a
    # calculated stop instead of collapsing to a flat ~8–10pt hold (Jul30).
    explosion_stop_abs_max_points: float = 40.0
    # Explosion SL as a fraction of entry premium (before score/velocity widen).
    explosion_stop_pct_of_premium: float = 0.10
    # Premium-relative soft ceiling: min(abs_max, max(12, premium × this)).
    explosion_stop_max_pct_of_premium: float = 0.18
    # After chart merge / edge / size-tune, never crush SL below this fraction
    # of the natural (premium×structure×score) stop for explosion entries.
    explosion_chart_stop_min_natural_frac: float = 0.85
    explosion_sl_preserve_natural_frac: float = 0.85
    # Every trade: place SL at local support (premium base / index swing / pivot),
    # not a weighted blend toward the nearest tiny structure.
    exit_sl_use_local_support: bool = True
    # Extra room beyond the support level (fraction of entry premium).
    exit_sl_local_support_buffer_pct: float = 0.02
    # Ignore structure closer than this (noise pivots that map to ~4pt "toy" stops).
    exit_sl_local_support_min_premium_frac: float = 0.06
    exit_sl_local_support_min_points: float = 5.0
    # Chart confidence at/above this confirms local-support SL (high-conf runners
    # are expected to move up without retesting; do not tighten toward noise).
    exit_sl_chart_confirm_min_confidence: float = 70.0
    explosion_stop_min_hold_seconds: int = 15
    explosion_no_progress_enabled: bool = False
    explosion_no_progress_seconds: int = 150
    explosion_no_progress_aligned_seconds: int = 420
    explosion_no_progress_skip_when_aligned: bool = True
    # Jul29 77600 CE: explosion_time_profit @ +0.3pt / best +5.5 vs TP 37, then LTP→290.
    # Skip green time-exit on ELITE/EXPLODING while still below target; let trail/SL/TP work.
    explosion_skip_time_profit_enabled: bool = True
    explosion_skip_time_profit_tiers_csv: str = "ELITE,EXPLODING"
    explosion_skip_time_profit_until_target_frac: float = 0.85
    explosion_elite_max_hold_seconds: int = 1800
    # Structured thesis hold — Aug4 NIFTY 24550 PUT: best +8.5 then time-stopped
    # red at ~44min while LTP later ran 90–100. Once ICT/HC trades go green,
    # skip time-stop entirely (trail/SL/TP manage). Never-green losers (Aug3
    # best~0) keep the short elite clock.
    explosion_thesis_hold_enabled: bool = True
    explosion_thesis_hold_min_best_points: float = 2.0  # as soon as meaningfully green
    explosion_thesis_hold_max_seconds: int = 10800  # fallback cap if skip-time disabled
    explosion_thesis_hold_skip_time_exit: bool = True  # no time_stop once thesis is green
    explosion_reentry_cooldown_seconds: int = 180
    explosion_emergency_cooldown_seconds: int = 300
    # A just-captured FTV peak remains exhausted until this exact CE/PE contract
    # builds a fresh post-close base and accelerates again.
    explosion_post_peak_reentry_guard_enabled: bool = True
    explosion_post_peak_reentry_lookback_seconds: int = 1800
    explosion_post_peak_reentry_min_peak_points: float = 20.0
    explosion_post_peak_reentry_near_peak_pct: float = 15.0
    explosion_post_peak_reentry_base_samples: int = 3
    explosion_post_peak_reentry_base_span_seconds: float = 6.0
    explosion_post_peak_reentry_min_reacceleration_pct: float = 8.0
    explosion_post_peak_reentry_min_velocity_3s: float = 1.5
    # Block re-entry on a strike that already ripped to session peak and is still
    # trading near the top on weak velocity (Aug25 24250 PE ₹121 peak → ₹110 chase).
    explosion_late_reentry_block_enabled: bool = True
    explosion_late_reentry_min_peak_points: float = 15.0
    explosion_late_reentry_near_peak_pct: float = 12.0
    explosion_late_reentry_pullback_ok_pct: float = 22.0
    explosion_late_reentry_min_velocity_3s: float = 1.2
    explosion_breadth_alignment_enabled: bool = True
    # Hard block PUT on BULLISH / CALL on BEARISH — no ELITE or premium-led bypass
    breadth_hard_side_block_enabled: bool = True
    # When option-chain OI breadth lags a live rally/selloff, trust chart+MTF over OI
    chart_mtf_breadth_bypass_enabled: bool = True
    chart_mtf_breadth_bypass_min_explosion_score: float = 42.0
    chart_mtf_breadth_bypass_min_aligned: int = 3
    chart_mtf_breadth_bypass_min_rsi: float = 52.0
    explosion_single_side_per_symbol: bool = True
    explosion_dominant_side_min_score: float = 50.0
    explosion_exhaustion_v15_pct: float = 18.0
    explosion_exhaustion_consolidation_reset_enabled: bool = True
    explosion_exhaustion_reset_minutes: int = 12
    explosion_exhaustion_consolidation_v3_max: float = 1.2
    explosion_exhaustion_consolidation_v9_max: float = 2.0
    explosion_high_premium_threshold_inr: float = 90.0
    explosion_high_premium_lot_cap: int = 15

    # Directional lock — aligned side default; CE↔PE switch only on full confirmation
    directional_side_lock_enabled: bool = True
    directional_sticky_per_symbol: bool = True
    directional_lock_use_chart: bool = True
    directional_lock_block_chart_counter: bool = True
    directional_switch_min_confirmations: int = 5
    directional_switch_min_velocity_pct: float = 2.5
    directional_switch_min_explosion_score: float = 55.0
    directional_switch_min_runner_score: float = 60.0
    directional_switch_min_trend_strength: float = 50.0
    # Best-side selection — follow dominant CE/PE leg all session (incl. power-hour flip).
    best_side_selection_enabled: bool = True
    best_side_min_velocity_3s: float = 2.0
    best_side_min_velocity_ratio: float = 1.4
    best_side_min_explosion_score: float = 45.0
    best_side_power_hour_min_velocity_3s: float = 1.8
    best_side_power_hour_min_velocity_ratio: float = 1.3
    best_side_directional_lock_bypass_enabled: bool = True
    best_side_power_hour_bypass_enabled: bool = True
    best_side_rank_bonus: float = 25.0
    best_side_counter_rank_penalty: float = 18.0
    best_side_global_rank_bonus: float = 15.0
    best_side_fading_waive_bonus: float = 20.0
    # Session side-regime & flip detector — one confirmed CALL/PUT regime per symbol that
    # only flips after sustained confirmation (min_confirms consecutive confident votes over
    # min_seconds). A confident vote needs >= min_vote_confidence of {index chart+mom5,
    # dominant option leg, tape-confirmed index drift} agreeing. Ranking prefers the confirmed
    # side and helps (not fights) the in-progress flip target. Selection-only; never gates the
    # live trigger/exit. Observe-only if side_regime_influences_ranking=false.
    side_regime_enabled: bool = True
    side_regime_influences_ranking: bool = True
    side_regime_min_chart_mom5_pct: float = 0.05
    side_regime_min_vote_confidence: int = 2
    side_regime_flip_min_confirms: int = 3
    side_regime_flip_min_seconds: float = 20.0
    side_regime_rank_bonus: float = 15.0
    side_regime_counter_penalty: float = 15.0
    side_regime_flip_target_bonus: float = 6.0
    # EOD replay — apply live session gates (power hour, directional lock, best-side).
    eod_replay_live_session_gates_enabled: bool = True

    # Symbol / instrument cooldown — stop same-strike churn after losses
    symbol_loss_cooldown_seconds: int = 180
    symbol_emergency_cooldown_seconds: int = 300
    symbol_streak_cooldown_seconds: int = 600
    reentry_score_penalty_per_loss: int = 5
    instrument_loss_cooldown_seconds: int = 300
    instrument_micro_win_cooldown_seconds: int = 180
    instrument_win_cooldown_seconds: int = 90
    instrument_max_entries_per_day: int = 3
    # Exact-leg defer after execution-time premium fade; another leg may win next scan.
    preorder_rejection_suppression_seconds: int = 30
    # Jul27 scalp churn: tiny win @6 lots → full size @24/25 → stop → repeat same CE.
    # Longer same-strike cooldowns + hard daily cap for scalp only.
    scalp_instrument_win_cooldown_seconds: int = 600
    scalp_instrument_loss_cooldown_seconds: int = 900
    scalp_max_entries_per_strike_per_day: int = 2
    block_duplicate_open_leg: bool = True
    counter_breadth_min_score: int = 70

    # Controlled trading — pre-trade backtest + fewer entries
    controlled_trading_enabled: bool = True
    controlled_max_trades_per_day: int = 10
    controlled_rally_trade_cap_bonus: int = 4
    min_seconds_between_entries: int = 240
    pretrade_min_rank_score: float = 52.0
    pretrade_min_symbol_trades_for_stats: int = 3
    pretrade_block_symbol_pf_below: float = 0.5
    pretrade_block_symbol_net_inr_below: float = -15_000.0
    pretrade_similar_side_lookback: int = 5
    pretrade_similar_side_min_trades: int = 3
    pretrade_block_similar_pf_below: float = 0.4
    index_selection_pf_bonus: float = 12.0

    # Last-N trades gate — check last 5 before any new entry
    last_n_trades_gate_enabled: bool = True
    last_n_trades_lookback: int = 5
    last_n_trades_min_count: int = 3
    last_n_pause_after_losses: int = 4
    last_n_elevate_after_losses: int = 3
    last_n_elevated_min_rank_score: float = 72.0
    last_n_block_pf_below: float = 0.35
    last_n_block_net_inr_below: float = -25_000.0
    last_n_momentum_rally_bypass_enabled: bool = True

    # Best trades only — fewer, higher-quality entries
    best_trades_only_enabled: bool = True
    best_trades_min_rank_score: float = 52.0
    best_trades_explosion_only_after_losses: int = 3

    # Whipsaw / churn — CE↔PE flip-flops in bearish sideways chop
    whipsaw_guards_enabled: bool = True
    post_exit_min_seconds: int = 120
    post_loss_exit_min_seconds: int = 300
    chop_session_entry_interval_seconds: int = 300
    opposite_side_cooldown_seconds: int = 420
    opposite_side_cooldown_after_loss_seconds: int = 600
    ce_pe_whipsaw_velocity_threshold: float = 1.2
    ce_pe_whipsaw_pause_seconds: int = 900
    flip_flop_lookback_trades: int = 6
    flip_flop_max_opposites: int = 2
    whipsaw_momentum_rally_bypass_enabled: bool = True
    whipsaw_dual_retrigger_cooldown_seconds: int = 300
    whipsaw_single_side_surge_bypass_enabled: bool = True
    whipsaw_dominant_velocity_min: float = 2.5
    whipsaw_dominant_velocity_ratio: float = 1.6
    bearish_sideways_halt_enabled: bool = True
    bearish_sideways_block_scalps: bool = True
    bearish_sideways_explosion_min_score: float = 78.0
    # Local-base CE may clear sideways at 75 (aligns with moneyness OTM bypass floor).
    bearish_sideways_local_base_min_score: float = 75.0

    # High-confidence hold — don't micro-exit then immediately re-enter same setup
    high_confidence_hold_enabled: bool = True
    high_confidence_min_score: float = 72.0
    high_confidence_max_hold_multiplier: float = 1.8
    high_confidence_micro_min_best_points: float = 6.0
    high_confidence_min_hold_before_micro_seconds: int = 180
    high_confidence_micro_giveback_points: float = 4.5
    high_confidence_trail_keep_ratio: float = 0.55
    high_confidence_reentry_cooldown_seconds: int = 600
    high_confidence_reentry_score_uplift: float = 5.0
    # Chart-confidence hold — ride to TP when MTF/chart conf is high
    chart_confidence_hold_enabled: bool = True
    # Was 62 on old clamp; rescale(62)≈48.2 on the 40–100 display scale.
    chart_confidence_hold_min_confidence: float = 48.2
    chart_confidence_hold_min_target_pct: float = 0.85
    chart_confidence_half_tp_lock_pct: float = 0.50
    chart_confidence_half_tp_giveback_ratio: float = 0.40
    chart_confidence_hold_defer_stop_seconds: int = 180
    chart_confidence_hold_max_seconds: int = 600
    chart_confidence_hold_stop_mult: float = 1.35
    # Elevated hold path (was hardcoded chartConf>=85); rescale(85)≈56.9.
    chart_confidence_elevated_threshold: float = 56.9
    # Defer to chart TP / block early profit-lock (was hardcoded >=95); rescale(95)≈60.6.
    chart_confidence_defer_tp_min: float = 60.6
    # Runner hold without breadth align (was all_day_min+16=78); rescale(78)≈54.2.
    chart_confidence_runner_hold_min: float = 54.2

    # Executable strikes are always ATM/ITM. A legacy OTM mode value is normalized
    # to ATM; shallow OTM may still be monitored for history but never ordered.
    moneyness_selection_enabled: bool = True
    trade_moneyness_mode: str = "AUTO"  # AUTO | ITM | ATM
    moneyness_atm_tolerance_points: float = 50.0
    # Real listed strike intervals — NIFTY is 50, SENSEX/BANKNIFTY are 100. The old
    # hardcoded 100 for NIFTY halved its OTM-depth counting (deep-OTM guards too loose).
    nifty_strike_step: float = 50.0
    sensex_strike_step: float = 100.0
    banknifty_strike_step: float = 100.0
    moneyness_max_otm_steps: int = 2
    expiry_explosion_max_otm_steps: int = 4
    moneyness_max_itm_steps: int = 2
    # Expiry-day ITM CE+PE monitor — cover most liquid ITM strikes on both sides
    # (ATM±2 was too narrow; Jul28 24050 PE rip sat outside the watched ATM cluster).
    expiry_itm_monitor_enabled: bool = True
    expiry_max_itm_steps: int = 6
    expiry_itm_candidate_limit: int = 12
    expiry_itm_scan_range: int = 800
    expiry_sensex_itm_scan_range: int = 1200
    expiry_itm_both_sides: bool = True
    moneyness_explosion_prefer: str = "ATM"
    # Legacy compatibility fields; execution enforces ATM/ITM independently.
    moneyness_explosion_block_otm: bool = True
    moneyness_explosion_atm_itm_only: bool = True
    moneyness_scalp_chop_prefer: str = "ITM"
    moneyness_high_conf_prefer: str = "ITM"
    moneyness_rank_bonus: float = 12.0
    moneyness_mismatch_penalty: float = 15.0
    # Base-window (28–55%) structured rips must not get fake-trap soft lot-cap of 6.
    # Jul23 ATM/ITM keep; Jul31 NIFTY 24500 CE (2-step OTM + local base) was wrongly
    # cut to 6 lots — allow near-OTM ≤ moneyness_local_base_max_otm_steps too.
    fake_explosion_trap_skip_soft_cut_base_window: bool = True
    fake_explosion_trap_skip_soft_cut_near_otm: bool = True
    # Aug6: chop+elite_hot cut_size(6) was restored to 27 by baseWindowFullLots /
    # top_explosion soft-cap bypass. On chop/worst conflict stacks, honor the soft cap.
    fake_explosion_trap_honor_soft_cap_on_chop: bool = True
    # Index-confirmed FTV + structured local-base rip keeps capital max lots on chop/worst
    # days (Sep1 NIFTY 23950 CE: eliteFullLot authorized but chop+elite soft cap → 6).
    index_confirmed_ftv_bypasses_fake_trap_lot_cap: bool = True
    # High-conviction max lots win over fake-trap soft cap (hard block still applies).
    high_conviction_bypasses_fake_trap_lot_cap: bool = True
    # Structured base-window explosions take capital max lots (no first-green 6-lot throttle).
    base_window_full_lots_enabled: bool = True
    # DEFENSIVE/worst base rips: full capital lots (was 0.55 → under-sized Jul31 6-lot entry).
    ict_defensive_base_rip_full_lots: bool = True

    # Expiry-day playbook — fewer trades, morning focus, worst-day prediction
    expiry_day_guards_enabled: bool = True
    expiry_max_trades_per_day: int = 6
    expiry_worst_day_max_trades: int = 3
    expiry_morning_only: bool = True
    expiry_morning_end_hour: int = 13
    expiry_morning_end_minute: int = 30
    # Hard stop for generic expiry entries after 15:00 — top FTV/V/ELITE/explosives bypass.
    expiry_evening_block_enabled: bool = True
    expiry_evening_block_hour: int = 15
    expiry_evening_block_minute: int = 0
    # Power hour on all sessions — only top trades after 15:00 until 15:30 close.
    power_hour_top_only_enabled: bool = True
    power_hour_start_hour: int = 15
    power_hour_start_minute: int = 0
    power_hour_end_hour: int = 15
    power_hour_end_minute: int = 30
    expiry_min_rank_score: float = 62.0
    expiry_cheap_premium_threshold_inr: float = 55.0
    expiry_cheap_premium_lot_cap: int = 55
    expiry_low_tqs_lot_cap_tqs: float = 40.0
    expiry_low_tqs_lot_cap: int = 15
    expiry_scalp_min_symbol_tqs: float = 38.0
    expiry_counter_breadth_elite_only: bool = True
    expiry_worst_day_min_rank_score: float = 72.0
    expiry_worst_day_score_threshold: float = 55.0
    expiry_worst_day_session_loss_inr: float = -12_000.0
    expiry_decline_session_loss_inr: float = -8_000.0
    expiry_worst_day_loss_count: int = 2
    expiry_worst_day_halt_entries: bool = True
    # On expiry worst + declining, still allow top ELITE explosions (not scalp/noise).
    # Session halt lifts only when an early-window elite top is on radar; late chase stays blocked.
    expiry_worst_day_elite_top_bypass_enabled: bool = True
    # Base-window matched rips: ELITE or EXPLODING, score ≥62, 28–55% move, premium in band.
    # Widened from ELITE/70 so matched PUT base rips (Jul21 EXPLODING score 50–65) can enter.
    expiry_worst_day_elite_top_min_score: float = 62.0
    expiry_worst_day_elite_top_min_move_pct: float = 28.0
    # Ceiling raised 55→70 (the chase ceiling): a fast matched rip (SENSEX 76500 PE
    # Jul23) blew past 55% before its explosion score confirmed ≥62, so the old
    # score-AND-move≤55 window never aligned. 70 still blocks >70% late chases.
    expiry_worst_day_elite_top_max_move_pct: float = 70.0
    expiry_worst_day_elite_top_tiers_csv: str = "ELITE,EXPLODING"
    expiry_worst_day_elite_top_composer_bypass: bool = True
    # daily_trade_cap_N>=3_expiry_worst must not skip ELITE / top EXPLODING —
    # lift the hard session cap and restrict to elite-top only (same gates).
    expiry_worst_day_elite_top_bypasses_trade_cap: bool = True
    # Grade-A FTV first-lift on NIFTY/SENSEX — lifts expiry worst-day declining halt and
    # lowers score/rank floors (Aug27 SENSEX 77300 PUT: EXPLODING grade A, score 33).
    grade_a_ftv_first_lift_enabled: bool = True
    grade_a_ftv_first_lift_symbols_csv: str = "NIFTY,SENSEX"
    grade_a_ftv_first_lift_min_explosion_score: float = 20.0
    grade_a_ftv_first_lift_min_quality: float = 55.0
    grade_a_ftv_first_lift_min_rank: float = 40.0
    grade_a_ftv_first_lift_min_base_move_pct: float = 8.0
    grade_a_ftv_first_lift_max_base_move_pct: float = 45.0
    # Aug17 afternoon CALL cluster: keep rank-1 BEARISH winners @ 28–31% baseRel;
    # max baseRel cap catches 50–64% chase; rank-2 afternoon NEUTRAL catches fee039db.
    grade_a_ftv_counter_breadth_block_enabled: bool = False
    grade_a_ftv_counter_breadth_min_base_rel_pct: float = 45.0
    # Also block when breadth is not side-aligned (NEUTRAL) above the same floor.
    grade_a_ftv_non_aligned_breadth_block_enabled: bool = False
    grade_a_ftv_afternoon_neutral_chase_block_enabled: bool = True
    grade_a_ftv_afternoon_neutral_start_hour: int = 12
    grade_a_ftv_afternoon_neutral_call_only: bool = True
    grade_a_ftv_afternoon_neutral_rank2_only: bool = True
    grade_a_ftv_afternoon_neutral_min_base_rel_pct: float = 20.0
    expiry_worst_day_grade_a_ftv_bypass_enabled: bool = True
    grade_a_ftv_chart_bypass_enabled: bool = True
    # Broader top FTV/V/ELITE/EXPLODING bypass on NIFTY/SENSEX expiry worst days —
    # lifts declining halt, trade cap, worst-day pause, score/rank/chart floors.
    top_ftv_v_expiry_bypass_enabled: bool = True
    top_ftv_v_expiry_bypass_symbols_csv: str = "NIFTY,SENSEX"
    top_ftv_v_expiry_bypass_min_explosion_score: float = 12.0
    top_ftv_v_expiry_bypass_min_rank: float = 0.0
    top_ftv_v_expiry_bypass_min_base_move_pct: float = 5.0
    top_ftv_v_expiry_bypass_max_base_move_pct: float = 55.0
    top_ftv_v_expiry_chart_bypass_enabled: bool = True
    expiry_worst_day_top_ftv_v_bypass_enabled: bool = True
    expiry_worst_day_top_ftv_v_bypasses_trade_cap: bool = True
    # Master switch for session-lift when top FTV/V / ELITE / explosive is on radar.
    top_signal_session_lift_enabled: bool = True
    last_n_top_signal_bypass_enabled: bool = True
    whipsaw_top_signal_bypass_enabled: bool = True
    controlled_cap_top_signal_bypass_enabled: bool = True
    expiry_dual_scalp_mode: bool = True
    expiry_dual_scalp_relax_whipsaw: bool = True
    expiry_dual_scalp_opposite_cooldown_seconds: int = 90
    expiry_explosion_open_block_minutes: int = 5

    # Expiry PM ITM quick scalps — day-of / next-day expiry, 14:00–15:30 IST
    expiry_pm_itm_quick_enabled: bool = True
    expiry_pm_itm_window_start_hour: int = 14
    expiry_pm_itm_window_start_minute: int = 0
    expiry_pm_itm_window_end_hour: int = 15
    expiry_pm_itm_window_end_minute: int = 30
    expiry_pm_itm_premium_max_inr: float = 280.0
    expiry_near_expiry_premium_max_inr: float = 300.0
    # Deep ITM on expiry — resting LTP can exceed ₹650 before the vertical prints.
    # Aug26 SENSEX 78200–78400 PUT (42–44% peaks) never reached radar when scan clipped at 500pt.
    expiry_itm_explosion_scan_max_premium_inr: float = 900.0
    expiry_pm_itm_min_velocity_pct: float = 0.35
    expiry_pm_itm_min_rank_score: float = 52.0
    expiry_pm_itm_chart_bypass_breadth: bool = True
    expiry_pm_itm_alternate_index_enabled: bool = True
    # PM ITM window normally restricts to quick ITM scalps on alternates; allow
    # ELITE/EXPLODING local-base explosion on the expiry symbol itself (Aug25
    # NIFTY CALL 24200 +138% MFE blocked by expiry_pm_itm_quick_only).
    expiry_pm_itm_local_base_explosion_bypass_enabled: bool = True
    expiry_pm_itm_local_base_min_explosion_score: float = 75.0
    expiry_pm_itm_local_base_min_move_pct: float = 2.0
    expiry_pm_itm_local_base_max_move_pct: float = 25.0
    # Legacy pre-expiry alternate routing — disabled in favor of near-expiry priority
    # when expiry_day_prefer_same_day_enabled (nearest expiry index wins).
    pre_expiry_cross_index_enabled: bool = True
    pre_expiry_symbol_rank_penalty: float = 12.0
    pre_expiry_alternate_min_rank: float = 55.0
    pre_expiry_expiry_symbol_explosion_min_rank: float = 45.0
    # Weekly: Tue NIFTY / Thu SENSEX. Priority = nearest expiry first, then flips.
    # Tue: NIFTY #1; Wed (SENSEX tomorrow): SENSEX #1; Thu: SENSEX #1; etc.
    expiry_day_prefer_same_day_enabled: bool = True
    expiry_day_symbol_rank_bonus: float = 22.0
    expiry_day_sort_priority_bonus: float = 30.0
    # #2 when peer expires within a few days (Tue NIFTY → Thu SENSEX = +2d).
    expiry_day_same_week_next_rank_bonus: float = 12.0
    expiry_day_same_week_next_sort_bonus: float = 15.0
    expiry_day_same_week_next_max_days: int = 3
    # Soften LTP floor slightly on same-day expiry so ~₹15–20 near-base rips clear.
    expiry_day_min_option_premium_inr: float = 15.0
    expiry_aligned_explosion_trade_bypass_enabled: bool = True
    expiry_aligned_explosion_chart_bypass_enabled: bool = True

    # Slow bounce — expensive ITM mean-reversion (RSI/MACD recovery, low velocity)
    quick_sideways_slow_bounce_enabled: bool = False
    quick_sideways_slow_bounce_premium_min_inr: float = 90.0
    quick_sideways_slow_bounce_min_velocity_pct: float = 0.1
    quick_sideways_slow_bounce_min_tqs: float = 28.0
    quick_sideways_slow_bounce_min_rank_score: float = 55.0
    quick_sideways_slow_bounce_rsi_min: float = 40.0
    quick_sideways_slow_bounce_rsi_max: float = 55.0
    quick_sideways_slow_bounce_macd_hist_min: float = -15.0

    # Morning slow-bounce — post-spike ITM consolidation (10:30–13:30 near-expiry)
    morning_slow_bounce_enabled: bool = True
    morning_slow_bounce_start_hour: int = 10
    morning_slow_bounce_start_minute: int = 30
    morning_slow_bounce_end_hour: int = 13
    morning_slow_bounce_end_minute: int = 30
    morning_slow_bounce_rsi_min: float = 45.0
    morning_slow_bounce_rsi_max: float = 60.0
    morning_slow_bounce_macd_hist_min: float = -20.0
    morning_slow_bounce_max_velocity_pct: float = 1.8

    # Psychology setup hold — FEAR/CAUTION entries held longer on expiry chop
    psychology_hold_enabled: bool = True
    psychology_hold_labels_csv: str = "FEAR,CAUTION"
    psychology_hold_min_score: float = 68.0
    psychology_hold_max_hold_multiplier: float = 1.5
    psychology_hold_micro_min_best_points: float = 5.5
    psychology_hold_min_hold_before_micro_seconds: int = 150
    psychology_hold_micro_giveback_points: float = 4.0
    psychology_hold_trail_keep_ratio: float = 0.52

    # Chart alignment — CE/PE must match index candle direction
    chart_alignment_enabled: bool = True
    chart_min_trend_strength: float = 25.0
    chart_min_momentum_pct: float = 0.04
    chart_override_min_score: float = 75
    # Live 5m direction hard block — not skippable by high rank score (fixes scalp mis-entries)
    chart_live_direction_hard_block: bool = True
    # Aug6 78800 PE: PUT into BULLISH index filled via expiryExplosionBypass / local-base
    # chart bypass. Hard direction conflict must not be waived by any bypass.
    chart_counter_trend_bypass_block_enabled: bool = True
    chart_alignment_rank_bonus: float = 10.0
    # Gap-down leaves spotChart/breadth BEARISH and blanket-blocks CEs (Jul24 NIFTY
    # 23700 CE EXPLODING 98 off a ~110 local base). Local premium base alone lifts
    # session-direction + sibling side/bias blocks; Ichimoku is optional.
    local_base_overrides_session_chart_enabled: bool = True
    local_base_ichimoku_chart_bypass_enabled: bool = True  # legacy alias, still honored
    local_base_chart_bypass_require_ichimoku: bool = False
    local_base_ichimoku_require_cloud: bool = False
    local_base_ichimoku_max_adverse_mom5_pct: float = 0.12
    # Bullish-for-CALL / bearish-for-PUT: require the LIVE 5-min index momentum to be
    # aligned with the option side before the local-base bypass fires. Uses live momentum
    # (not the stale day chart), so a genuine bounce (index turning up) still lets a CALL
    # rip through, but a CALL drifting while the index falls > tolerance is rejected.
    # Symmetric for PUT. Tighter than the 0.12 hard cap above.
    local_base_require_aligned_live_momentum: bool = True
    local_base_aligned_momentum_max_adverse_pct: float = 0.05
    # Counter-breadth TURN (symmetric CE/PE): a top-tier ELITE/EXPLODING base rip on the
    # side OPPOSITE current breadth/chart is the reversal itself — the market is moving to
    # the other side (Aug13 SENSEX 77900 CE ripped off its base while breadth/chart were
    # still bearish). When the live 5m index momentum is CONFIRMED turning toward the option
    # side (5m > 15m by a margin AND 5m no worse than 10m — monotonic-ish improvement) on a
    # high-volume top-tier rip, widen the adverse-momentum cap so the turn is caught. A
    # steadily dumping / non-improving index, a low score, or thin volume is still rejected,
    # preserving the #261 counter-trend-fade protection. CALL mirrors PUT exactly.
    local_base_turn_bypass_enabled: bool = True
    local_base_turn_min_score: float = 62.0
    local_base_turn_min_vol_surge: float = 2.0
    local_base_turn_min_mom_shift_pct: float = 0.05
    local_base_turn_max_adverse_mom5_pct: float = 0.12
    # Local-base reversal prediction (CE + PE). Promotes a CALL or PUT leg only after a
    # real premium base, live index momentum turn toward that side, premium acceleration
    # and volume agree — plus optional ICT confirms (FVG / OTE / Judas / CHoCH).
    # Never bypasses risk, fake-trap, chase or execution-chart safety.
    bullish_local_base_prediction_enabled: bool = True
    local_base_reversal_prediction_enabled: bool = True  # alias master switch
    bullish_local_base_prediction_min_score: float = 62.0
    bullish_local_base_prediction_min_vol_surge: float = 2.0
    bullish_local_base_prediction_min_velocity_3s: float = 1.5
    bullish_local_base_prediction_min_velocity_9s: float = 0.2
    bullish_local_base_prediction_min_move_pct: float = 8.0
    bullish_local_base_prediction_max_move_pct: float = 40.0
    bullish_local_base_prediction_min_confidence: float = 70.0
    bullish_local_base_prediction_rank_max: float = 18.0
    # Pad-capture lane — low-score FTV at local base with volume awake (Aug27 SENSEX
    # 77300 PUT: score 33, v3=0 at trough, +338% MFE missed).
    bullish_local_base_pad_min_explosion_score: float = 8.0
    bullish_local_base_pad_max_move_pct: float = 45.0
    bullish_local_base_pad_min_confidence: float = 55.0
    bullish_local_base_trough_velocity_eps: float = 0.05
    bullish_local_base_pad_session_bypass_enabled: bool = True
    bullish_local_base_pad_must_take_min_move_pct: float = 8.0
    local_base_turn_pad_min_score: float = 20.0
    # Local-base pad capture band — slow coil → fast vertical lift (not generic
    # cheap options). Aug24 24200 PE: ₹18–23 coil, lift through ₹50+.
    local_base_pad_capture_min_premium_inr: float = 18.0
    local_base_pad_capture_max_premium_inr: float = 220.0
    # Fast-moving local-base capture — enter in the pad band when momentum turn +
    # volume awakening prove the rip is starting.
    fast_bullish_local_base_capture_enabled: bool = True
    fast_bullish_local_base_max_premium_inr: float = 220.0
    fast_bullish_local_base_min_move_pct: float = 1.0
    fast_bullish_local_base_max_move_pct: float = 45.0
    fast_bullish_local_base_min_velocity_3s: float = 0.8
    fast_bullish_local_base_soft_min_score: float = 45.0
    fast_bullish_local_base_soft_min_confidence: float = 60.0
    # Slow-grind coil in the pad band — catch the flat base before volume/velocity spike.
    # Aug24 24200 PE: 18–23 LTP for ~45min, then sudden lift at 11:15.
    slow_grind_sudden_lift_enabled: bool = True
    slow_grind_sudden_lift_max_premium_inr: float = 220.0
    slow_grind_sudden_lift_min_move_pct: float = 2.0
    slow_grind_sudden_lift_max_move_pct: float = 30.0
    # When volume awakens before the velocity spike, extend the pad ceiling so the
    # handoff at ~25–30% base-rel (Aug24 24200 PE lift) does not fall through.
    slow_grind_sudden_lift_handoff_move_bonus_pct: float = 8.0
    slow_grind_sudden_lift_min_velocity_3s: float = -0.8
    slow_grind_sudden_lift_max_velocity_3s: float = 1.5
    slow_grind_sudden_lift_min_coil_samples: int = 6
    slow_grind_sudden_lift_min_flat_quality: float = 50.0
    slow_grind_sudden_lift_min_impending_signals: int = 2
    # Armed-base at session trough — catch WATCH-tier coils before flat-quality confirms
    # (Aug25 NIFTY 24150 CE ₹33 armed base before slow-grind structure matures).
    slow_grind_armed_trough_enabled: bool = True
    slow_grind_armed_trough_max_off_low_pct: float = 2.0
    slow_grind_armed_trough_min_move_pct: float = 0.0
    slow_grind_armed_trough_max_move_pct: float = 20.0
    slow_grind_armed_trough_min_impending_signals: int = 1
    slow_grind_armed_trough_min_explosion_score: float = 5.0
    # Index slow-V at session trough — fire before option premium coil arms (~10:30 vs ~11:06).
    slow_grind_armed_trough_index_trough_enabled: bool = True
    # Wider than armed-trough 2% — catch slow grind off session low while index V forms.
    slow_grind_armed_trough_index_trough_max_off_low_pct: float = 15.0
    # BEARISH 5m chart may still block CALLs at the index trough; waive when 5m turns.
    index_trough_chart_bypass_enabled: bool = True
    index_trough_chart_bypass_min_mom5_pct: float = 0.008
    index_trough_chart_bypass_min_mom_shift_pct: float = 0.02
    index_trough_chart_bypass_max_adverse_mom15_pct: float = -0.35
    # Sep 1 afternoon: composite 5m stayed BULLISH (mom15/mom30 lagging the morning rally)
    # while live 5m rolled over at the session high — PUTs blocked as chart_live_bullish_no_puts.
    # When breadth agrees with the rollover, trust negative mom5 over lagging mom15/mom30.
    chart_breadth_mom5_rollover_enabled: bool = True
    chart_breadth_bearish_mom5_rollover_pct: float = 0.008
    chart_breadth_bullish_mom5_rollover_pct: float = 0.008
    # Mid-day consolidation base — armed coil off session low before afternoon breakout
    # (Aug25 NIFTY 24250 PE ₹70–80 base 12:15–12:45 before 1pm rip).
    slow_grind_consolidation_base_enabled: bool = True
    slow_grind_consolidation_base_min_off_low_pct: float = 3.0
    slow_grind_consolidation_base_max_off_low_pct: float = 30.0
    slow_grind_consolidation_base_min_move_pct: float = 2.0
    slow_grind_consolidation_base_max_move_pct: float = 22.0
    slow_grind_consolidation_base_max_peak_move_pct: float = 24.0
    slow_grind_consolidation_base_min_coil_samples: int = 6
    slow_grind_consolidation_base_min_flat_quality: float = 35.0
    slow_grind_consolidation_base_min_impending_signals: int = 2
    slow_grind_consolidation_base_min_explosion_score: float = 24.0
    # ITM SENSEX/NIFTY afternoon bases often sit above the ₹220 pad lane (Aug25
    # SENSEX CALL 77100 @ ₹397 base missed L1 before 53% vertical).
    slow_grind_consolidation_base_max_premium_inr: float = 800.0
    # Squeeze release at pad — Bollinger-in-Keltner compression → fresh release.
    squeeze_release_capture_enabled: bool = True
    squeeze_release_max_premium_inr: float = 220.0
    squeeze_release_min_move_pct: float = 2.0
    squeeze_release_max_move_pct: float = 30.0
    squeeze_release_max_velocity_3s: float = 1.5
    squeeze_release_min_bars_on: int = 3
    squeeze_release_ftv_enabled: bool = True
    squeeze_release_ftv_min_explosion_score: float = 12.0
    squeeze_release_ftv_max_capital_pct: float = 0.90
    squeeze_release_ftv_force_max_lots: bool = True
    # Index-led option lag — index thrusting, option premium still flat in pad.
    index_led_option_lag_capture_enabled: bool = True
    index_led_option_lag_max_premium_inr: float = 220.0
    index_led_option_lag_min_move_pct: float = 2.0
    index_led_option_lag_max_move_pct: float = 25.0
    index_led_option_lag_max_option_velocity_3s: float = 1.2
    index_led_option_lag_min_index_velocity_3s: float = 0.02
    index_led_option_lag_ftv_enabled: bool = True
    index_led_option_lag_ftv_min_explosion_score: float = 12.0
    index_led_option_lag_ftv_max_capital_pct: float = 0.90
    index_led_option_lag_ftv_force_max_lots: bool = True
    # Stealth CVD coil — flat price, CVD buying+acceleration before volume spike.
    stealth_cvd_coil_capture_enabled: bool = True
    stealth_cvd_coil_max_premium_inr: float = 220.0
    stealth_cvd_coil_min_move_pct: float = 2.0
    stealth_cvd_coil_max_move_pct: float = 25.0
    stealth_cvd_coil_min_velocity_3s: float = -0.5
    stealth_cvd_coil_max_velocity_3s: float = 1.0
    stealth_cvd_coil_max_volume_surge: float = 1.8
    stealth_cvd_coil_ftv_enabled: bool = True
    stealth_cvd_coil_ftv_min_explosion_score: float = 12.0
    stealth_cvd_coil_ftv_max_capital_pct: float = 0.90
    stealth_cvd_coil_ftv_force_max_lots: bool = True
    # Micro-pullback retest on armed base before lift resumes.
    micro_pullback_retest_capture_enabled: bool = True
    micro_pullback_retest_max_premium_inr: float = 220.0
    micro_pullback_retest_min_move_pct: float = 5.0
    micro_pullback_retest_max_move_pct: float = 25.0
    micro_pullback_retest_min_velocity_3s: float = -1.2
    micro_pullback_retest_max_velocity_3s: float = 0.5
    micro_pullback_retest_min_velocity_9s: float = -0.5
    micro_pullback_retest_ftv_enabled: bool = True
    micro_pullback_retest_ftv_min_explosion_score: float = 12.0
    micro_pullback_retest_ftv_max_capital_pct: float = 0.90
    micro_pullback_retest_ftv_force_max_lots: bool = True
    # Premium FVG at local base before vertical extension.
    premium_fvg_pad_capture_enabled: bool = True
    premium_fvg_pad_max_premium_inr: float = 220.0
    premium_fvg_pad_min_move_pct: float = 2.0
    premium_fvg_pad_max_move_pct: float = 28.0
    premium_fvg_pad_max_velocity_3s: float = 2.0
    premium_fvg_pad_ftv_enabled: bool = True
    premium_fvg_pad_ftv_min_explosion_score: float = 12.0
    premium_fvg_pad_ftv_max_capital_pct: float = 0.90
    premium_fvg_pad_ftv_force_max_lots: bool = True
    # Double-dip V-base — session low → bounce → retest low → second lift.
    double_dip_vbase_capture_enabled: bool = True
    double_dip_vbase_max_premium_inr: float = 220.0
    double_dip_vbase_min_move_pct: float = 2.0
    double_dip_vbase_max_move_pct: float = 20.0
    double_dip_vbase_min_first_bounce_pct: float = 8.0
    double_dip_vbase_max_retest_off_low_pct: float = 12.0
    double_dip_vbase_min_retrace_ratio: float = 0.55
    double_dip_vbase_min_velocity_3s: float = -0.8
    double_dip_vbase_max_velocity_3s: float = 1.5
    double_dip_vbase_ftv_enabled: bool = True
    double_dip_vbase_ftv_min_explosion_score: float = 12.0
    double_dip_vbase_ftv_max_capital_pct: float = 0.90
    double_dip_vbase_ftv_force_max_lots: bool = True
    # Unified early-pad floors — WATCH/BUILDING/FTV/V trough sleeves share these so
    # entries fire before composite score warms to ELITE/EXPLODING (Aug26 77600 CE @12.8).
    early_pad_min_explosion_score: float = 12.0
    early_pad_min_quality: float = 45.0
    first_lift_early_pad_min_score: float = 8.0
    first_lift_early_pad_min_rank: float = 38.0
    early_catch_pad_min_rank: float = 35.0
    first_lift_early_pad_min_quality: float = 45.0
    # Early radar pad — take FTV/V/ELITE/EXPLODING at session trough (e.g. ₹33→48).
    early_radar_pad_capture_enabled: bool = True
    early_radar_pad_max_off_low_pct: float = 15.0
    early_radar_pad_max_local_move_pct: float = 20.0
    early_radar_pad_min_explosion_score: float = 5.0
    # EXPLODING/ELITE at local base before armed_base_launch stamp (Aug27 PUT 77300).
    early_radar_pad_exploding_prelaunch_min_score: float = 18.0
    early_radar_pad_ftv_enabled: bool = True
    early_radar_pad_ftv_min_explosion_score: float = 5.0
    early_radar_pad_ftv_max_capital_pct: float = 0.90
    early_radar_pad_ftv_force_max_lots: bool = True
    # Live pad entry requires expansion — armed base alone is watch-only (Sep2 gap-day chop).
    early_radar_pad_confirm_entry_enabled: bool = True
    early_radar_pad_confirm_min_velocity_3s: float = 0.5
    early_radar_pad_confirm_min_velocity_9s: float = 0.25
    early_radar_pad_confirm_min_volume_surge: float = 1.0
    early_radar_pad_confirm_trough_off_low_max_pct: float = 3.0
    # Post-open impulse done — index consolidating; pad lanes need fresh lift (Sep2 09:30).
    post_impulse_consolidation_guard_enabled: bool = True
    post_impulse_consolidation_min_index_momentum15_pct: float = 0.12
    post_impulse_consolidation_max_index_momentum5_pct: float = 0.04
    post_impulse_consolidation_max_index_momentum10_pct: float = 0.05
    post_impulse_consolidation_min_velocity_3s: float = 0.8
    post_impulse_consolidation_min_velocity_9s: float = 0.5
    # WATCH-tier local-base pad — enter at session trough with low scores before ELITE/EXPLODING.
    # Aug26 SENSEX 77600 CE: WATCH ~12.8 at ₹240 pad was DETECTED but not SELECTED until
    # score hit 100 and explosion_near_miss fired after the rip to ₹306.
    watch_local_base_pad_entry_enabled: bool = True
    watch_local_base_pad_max_off_low_pct: float = 18.0
    watch_local_base_pad_max_local_move_pct: float = 15.0
    watch_local_base_pad_max_explosion_score: float = 50.0
    watch_local_base_pad_min_velocity_3s: float = 0.05
    watch_local_base_pad_min_velocity_9s: float = 0.03
    # Cold-trough pad — WATCH/BUILDING at session low with v3=0 and armed/coil signals
    # (Aug28 NIFTY 24150 CE 15:03–15:05 at ₹104 pad before 3pm rip; v3=0 blocked watch pad).
    cold_trough_pad_entry_enabled: bool = True
    cold_trough_pad_max_off_low_pct: float = 5.0
    cold_trough_pad_max_local_move_pct: float = 8.0
    cold_trough_pad_max_explosion_score: float = 35.0
    # Anti-chase — block ELITE/EXPLODING tier promotion when baseRel > floor without pad stamp
    # (Aug28 NIFTY 24250 CE 10:17 ELITE @ 8.4% baseRel after micro-rip, not cold trough).
    tier_promotion_pad_chase_block_enabled: bool = True
    tier_promotion_pad_chase_min_base_rel_pct: float = 8.0
    # Best-only selector — one top-ranked explosion per radar cycle; rank-1 at selection.
    selector_best_only_enabled: bool = True
    # Grade-A BUILDING armed_base_option_led_ready on live selector — enter at local
    # base before ELITE/EXPLODING promote (Aug28 NIFTY PUT 24200/24100 ~1h late).
    # Archive week in-window false-start rate ~7.5% (3/40); win rate ~75%.
    building_armed_base_grade_a_live_enabled: bool = True
    building_armed_base_grade_a_min_grade: str = "B"
    building_armed_base_grade_a_max_base_rel_pct: float = 0.0
    building_armed_base_grade_a_use_local_base_window: bool = True
    building_armed_base_grade_a_ftv_enabled: bool = True
    building_armed_base_grade_a_ftv_max_capital_pct: float = 0.90
    building_armed_base_grade_a_ftv_force_max_lots: bool = True
    # WORST/BREAKOUT_ONLY days still take grade-B armed base at the local pad
    # (Aug28 NIFTY PUT 24100/24200 @ 10:45–11:00).
    building_armed_base_worst_day_waive_enabled: bool = True
    building_armed_base_worst_day_waive_min_base_rel_pct: float = 10.0
    building_armed_base_worst_day_waive_max_base_rel_pct: float = 25.0
    building_armed_base_worst_day_waive_min_volume_surge: float = 2.0
    # BUILDING coil pad at 10–25% local base — EOD hindsight entry window live
    # (Aug28 NIFTY PUT 24050 @ 11:12: BUILDING baseRel 20.7%, v3=0, +₹78k hindsight).
    building_coil_pad_entry_enabled: bool = True
    building_coil_pad_min_local_move_pct: float = 10.0
    building_coil_pad_max_local_move_pct: float = 25.0
    building_coil_pad_max_explosion_score: float = 65.0
    building_coil_pad_ftv_enabled: bool = True
    building_coil_pad_ftv_max_capital_pct: float = 0.90
    building_coil_pad_ftv_force_max_lots: bool = True
    building_coil_pad_max_otm_steps: int = 4
    building_coil_pad_min_grade: str = "B"
    building_coil_pad_floor_grade_enabled: bool = True
    # Require lift confirmation before coil-pad live entry (armed coil is watch-only).
    building_coil_pad_confirm_entry_enabled: bool = True
    building_coil_pad_confirm_min_velocity_3s: float = 0.5
    building_coil_pad_confirm_min_velocity_9s: float = 0.25
    building_coil_pad_confirm_min_volume_surge: float = 1.0
    building_coil_pad_confirm_allow_flat_vertical: bool = True
    # Quiet armed coil at pad — volume awake before v3 lifts (Aug28 PUT 24050 @ 11:12).
    building_coil_pad_confirm_armed_volume_ok: bool = True
    building_coil_pad_worst_day_waive_enabled: bool = True
    # WATCH/BUILDING armed base at 5–18% local pad before vertical lift (Aug28 10:30 PUTs).
    building_armed_prelaunch_pad_enabled: bool = True
    building_armed_prelaunch_min_base_rel_pct: float = 5.0
    building_armed_prelaunch_max_base_rel_pct: float = 18.0
    building_armed_prelaunch_min_explosion_score: float = 5.0
    building_armed_prelaunch_max_explosion_score: float = 55.0
    building_armed_prelaunch_min_volume_surge: float = 1.0
    building_armed_prelaunch_min_grade: str = "C"
    # Momentum-rally window: keep armed-base coils on radar before vertical lift.
    momentum_rally_armed_coil_radar_enabled: bool = True
    momentum_rally_armed_coil_min_premium: float = 18.0
    momentum_rally_armed_coil_max_premium: float = 45.0
    momentum_rally_armed_coil_min_samples: int = 4
    momentum_rally_armed_coil_min_score: float = 18.0
    eod_replay_early_pad_rank_penalty: float = 12.0
    eod_replay_counter_side_rank_penalty: float = 35.0
    # Prefer deeper ITM expansion strikes over ATM when coil pad is active
    # (Aug28 24050 ITM over 24200/24100 ATM on the same lift).
    expansion_strike_rank_bonus_enabled: bool = True
    expansion_strike_rank_bonus: float = 15.0
    # Pad-lane turnaround chart bypass — premium-led V-rip / slow-grind / FTV lifts off
    # session low while the 5m index chart is still counter-trend (Aug25 NIFTY 24150 CE
    # ₹20→90 V-reversal blocked by chart_live_bearish_no_calls). Wider adverse-momentum
    # cap than local_base_structure_active; still bounded so extended chases fail.
    pad_lane_chart_bypass_enabled: bool = True
    pad_lane_chart_bypass_min_velocity_3s: float = 0.5
    pad_lane_chart_bypass_volume_awaken_min_velocity_3s: float = 0.2
    pad_lane_chart_bypass_max_off_low_pct: float = 30.0
    pad_lane_chart_bypass_max_peak_move_pct: float = 38.0
    pad_lane_chart_bypass_max_adverse_index_mom5_pct: float = 0.25
    pad_lane_chart_bypass_min_premium_velocity_9s: float = -0.3
    # ELITE/EXPLODING flat→vertical off local base may bypass bearish chart even after
    # the v_rip_session_low stamp clears (Aug25 NIFTY 24200 CE chart_not_aligned at ELITE).
    pad_lane_elite_ftv_chart_bypass_enabled: bool = True
    pad_lane_elite_ftv_chart_bypass_min_score: float = 12.0
    pad_lane_elite_ftv_chart_bypass_max_peak_move_pct: float = 45.0
    # first_lift_local_base at the pad may bypass counter-trend chart when session peak
    # is high but LTP is still inside the 2–25% local-base window (Aug26 SENSEX PUT 77800).
    pad_lane_first_lift_local_base_chart_bypass_enabled: bool = True
    # Pad-lane FTV may waive cold-velocity / FAILED_LAUNCH timing blocks at execution.
    pad_lane_ftv_waives_timing_block_enabled: bool = True
    # Floor rank grade to A for stamped pad-lane FTV (fixes replay top_moment_grade_reject).
    pad_lane_grade_floor_enabled: bool = True
    # Pad-lane FTV may authorize on rank 2+ sleeves — the moment is contract-specific
    # (Aug25 CALL 24150 blocked by early_radar_pad_ftv_requires_allocation_rank_1).
    pad_lane_ftv_waives_allocation_rank_one: bool = True
    # Boost pad-lane local-base legs in selector so they win rank over stale leaders.
    pad_lane_selector_rank_bonus: float = 18.0
    # Pad-lane base retest may fill through shallow premium fade at execution.
    pad_lane_premium_fade_fill_enabled: bool = True
    pad_lane_premium_fade_fill_max_drawdown_pct: float = -1.2
    # Pad-lane local-base FTV on EXPIRY WORST may waive quality/score floors when
    # stamped readiness proves the lift (Aug25 24250 CE afternoon block).
    pad_lane_expiry_worst_waive_enabled: bool = True
    # Stamped pad-lane readiness (v_rip_session_low_ready, slow-grind pad, etc.) may
    # waive ICT first-lift quality / BUILDING→ELITE lag near-miss blockers so the
    # selector admits the leg at the local base before flatVerticalQuality warms.
    pad_lane_early_near_miss_waive_enabled: bool = True
    # Link stamped pad-lane / BUILDING FTV readiness directly to trade execution.
    # Aug26 SENSEX 77700 PE: EARLY at ~₹120 on radar but chart/timing/rank blocked
    # until the vertical reached ~₹200 — must-take path only covered ELITE/EXPLODING.
    ftv_direct_trade_enabled: bool = True
    ftv_direct_trade_max_off_low_pct: float = 35.0
    ftv_direct_trade_max_local_move_pct: float = 45.0
    ftv_direct_trade_max_peak_move_pct: float = 50.0
    ftv_direct_trade_min_off_low_pct: float = 2.0
    ftv_direct_trade_selector_rank_bonus: float = 55.0
    ftv_direct_trade_require_atm_itm: bool = True
    # ICT confirm stack for local-base reversals (additive quality, not hard gates).
    local_base_reversal_ict_bonus_max: float = 18.0
    local_base_reversal_kill_zone_bonus_enabled: bool = True
    local_base_reversal_require_ict_confirm: bool = False
    local_base_chart_bypass_min_score: float = 38.0
    # Radar-lag side-bias fallback (no ICT flags yet) — keep above entry floor so
    # bare ELITE+15% cannot lift counter-breadth locks.
    local_base_chart_bypass_radar_min_move_pct: float = 28.0
    # Also lifts explosion_call_vs_bearish_breadth, market_opposes_side,
    # directional_call_needs_confirmation_*, bad_day/worst_day alignment.
    local_base_overrides_bearish_breadth: bool = True
    spot_chart_timeframe_minutes: int = 5
    spot_chart_1m_bars: int = 300  # 1m history for 5m resample + RSI/MACD warmup
    # Historical time-to-FTV advisory. V3 index candles train a time-of-day
    # breakout prior; live premium/orderflow must still confirm every entry.
    ftv_probability_enabled: bool = True
    ftv_probability_history_days: int = 28
    ftv_probability_profile_cache_seconds: int = 1800
    ftv_probability_base_window_minutes: int = 5
    ftv_probability_time_bucket_minutes: int = 15
    ftv_probability_flat_max_range_pct: float = 0.22
    ftv_probability_vertical_move_pct: float = 0.18
    ftv_probability_min_training_samples: int = 100
    ftv_premium_calibration_enabled: bool = True
    ftv_premium_calibration_history_days: int = 30
    ftv_premium_calibration_sample_seconds: int = 60
    ftv_premium_vertical_move_pct: float = 20.0
    ftv_premium_min_training_samples: int = 200
    ftv_probability_drift_warn_pct_points: float = 8.0
    ftv_probability_drift_critical_pct_points: float = 15.0
    # Advisory soft alert when FTV live timing, local base, chart side, and
    # tradeable radar all align. Never wired to auto_trader entry.
    ftv_focus_alerts_enabled: bool = True
    ftv_focus_min_confidence: str = "MEDIUM"
    ftv_focus_min_peak_probability_pct: float = 28.0
    ftv_focus_cooldown_seconds: int = 300
    # Sep01: index base often expands before option coil arms — accept option local-base
    # when index range is still within this ceiling (advisory only).
    ftv_focus_option_local_base_enabled: bool = True
    ftv_focus_option_local_base_max_index_range_pct: float = 0.45
    # Mirror index-trough / session-peak chart bypass (#502) for focus alerts.
    ftv_focus_index_momentum_chart_bypass_enabled: bool = True
    # Include BUILDING/WATCH radar at local base before tradeable promotion.
    ftv_focus_allow_building_radar: bool = True
    ftv_focus_min_radar_score: float = 35.0
    ftv_focus_low_confidence_min_radar_score: float = 55.0
    # Bootstrap premium calibration from finalized radar archives when live tape purged.
    ftv_premium_calibration_use_archived_tape: bool = True
    # Operator-supplied verified events only. JSON array fields:
    # date, time, title, impact, symbols, sideBias, durationMinutes.
    ftv_scheduled_events_json: str = "[]"
    ftv_scheduled_event_lead_minutes: int = 30
    # Use true resampled-5m closes for the spot-chart RSI/MACD as soon as there are this
    # many 5m bars; only fall back to 1m when the session is genuinely too thin. The old
    # hardcoded 35 kept the "5m" chart on 1m data until ~12:10 IST every day, so the
    # morning spot RSI/MACD (which drive the direction vote + CE/PE alignment) diverged
    # from the true 5m / MTF panel (e.g. spot RSI 54 vs MTF 5m RSI 24). 20 bars is enough
    # for a meaningful RSI(14) and keeps the chart 5m-consistent through the morning.
    spot_chart_min_5m_indicator_bars: int = 20
    # A CONFIRMED live 5m reversal (EMA flip + both momenta agreeing + MACD not opposing)
    # is not a lone oversold flicker — keep the live direction instead of force-flipping it
    # back to a stale MTF consensus. Aug13 SENSEX: the index V-recovered (emaBias BULLISH,
    # mom5 +0.14 / mom15 +0.25) with ELITE volume-awakened CALLs, but the MTF was stuck
    # oversold-bearish (RSI 23–30) and reconcile forced the chart BEARISH → chart_live_bearish
    # _no_calls hard-blocked every CALL. A shallow bounce (no EMA flip / weak momentum) is
    # still force-flipped, preserving the dead-cat-bounce protection. Symmetric CE/PE.
    chart_reconcile_confirmed_reversal_keeps_live: bool = True
    chart_reconcile_confirmed_reversal_min_mom15_pct: float = 0.06
    # Ichimoku / micro-bounce chart flips must not override directional breadth
    # (Aug26: bearish breadth + bearish broker chart but spotChart showed BULLISH →
    # chart_live_bullish_no_puts blocked every PUT).
    chart_reconcile_respects_breadth_enabled: bool = True
    # Advanced indicators (squeeze / ADX / Supertrend / VWAP) computed on the index chart.
    # The squeeze (Bollinger-in-Keltner compression -> release) is the canonical flat-base
    # -> vertical-explosion signal: a fresh release with momentum toward the option side is
    # the explosion starting AT the base. Additive rank bonus only (never a gate/loosener).
    advanced_indicators_enabled: bool = True
    squeeze_rank_bonus_enabled: bool = True
    squeeze_rank_bonus: float = 10.0
    squeeze_fresh_window_bars: int = 3
    # Cumulative Volume Delta (trade authenticity) from WS ticks: net buying in the option
    # we're buying = real demand behind the rip. Additive rank bonus only (never a gate).
    cvd_confirm_enabled: bool = True
    cvd_window_seconds: float = 90.0
    cvd_min_recent_qty: float = 0.0
    cvd_rank_bonus: float = 5.0
    # Change in signed-volume rate across two short slices. Additive only: sparse
    # or stable flow receives no bonus and can never bypass an entry safeguard.
    cvd_acceleration_enabled: bool = True
    cvd_acceleration_slice_seconds: float = 15.0
    cvd_acceleration_min_samples_per_slice: int = 2
    cvd_acceleration_min_delta_qty_per_second: float = 0.25
    cvd_acceleration_rank_bonus: float = 4.0
    # Flat->vertical setup quality (0-100) — grade the coil (tightness/duration/launch/heat/
    # volume) and give a proportional rank bonus so the cleanest base rips jump the queue.
    flat_vertical_quality_rank_enabled: bool = True
    flat_vertical_quality_rank_max: float = 12.0
    # ADX regime + VWAP reclaim as additive selection-quality nudges (never a gate):
    # de-rank CHOP, boost a trend aligned with the side, and reward a fresh VWAP reclaim.
    adx_rank_enabled: bool = True
    adx_trend_rank_bonus: float = 6.0
    adx_chop_rank_penalty: float = 8.0
    vwap_reclaim_rank_bonus_enabled: bool = True
    vwap_reclaim_rank_bonus: float = 6.0
    # Squeeze-fired ELITE/EXPLODING at a confirmed local base may enter closer to the base
    # than the normal 15% floor — a Bollinger/Keltner release off the base is a confirmed
    # coil break, not noise. Catch it AT the base. Only lowers the floor when the squeeze
    # confirms; everything else keeps the 15% floor so chop stays blocked.
    explosion_squeeze_early_base_enabled: bool = True
    explosion_squeeze_early_base_min_move_pct: float = 8.0
    # India VIX regime (day-type context). Inert until a real India VIX value is wired in
    # (Upstox NSE_INDEX|India VIX); classification only, no hard gate by default.
    india_vix_enabled: bool = True
    india_vix_calm_max: float = 11.0
    india_vix_normal_max: float = 14.0
    india_vix_elevated_max: float = 20.0
    india_vix_rising_pct: float = 0.03
    india_vix_spike_pct: float = 0.10
    # VIX-regime day-type sizing. Default OFF (observe-only): the regime + would-be
    # multiplier are stamped on every trade for validation, but lots are unchanged until
    # this is flipped on after confirming the live VIX trend. Expansion = normal size;
    # calm/contraction (theta chop) and VIX spikes (event risk) shrink lots.
    vix_regime_sizing_enabled: bool = False
    vix_size_mult_expansion: float = 1.0
    vix_size_mult_size_down: float = 0.5
    vix_size_mult_stand_down: float = 0.6

    # Execution-time chart — fresh Upstox fetch right before order
    execution_chart_gate_enabled: bool = True
    execution_chart_force_upstox_refresh: bool = True
    execution_chart_premium_check_enabled: bool = True
    execution_chart_min_premium_momentum_pct: float = -0.15
    execution_chart_candle_count: int = 60
    # Confirmed near-base FTV first-lifts may fill THROUGH a shallow premium dip — that dip is
    # the base retest right before the vertical, not a collapse. Without this the execution
    # premium-fading gate blocked every confirmed FTV first-lift (they always ticked back a
    # hair at the base). Bounded: only ELITE/EXPLODING first-lifts, and only while the dip is
    # shallower than the floor below; a deeper collapse still blocks. This is what lets the
    # system take these AT the local base instead of chasing them after they lift.
    ftv_premium_fade_fill_enabled: bool = True
    ftv_premium_fade_fill_max_drawdown_pct: float = -0.6

    # Multi-timeframe pre-test (1m/5m/15m/1h/4h) before execution
    execution_mtf_enabled: bool = True
    execution_mtf_use_v3_native: bool = True
    execution_mtf_1m_bars: int = 300
    execution_mtf_min_align: int = 3
    execution_mtf_block_htf_conflict: bool = True
    recent_win_window_seconds: int = 900
    recent_win_rank_bonus: float = 0.0
    calibration_block_min_losses: int = 5

    # Entries from 9:20 IST — skip 9:15 open auction; open caution until 9:45
    entry_earliest_hour: int = 9
    entry_earliest_minute: int = 20
    open_caution_until_hour: int = 9
    open_caution_until_minute: int = 45
    open_caution_min_explosion_score: int = 45
    open_caution_score_bonus: int = 0
    open_caution_min_rank_score: float = 55.0
    primary_window_start_hour: int = 10
    primary_window_start_minute: int = 0

    # Chop-day guardrails (Jun 25 playbook for RANGE_BOUND / NEUTRAL days)
    chop_day_guards_enabled: bool = True
    neutral_breadth_min_score: float = 60.0
    neutral_breadth_explosion_min_score: float = 55.0
    sensex_rank_bonus: float = 10.0
    nifty_rank_penalty_chop: float = 5.0
    # Daily risk budget = 10% of the ~200k sizing capital. This is a CEILING that halts
    # new entries, not a target — selectivity + per-trade caps keep us far below it.
    daily_loss_stop_inr: float = 20_000.0
    daily_max_trades_chop: int = 20
    daily_max_trades_pre10_chop: int = 5
    pre10_chop_min_rank_score: float = 60.0
    # Pause after 2 losses — Jul20 burned 6 before the old 3-loss pause helped.
    loss_streak_pause_count: int = 2
    loss_streak_pause_seconds: int = 1200
    session_large_loss_pause_inr: float = 8_000.0
    session_large_loss_pause_seconds: int = 900
    # Jul23: loss_streak_pause blanked 13:57–14:18 while SENSEX 76400 PE went ELITE.
    # Lift pause only for high-confidence ELITE / top explosive (not large_loss_pause).
    loss_streak_elite_bypass_enabled: bool = True
    loss_streak_elite_bypass_min_score: float = 90.0
    loss_streak_elite_bypass_min_chart_confidence: float = 56.9
    loss_streak_elite_bypass_tiers_csv: str = "ELITE,EXPLODING"
    loss_streak_elite_bypass_min_move_pct: float = 28.0
    loss_streak_elite_bypass_max_move_pct: float = 55.0
    chop_lots_high: int = 40
    chop_lots_mid: int = 20
    chop_lots_min_rank: float = 48.0
    chop_lots_high_min_rank: float = 55.0
    momentum_bypass_velocity_pct: float = 2.5
    momentum_bypass_volume_surge: float = 1.4
    momentum_bypass_explosion_score: float = 48.0
    momentum_rally_start_hour: int = 10
    momentum_rally_start_minute: int = 0
    momentum_rally_end_hour: int = 15
    momentum_rally_end_minute: int = 30
    morning_premium_capture_enabled: bool = True
    morning_capture_start_hour: int = 9
    morning_capture_start_minute: int = 15
    morning_capture_end_hour: int = 11
    morning_capture_end_minute: int = 45
    morning_capture_min_rank_score: float = 48.0
    morning_capture_building_min_score: float = 38.0
    morning_capture_min_velocity_3s: float = 2.0
    morning_capture_min_velocity_9s: float = 2.8
    morning_capture_building_min_velocity_3s: float = 2.0
    morning_capture_min_vol_surge: float = 1.3
    morning_capture_skip_chart_on_extreme_velocity: bool = True
    morning_capture_extreme_velocity_3s: float = 3.0
    morning_capture_extreme_velocity_9s: float = 4.0
    premium_led_counter_breadth_enabled: bool = True
    premium_led_min_velocity_3s: float = 2.8
    premium_led_min_velocity_9s: float = 3.5
    premium_led_min_explosion_score: float = 42.0
    premium_led_counter_breadth_min_score: float = 90.0
    premium_led_elite_counter_min_score: float = 90.0
    premium_led_explosion_bypass_enabled: bool = True
    # Explosion-only entries from 9:15 — catch open premium rips before 9:20 general window
    explosion_open_entry_enabled: bool = True
    explosion_entry_earliest_hour: int = 9
    explosion_entry_earliest_minute: int = 15
    # Open premium explosion — NIFTY PE 60→160 style gap rips at 9:15
    open_premium_explosion_enabled: bool = True
    open_premium_min_move_pct: float = 25.0
    open_premium_chart_bypass_move_pct: float = 20.0
    open_premium_bypass_min_score: float = 35.0
    open_premium_relax_velocity_3s: float = 1.8
    open_premium_relax_velocity_9s: float = 2.5
    explosion_open_scan_interval_ms: int = 600

    # Afternoon premium capture — 11:45–13:45 consolidation breakouts (e.g. NIFTY 24250 PE 1pm rip)
    afternoon_premium_capture_enabled: bool = True
    afternoon_capture_min_rank_score: float = 46.0
    afternoon_capture_building_min_score: float = 35.0
    afternoon_capture_min_velocity_3s: float = 1.2
    afternoon_capture_min_velocity_9s: float = 1.8
    afternoon_capture_building_min_velocity_3s: float = 1.0
    afternoon_capture_min_vol_surge: float = 1.4
    afternoon_capture_consolidation_vol_surge: float = 1.5
    afternoon_capture_consolidation_velocity_9s: float = 1.2
    afternoon_capture_skip_chart_on_volume: bool = True
    afternoon_capture_chart_bypass_vol_surge: float = 1.5
    afternoon_capture_chart_bypass_velocity_9s: float = 1.2
    afternoon_capture_bearish_min_score: float = 42.0
    afternoon_capture_dominant_velocity_min: float = 1.6
    afternoon_capture_dominant_velocity_ratio: float = 1.4
    afternoon_capture_exit_target_points: float = 18.0
    afternoon_capture_exit_stop_points: float = 4.0
    afternoon_capture_exit_trail_arm_points: float = 6.0
    afternoon_capture_exit_max_hold_seconds: int = 480
    afternoon_capture_exit_trail_keep_ratio: float = 0.55
    # Book when peak profit halves (peak ₹121 → exit ~₹111 on a ₹100 entry).
    afternoon_capture_peak_halve_lock_enabled: bool = True
    afternoon_capture_peak_halve_min_best_points: float = 10.0
    afternoon_capture_peak_halve_giveback_ratio: float = 0.50
    afternoon_capture_peak_halve_min_remain_points: float = 1.0
    # Aug28 SENSEX 77300/77200 — halve-lock fired ~16s after entry on a +12pt spike
    # while projectedMaxTp was 800+. Stage-ladder runners need time to expand.
    afternoon_capture_peak_halve_min_hold_seconds: int = 120
    afternoon_capture_peak_halve_skip_stage_ladder_min_projected_tp: float = 80.0
    # Do not tighten afternoon trail arm onto stage-ladder trades (6pt arm clips rips).
    afternoon_capture_skip_exit_tighten_on_stage_ladder: bool = True
    # Stage-ladder / peak-keep exits need a minimum hold — avoid 15s scratch on noise.
    explosion_stage_trail_min_hold_seconds: float = 90.0

    # All-day explosive capture — 9:20–15:30 session rips (e.g. NIFTY 23850 PE 14:00 +1360%)
    all_day_explosion_capture_enabled: bool = True
    all_day_explosion_start_hour: int = 9
    all_day_explosion_start_minute: int = 20
    all_day_explosion_end_hour: int = 15
    all_day_explosion_end_minute: int = 30
    all_day_explosion_min_score: float = 38.0
    all_day_explosion_session_move_min_pct: float = 40.0
    all_day_explosion_extreme_move_min_pct: float = 80.0
    # ELITE +100% / 150%+ rips — ALL-IN bypass (AI report → trade).
    # NOTE: these move floors sit ABOVE the extended-chase ceiling
    # (extreme_all_in_bypass_max_move_pct = 55%), so the ALL-IN gate-skip in
    # is_extreme_explosion_all_in_bypass is intentionally inert — a +100% move is a
    # late chase, not an entry. Genuine early rips are captured by high-conviction
    # sizing + the expiry elite-top bypass. elite_move_min is still used by
    # adaptive_exits (mega-move exit behavior), so it is kept, not removed.
    extreme_explosion_all_in_enabled: bool = True
    extreme_explosion_elite_move_min_pct: float = 100.0
    extreme_explosion_all_in_move_min_pct: float = 150.0
    extreme_explosion_all_in_min_score: float = 35.0
    extreme_all_in_max_otm_steps: int = 3
    extreme_explosion_hold_min_best_points: float = 8.0
    expiry_evening_all_in_explosion_bypass: bool = True
    all_day_explosion_building_min_velocity_3s: float = 2.0
    all_day_explosion_min_velocity_9s: float = 2.5
    all_day_explosion_chart_bypass_move_pct: float = 50.0
    all_day_explosion_dominant_min_score: float = 40.0
    # Peak-move bypass — faded vertical rips (velocity cooled, session peak still huge)
    peak_move_explosion_bypass_enabled: bool = True
    peak_move_explosion_min_pct: float = 35.0
    peak_move_explosion_min_tier: str = "ELITE"
    peak_move_explosion_score_floor: float = 38.0
    peak_move_explosion_score_boost_per_pct: float = 0.12
    # Session-open baseline — use intraday low when first tick arrived mid-rip
    session_open_use_intraday_low: bool = True
    session_open_low_backfill_pct: float = 5.0
    # Ignore illiquid micro-ticks as open/low baseline (Jul30 fake +8873% from ~₹0.28).
    # Real V-bottoms print ≥ this; junk prints do not.
    session_move_min_baseline_premium: float = 5.0
    # Moves above this without a real local/off-low base are treated as untrustworthy
    # mega-rip artifacts (radar noise), not elite moments.
    session_move_max_credible_pct: float = 500.0
    # Open-gap ITM CE/PE — seed baseline from option prev-close so gap rips
    # (Jul29 SENSEX 77500 CE 90→270, NIFTY 24200 CE 75→150) register as ELITE,
    # not as a flat ~+8% from the first mid-spike LTP sample.
    open_gap_prev_close_baseline_enabled: bool = True
    open_gap_baseline_min_gap_pct: float = 15.0
    # Seed session low/peak from option-chain day OHLC — catches V-bottoms missed
    # between sparse LTP polls (Aug12 SENSEX 77800 PE ~120 trough / ~238 peak).
    session_day_ohlc_extremes_enabled: bool = True
    session_day_ohlc_max_dev_mult: float = 8.0
    # Expiry trough first-tick scan — detect V-lift off chain day-low before velocity
    # history builds (Aug26 SENSEX 77800 PE: ₹95 trough, lift to ₹100+ at 10:00 but
    # radar waited until 10:55 ELITE @ ₹153 because open_move floor was 25%).
    expiry_trough_scan_enabled: bool = True
    expiry_trough_first_tick_min_off_low_pct: float = 3.0
    expiry_trough_first_tick_max_off_low_pct: float = 18.0
    expiry_trough_first_tick_min_score_boost: float = 10.0
    # Breadth-aligned ELITE/EXPLODING open-gap: bypass stale 5m MTF oppose.
    open_gap_elite_mtf_bypass_enabled: bool = True
    open_gap_elite_mtf_min_move_pct: float = 40.0
    # Pre-10 chop: never block ELITE; allow EXPLODING open-gaps ≥ this move.
    open_gap_chop_elite_bypass_enabled: bool = True
    # Near-expiry (today/tomorrow): allow breadth-aligned ELITE/EXPLODING on the
    # expiry symbol itself — don't force alternate-index routing.
    open_gap_near_expiry_symbol_allow_enabled: bool = True
    # Velocity-at-peak scoring — retain spike velocity after fade
    velocity_peak_score_boost_enabled: bool = True
    velocity_peak_min_3s: float = 2.5
    velocity_peak_score_floor: float = 42.0
    velocity_peak_decay_seconds: int = 180
    velocity_peak_score_blend: float = 0.55
    # Vertical rip bypass — catch premium-led explosions vs stale chart/breadth/MTF
    vertical_rip_bypass_enabled: bool = True
    vertical_rip_bypass_min_peak_pct: float = 30.0
    vertical_rip_bypass_min_tier: str = "EXPLODING"
    vertical_rip_bypass_min_score: float = 38.0
    vertical_rip_bypass_min_peak_velocity_3s: float = 2.0
    vertical_rip_bypass_min_volume_surge: float = 3.0
    vertical_rip_hard_breadth_bypass_enabled: bool = True
    vertical_rip_mtf_bypass_enabled: bool = True
    # Volume-spike baseline — flat-then-vertical rips under-report peak move
    volume_spike_baseline_enabled: bool = True
    volume_spike_baseline_min_surge: float = 3.5
    spike_velocity_baseline_min_pct: float = 12.0
    # Cheap PE/CE bases (SENSEX ~12, NIFTY ~25–40) must be tradeable at first break.
    # Keep cheap-rip floor at the main band min so ≥₹18 always holds.
    explosion_cheap_rip_min_premium_inr: float = 18.0
    explosion_cheap_rip_min_peak_pct: float = 25.0

    runner_trail_keep_ratio: float = 0.38
    runner_micro_giveback_points: float = 4.0
    runner_min_best_points: float = 5.0

    # Option premium (LTP) band for entries and scanners
    min_option_premium_inr: float = 18.0
    max_option_premium_inr: float = 300.0
    # Raised so mid-rip ATM/ITM (180→450+) stays on radar for max-TP capture.
    explosion_max_premium_inr: float = 650.0
    # ICT flat→vertical ATM/ITM can use a higher ceiling while still in the pad.
    explosion_ict_max_premium_inr: float = 800.0

    # Jun 25 profile — hold winners longer for 2.5+ profit factor
    enhanced_micro_target_points: float = 4.0
    enhanced_velocity_threshold: float = 1.2
    enhanced_tqs_entry: int = 50
    runner_alignment_override_score: int = 82
    rapid_scalp_mode_enabled: bool = False
    quick_sideways_enabled: bool = False
    quick_sideways_min_rank_score: float = 58.0
    quick_sideways_min_velocity_pct: float = 0.5
    quick_sideways_chop_min_velocity_pct: float = 0.22
    quick_sideways_chop_pick_momentum_pct: float = 0.02
    quick_sideways_scan_watchlist: bool = True
    quick_sideways_strike_scan_radius: int = 250
    quick_sideways_allow_bearish_chop: bool = True
    quick_sideways_min_tqs: int = 35
    quick_sideways_target_points: float = 3.0
    quick_sideways_stop_points: float = 2.0
    quick_sideways_micro_target_points: float = 2.0
    quick_sideways_micro_giveback_points: float = 1.5
    quick_sideways_max_hold_seconds: int = 120
    quick_sideways_no_progress_seconds: int = 75
    quick_sideways_min_seconds_between_entries: int = 120
    quick_sideways_stop_adaptive_enabled: bool = True
    quick_sideways_stop_premium_lt_60: float = 2.0
    quick_sideways_stop_premium_60_90: float = 2.5
    quick_sideways_stop_premium_90_130: float = 3.0
    quick_sideways_stop_premium_gt_130: float = 3.5
    quick_sideways_min_stop_hold_seconds: int = 30
    quick_sideways_instrument_cooldown_seconds: int = 300
    quick_sideways_high_premium_threshold_inr: float = 90.0
    quick_sideways_high_premium_lot_cap: int = 10
    quick_sideways_preferred_premium_min: float = 30.0
    quick_sideways_preferred_premium_max: float = 80.0
    quick_sideways_high_premium_penalty_start: float = 90.0
    quick_sideways_chop_early_lock_points: float = 1.5
    quick_sideways_chop_early_giveback_points: float = 0.75
    sure_shot_mode_enabled: bool = False
    sure_shot_min_symbol_tqs: int = 40
    sure_shot_min_rank_score: float = 48.0
    sure_shot_scalp_min_score: int = 55
    # Jul17 logic: 0 = capital-derived max (14–20 lot ITM runners). First-green lot
    # cap (size_until_first_green) still guards never-green oversize.
    scalp_max_lots: int = 0
    scalp_target_points: float = 12.0  # unused — session targets in simple_profit
    # Jul17 logic: best-only OFF — Jul17 winners used enhanced TQS/velocity gates only.
    # (Jul27 clamps remain available via env if churn returns.)
    scalp_best_only_enabled: bool = False
    scalp_best_min_rank_score: float = 84.0
    scalp_best_min_chart_confidence: float = 68.0
    scalp_best_require_breadth_aligned: bool = True
    scalp_best_require_chart_aligned: bool = True
    scalp_best_atm_itm_only: bool = True
    scalp_best_min_velocity_pct: float = 1.0
    # Jul17: do not defer scalp when an explosion is also on radar — selector picks best.
    scalp_best_defer_to_explosion: bool = False
    scalp_local_base_enabled: bool = True
    scalp_local_base_min_rank_score: float = 80.0
    scalp_local_base_min_chart_confidence: float = 62.0
    scalp_local_base_min_velocity_pct: float = 0.8
    scalp_local_base_max_otm_steps: int = 3
    bullish_hold_enabled: bool = True
    bullish_hold_trail_keep_ratio: float = 0.48
    bullish_hold_max_hold_multiplier: float = 1.6
    scalp_micro_lock_min_best_points: float = 4.5
    scalp_min_hold_before_micro_lock_seconds: int = 90
    midday_chop_block_scalps: bool = True
    midday_chop_start_hour: int = 11
    midday_chop_start_minute: int = 30
    midday_chop_end_hour: int = 13
    midday_chop_end_minute: int = 30
    adaptive_target_enabled: bool = True
    tick_fusion_enabled: bool = True  # multi-timeframe momentum fusion

    # Capital / risk — ranked FTV allocation keeps cash reserved and fills the
    # strongest approved contracts first instead of spending the whole book on one leg.
    fallback_capital_inr: float = 200_000
    max_sizing_capital_inr: float = 200_000
    per_trade_capital_pct: float = 0.90
    ftv_ranked_allocation_enabled: bool = True
    ftv_allocation_weights_csv: str = "0.60,0.25,0.10"
    ftv_allocation_remaining_pct: float = 0.90
    ftv_allocation_cash_reserve_pct: float = 0.0
    ftv_allocation_max_positions: int = 3
    ftv_allocation_max_same_side: int = 2
    ftv_allocation_require_ftv: bool = True
    # Rank-1 sleeve: when 90% budget cannot afford 1 lot but remaining margin can,
    # deploy full remaining for that entry (Aug26 ftv_allocation_below_one_lot @ ₹573).
    ftv_allocation_rank_one_min_one_lot_enabled: bool = True
    # Pad-lane / FTV-direct / full-sleeve rank-1 uses 100% of remaining, not 90%.
    ftv_allocation_full_remaining_on_full_sleeve_enabled: bool = True
    # Final-policy-authorized rank-1 ELITE/EXPLODING entries keep every
    # cash-affordable sleeve lot instead of being reduced by the standard SL budget.
    top_rank_first_lift_full_budget_lots_enabled: bool = True
    aggressive_lot_sizing: bool = True
    aggressive_min_tqs: int = 50
    aggressive_min_explosion_score: int = 38
    explosion_confirmed_min_score: int = 45
    explosion_max_lots: int = 0  # 0 = capital-derived max on 85% per trade
    aggressive_min_swing_confidence: int = 65
    aggressive_max_open_scalps: int = 1
    max_lots_per_trade: int = 0  # 0 = no hard cap; size from 85% capital only
    min_lots_per_trade: int = 1
    max_risk_per_trade_inr: float = 4_000
    min_per_trade_risk_inr: float = 3_000
    per_trade_risk_pct: float = 0.95
    max_exposure_pct: float = 0.95
    position_sl_cap_pct: float = 0.08
    position_tp_target_pct: float = 0.12
    # Never let the position-tuned target land below the stop (budget-cap SL could exceed
    # the target floor → inverted R:R). Guarantee target >= stop x this ratio.
    position_min_risk_reward: float = 1.2
    emergency_stop_enabled: bool = False
    emergency_stop_inr: float = 20_000
    emergency_stop_scale_with_position: bool = False
    # Risk guardrails (Aug6 SENSEX 78800 PE: never-green ELITE, 27 lots, ran to −37pt =
    # −₹20k; Jul30 90-lot ELITE = −₹86k). Three bounded, always-on protections:
    # 1) Never-green cut — a trade that printed NO green and is down past a tight floor is
    #    directionally wrong; cut faster than the full adaptive stop.
    explosion_never_green_stop_enabled: bool = False
    explosion_never_green_min_green_points: float = 0.5
    explosion_never_green_stop_points: float = 4.0
    explosion_never_green_stop_pct: float = 8.0
    explosion_never_green_min_hold_seconds: int = 10
    # Scratch a launch that immediately loses both price and velocity confirmation.
    explosion_failed_launch_exit_enabled: bool = False
    explosion_failed_launch_min_hold_seconds: int = 15
    explosion_failed_launch_max_hold_seconds: int = 45
    explosion_failed_launch_max_best_points: float = 1.0
    explosion_failed_launch_min_loss_points: float = 1.5
    explosion_failed_launch_max_velocity_3s: float = 0.0
    # Same-chain cooldown after a failed launch / never-green chop spike.
    explosion_failed_launch_reentry_block_enabled: bool = True
    explosion_failed_launch_reentry_cooldown_seconds: int = 1800
    # Block ATM±N adjacent strikes (1 = exact + one step each side).
    explosion_failed_launch_reentry_strike_steps: int = 1
    # Exit reasons that arm the cooldown (never-green hard cut often lacks v3<0).
    # adaptive_stop_loss counts only when best ≤ explosion_failed_launch_max_best_points.
    explosion_failed_launch_reentry_exit_reasons_csv: str = (
        "explosion_failed_launch,explosion_never_green_stop,adaptive_stop_loss"
    )
    # Re-entry ML gate — Aug28 winners ~56% ML, 24050 losses ~41-43%.
    explosion_reentry_ml_win_prob_gate_enabled: bool = True
    explosion_reentry_ml_win_prob_min: float = 0.52
    explosion_reentry_ml_win_prob_same_strike_min: float = 0.55
    # 2) Hard INR ceilings: ~1% of ₹2L normally, ~2% only for a fully proven launch.
    explosion_per_trade_max_loss_inr: float = 2_000.0
    explosion_exceptional_per_trade_max_loss_inr: float = 4_000.0
    # Index-confirmed near-base FTV size-up: a genuine index thrust (drift/burst/index
    # helpers) at a near-base ELITE/EXPLODING lift is NOT a premium-only fake trap, so it
    # may keep its elevated (~2x) size even on a chop day (lifts the fake-trap chop cap) and
    # gets a wider ~2% per-trade rupee stop so the bigger size survives the normal near-base
    # shakeout instead of being clipped at a ~2pt stop. Still bounded: elevated (not full
    # sleeve), whipsaw/never-green guards stay, and the 10%/day loss stop is the backstop.
    index_confirmed_ftv_size_up_enabled: bool = True
    index_confirmed_ftv_max_base_rel_pct: float = 20.0
    index_confirmed_ftv_per_trade_max_loss_inr: float = 4_000.0
    # ELITE full-lot + ride-to-max-TP: index-confirmed ELITE FTV deploys the full per-trade
    # capital budget (~₹1.8L = 90% of ₹2L) and holds to max TP. Do NOT shrink lots to a tiny
    # ₹10k/8pt risk envelope — that caps size at ~half capital and stop-outs the runner on a
    # normal base shakeout before the vertical. Structural SL is widened (% of premium); the
    # ₹20k/day stop remains the session backstop. Per-trade INR clip is off by default (0)
    # so a wide point SL can breathe without an early rupee kill.
    elite_full_lot_enabled: bool = True
    elite_full_lot_requires_index_confirm: bool = True
    elite_full_lot_use_full_capital: bool = True
    # 0 = disabled (prefer point SL + daily loss stop). Set >0 only for a hard INR clip.
    elite_full_lot_risk_inr: float = 0.0
    # Legacy risk-budget sizing only when elite_full_lot_use_full_capital=False.
    elite_full_lot_est_stop_points: float = 8.0
    # Proper room for V/FTV shakeouts — not a toy 8pt stop that clips then watches the rip.
    elite_full_lot_min_stop_points: float = 16.0
    elite_full_lot_min_stop_pct_of_premium: float = 0.18
    elite_full_lot_preserve_lots_over_sl_budget: bool = True
    elite_ride_max_tp_enabled: bool = True
    # 3) Whipsaw flip — after a same-session WIN on the opposite side, don't max-size the
    #    counter-flip (Aug6: CALLs won, then a max-size PUT flip lost). Cap flip size.
    explosion_whipsaw_flip_guard_enabled: bool = True
    explosion_whipsaw_flip_lookback_seconds: int = 3600
    explosion_whipsaw_flip_lot_cap: int = 8
    # After opposite-side win, weak tape flips are blocked (Aug6 PUT v3=0.54).
    # Hot flips (≥ breakout floor) still get the lot cap only.
    explosion_whipsaw_flip_require_velocity: bool = True
    explosion_whipsaw_flip_min_velocity_3s: float = 2.5
    explosion_whipsaw_flip_block_weak: bool = True
    scalp_stop_points: float = 3.0  # legacy fallback when premium unknown
    # Calculated scalp SL = max(min_points, premium * pct), capped at max_points.
    scalp_stop_pct_of_premium: float = 0.10
    scalp_stop_max_points: float = 15.0
    scalp_stop_min_points: float = 2.5
    scalp_stop_min_hold_seconds: int = 30
    scalp_trail_arm_points: float = 3.0
    scalp_trail_keep_ratio: float = 0.60
    scalp_trail_step_points: float = 2.0
    scalp_trail_tight_arm: float = 8.0
    scalp_trail_tight_points: float = 3.0
    # High-conf live trail: arm at least this fraction of entry TP (hold winners).
    high_conf_trail_arm_min_target_frac: float = 0.22
    # Defer scalp_trail_sl while best is still a scratch vs entry TP.
    scalp_trail_defer_until_target_frac: float = 0.20
    scalp_trail_defer_min_chart_confidence: float = 55.0
    scalp_micro_giveback_points: float = 3.0
    scalp_no_progress_seconds: int = 150
    scalp_no_progress_aligned_seconds: int = 420
    scalp_no_progress_skip_when_aligned: bool = True

    # Daily target — 18% of capital per session (confidence-gated full limits)
    daily_profit_target_from_capital: bool = True
    daily_profit_target_pct: float = 0.18
    daily_profit_target_inr: float = 44_000  # fallback when pct mode off
    daily_profit_trail_inr: float = 5_000  # legacy; unused when stage locks enabled
    daily_profit_stage_locks_enabled: bool = True
    daily_profit_stage_block_entries_min_stage: int = 2
    daily_profit_stage_pcts_csv: str = "0.55,0.88,1.12"  # env: DAILY_PROFIT_STAGE_PCTS
    daily_profit_stage_from_target: bool = True
    daily_profit_stage_target_mults_csv: str = "0.5,1.0,1.5"  # locks at 9%, 18%, 27% of cap

    # Daily 18% strategy — progressive playbook across all day types
    daily_18pct_strategy_enabled: bool = True
    daily_18pct_medium_confidence_min: float = 55.0
    daily_18pct_high_confidence_min: float = 72.0
    daily_18pct_elite_confidence_min: float = 85.0
    daily_18pct_unlock_full_limits_min_confidence: float = 78.0
    daily_18pct_chop_max_trades: int = 10
    daily_18pct_expiry_max_trades: int = 5
    daily_18pct_expiry_min_rank: float = 65.0
    daily_18pct_full_limit_max_trades: int = 12

    # Day-adaptive engine — trade well on worst, chop, normal, and good days
    day_adaptive_enabled: bool = True
    day_adaptive_worst_rank_cap: float = 68.0

    # Bad-day routing — fading expiry index, cross-index preference, high-confidence only
    bad_day_routing_enabled: bool = True
    bad_day_high_confidence_min_rank: float = 65.0
    bad_day_severe_min_rank: float = 78.0
    bad_day_severe_session_loss_inr: float = -25_000.0
    bad_day_session_loss_inr: float = -8_000.0
    bad_day_recent_loss_count: int = 2
    bad_day_min_symbol_tqs: float = 42.0
    bad_day_fading_expiry_min_rank: float = 65.0
    bad_day_fading_symbol_penalty: float = 18.0
    bad_day_alternate_index_bonus: float = 14.0
    bad_day_alternate_aligned_bonus: float = 8.0
    cross_index_elite_priority_enabled: bool = True
    cross_index_elite_min_session_move_pct: float = 40.0
    cross_index_elite_priority_bonus: float = 22.0
    expiry_fading_symbol_loss_inr: float = -5_000.0
    expiry_fading_session_loss_inr: float = -10_000.0
    expiry_fading_max_symbol_tqs: float = 42.0
    bad_day_cheap_premium_threshold_inr: float = 55.0
    bad_day_cheap_premium_lot_cap: int = 20

    # Worst-day pause — identify early, pause regular entries, breakout-only
    worst_day_pause_enabled: bool = True
    worst_day_pause_score_threshold: float = 45.0
    worst_day_early_chop_pause: bool = True
    worst_day_breakout_only_enabled: bool = True
    worst_day_breakout_min_rank: float = 68.0
    worst_day_breakout_min_velocity_3s: float = 2.5
    # Intraday TREND-OVERRIDE: a morning "chop/worst day" verdict is stale once the index
    # genuinely breaks out. When spot is at/near a fresh session extreme WITH aligned 5m
    # momentum AND a confirmed index thrust (sustained drift or same-direction spike burst),
    # lift the worst-day BREAKOUT_ONLY/full-pause so a top ELITE/EXPLODING can trade the real
    # trend. Never lifts the SEVERE session-loss pause; still bounded by the daily loss stop.
    # Requires sustained thrust (not a single spike) + a real session range, so chop can't
    # trip it. (Aug20 SENSEX +0.82% breakout stood down all day under a stale chop verdict.)
    worst_day_intraday_trend_override_enabled: bool = True
    index_trend_override_near_extreme_pct: float = 0.05
    index_trend_override_min_mom5_pct: float = 0.10
    index_trend_override_min_range_pct: float = 0.15
    # Structured near-ATM CE/PE soft floor + peak-velocity carry (key name kept for compat).
    worst_day_structured_ce_min_velocity_3s: float = 1.5
    worst_day_breakout_peak_velocity_bypass_enabled: bool = True
    worst_day_breakout_min_symbol_tqs: float = 45.0
    worst_day_breakout_tiers_csv: str = "ELITE,EXPLODING"
    worst_day_breakout_require_chart_align: bool = True
    # Aug6: elite_never_block short-circuited worst-day before chart-align / cold-base
    # checks. Require both for the elite bypass on BREAKOUT_ONLY / PAUSED days.
    worst_day_elite_bypass_require_chart_align: bool = True
    worst_day_elite_bypass_block_cold_base: bool = True
    worst_day_full_pause_loss_inr: float = -20_000.0
    worst_day_blocks_live: bool = True
    worst_day_call_block_enabled: bool = True
    worst_day_call_block_symbols_csv: str = "SENSEX"
    worst_day_slow_bounce_min_rank: float = 55.0
  # Worst-day defensive ITM fade — alternate index, tight targets, 1 lot
    worst_day_itm_fade_enabled: bool = True
    worst_day_itm_fade_alternate_only: bool = True
    worst_day_itm_fade_min_rank: float = 52.0
    worst_day_itm_fade_max_itm_steps: int = 1
    worst_day_itm_fade_lot_cap: int = 1
    worst_day_itm_fade_min_premium_inr: float = 90.0
    worst_day_itm_fade_min_tqs: float = 28.0
    worst_day_itm_fade_min_velocity_pct: float = 0.08
    worst_day_itm_fade_max_velocity_pct: float = 1.5
    worst_day_itm_fade_target_points: float = 2.5
    worst_day_itm_fade_stop_points: float = 2.0
    worst_day_itm_fade_micro_target_points: float = 1.5
    worst_day_itm_fade_max_hold_seconds: int = 90
    worst_day_itm_fade_rank_bonus: float = 8.0
    # Worst-day quick scalps — alternate index chop fades only
    # Jul20 — block quick_sideways only; scalp + momentum explosions stay allowed.
    worst_day_quick_enabled: bool = False
    worst_day_quick_alternate_only: bool = True
    worst_day_quick_min_rank: float = 60.0
    worst_day_quick_max_velocity_pct: float = 1.2
    worst_day_quick_rank_bonus: float = 6.0
    # Hard-block quick_sideways on BREAKOUT_ONLY/PAUSED (not scalp/momentum).
    worst_day_block_quick_trades: bool = True
    # Allow scalp / slow_bounce on worst days when score clears breakout floor.
    worst_day_allow_scalp_momentum: bool = True
    worst_day_scalp_min_rank: float = 68.0
    # Elite momentum may flip side after an opposite-side loss (Jul20 24200 CE → 102).
    whipsaw_elite_momentum_flip_bypass_enabled: bool = True
    whipsaw_elite_momentum_flip_min_score: float = 85.0
    worst_day_dead_zone_enabled: bool = True
    worst_day_dead_zone_start_hour: int = 11
    worst_day_dead_zone_start_minute: int = 0
    worst_day_dead_zone_end_hour: int = 12
    worst_day_dead_zone_end_minute: int = 0
    # Allow ELITE/EXPLODING vertical rips through 11:00–12:00 dead zone
    worst_day_dead_zone_explosion_bypass_enabled: bool = True
    worst_day_dead_zone_bypass_min_tier: str = "EXPLODING"
    worst_day_dead_zone_bypass_min_peak_pct: float = 30.0
    worst_day_dead_zone_bypass_min_velocity_3s: float = 2.0
    worst_day_dead_zone_bypass_min_session_move_pct: float = 35.0
    # Narrow 11:00–12:00 bypass for ELITE/EXPLODING armed_base at 2–25% local pad + ≥25% peak
    worst_day_dead_zone_local_base_bypass_enabled: bool = True
    worst_day_dead_zone_local_base_bypass_min_tier: str = "EXPLODING"
    worst_day_dead_zone_local_base_min_peak_pct: float = 25.0
    worst_day_dead_zone_local_base_min_lb_pct: float = 2.0
    worst_day_dead_zone_local_base_max_lb_pct: float = 25.0
    day_adaptive_chop_rank_cap: float = 70.0
    day_adaptive_good_day_rank_relief: float = 3.0

    # Dual-mode weekly playbook — defensive worst days vs aggressive good-day capture
    dual_mode_enabled: bool = True
    defensive_daily_target_pct_min: float = 0.05
    defensive_daily_target_pct_max: float = 0.10
    aggressive_good_day_min_rank: float = 52.0
    aggressive_good_day_rank_relief: float = 10.0
    aggressive_good_day_min_tqs: float = 45.0
    aggressive_good_day_trade_cap_bonus: int = 8
    aggressive_good_day_lot_scale: float = 1.2
    aggressive_good_day_skip_best_trades_only: bool = True
    aggressive_good_day_skip_worst_day_policy: bool = True
    aggressive_good_day_bypass_last_n_pause: bool = True
    aggressive_good_day_bypass_bad_day_floor: bool = True
    aggressive_good_day_allow_building_tier: bool = True

    # ICT / FVG breakout monitor — flat-then-vertical premium rips (8→393 / 26→70 CE style)
    ict_breakout_monitor_enabled: bool = True
    ict_fvg_min_gap_pct: float = 12.0
    ict_flat_base_max_range_pct: float = 8.0
    ict_displacement_min_velocity_3s: float = 2.2
    # Full vertical confirmation (legacy mega-style). Early breakout uses ict_early_vertical_*.
    ict_vertical_min_session_move_pct: float = 80.0
    # Early flat→vertical: arm pattern near the base (was 28% — missed first lift).
    ict_early_vertical_min_session_move_pct: float = 12.0
    ict_early_vertical_min_velocity_3s: float = 2.0
    # Aligned with detector volAwaken boost (max(surge, 2.0)) — was 3.0 so ICT
    # never saw volume_awakening after WS/REST blended surges of ~2.0 (Jul23 gap).
    ict_volume_surge_awaken_min: float = 2.0
    ict_mega_rip_min_session_move_pct: float = 200.0
    ict_breakout_min_score: float = 28.0
    ict_fvg_score_bonus: float = 14.0
    ict_flat_vertical_score_bonus: float = 18.0
    ict_early_breakout_score_bonus: float = 16.0
    ict_mega_rip_score_bonus: float = 22.0
    ict_max_rank_bonus: float = 30.0
    ict_good_day_capture_enabled: bool = True
    # All-day ICT capture — NORMAL + AGGRESSIVE (not only good-day AGGRESSIVE).
    ict_all_day_capture_enabled: bool = True
    ict_all_day_capture_min_score: float = 30.0
    ict_all_day_lot_multiplier: float = 0.85
    ict_good_day_min_score: float = 35.0
    ict_good_day_rank_bonus: float = 18.0
    ict_mega_rip_rank_bonus: float = 25.0
    ict_breakout_no_progress_seconds: int = 360
    ict_mega_rip_no_progress_seconds: int = 600
    ict_breakout_trail_arm_multiplier: float = 1.5
    ict_mega_rip_trail_arm_multiplier: float = 2.2
    ict_good_day_force_max_lots: bool = True
    # Late fade-chase: skip new entries when peak already extended and live velocity cooling.
    # Was 120% — too late (24250-style +91% chases still passed).
    ict_late_chase_block_enabled: bool = True
    ict_late_chase_min_peak_pct: float = 75.0
    ict_late_chase_max_live_velocity_3s: float = 1.0
    # DEFENSIVE/worst days: still catch true flat→vertical base rips (12→392 PE style).
    # Aug10: BUILDING was admitted here and full-lotted into a dead spike — ELITE only.
    ict_defensive_base_rip_enabled: bool = True
    ict_defensive_base_rip_tiers_csv: str = "ELITE,EXPLODING"
    # Reduced size when full-lots tiers do not apply (never ≥0.99 — blocks force-max).
    ict_defensive_base_rip_lot_multiplier: float = 0.55
    ict_defensive_base_rip_max_move_pct: float = 55.0
    # Full lots only for top tiers on defensive rip (never BUILDING).
    ict_defensive_base_rip_full_lots_tiers_csv: str = "ELITE,EXPLODING"
    # Always: defensive/worst base rip only for top ELITE/EXPLODING at local base —
    # do not admit every EXPLODING FTV print (Aug18 mid-quality 71.5 / B).
    ict_defensive_base_rip_require_top_quality: bool = True
    ict_defensive_base_rip_min_score: float = 75.0
    ict_defensive_base_rip_min_quality: float = 70.0
    ict_defensive_base_rip_min_velocity_3s: float = 2.5
    # Aug18: EXPIRY WORST armed/defensive EXPLODING spikes failed — block unless
    # a true ELITE high-quality base rip clears the raised bar.
    ict_defensive_base_rip_block_expiry_worst: bool = True
    ict_defensive_base_rip_expiry_worst_min_tier: str = "ELITE"
    ict_defensive_base_rip_expiry_worst_min_quality: float = 85.0
    ict_defensive_base_rip_expiry_worst_min_score: float = 90.0
    ict_defensive_base_rip_expiry_worst_min_velocity_3s: float = 3.0
    # Max-profit trail — do not bank tiny TP on base→vertical ICT (25pt elite TP kills 12→392).
    ict_max_profit_skip_hard_target: bool = True
    ict_max_profit_target_points: float = 180.0
    ict_max_profit_trail_keep_ratio: float = 0.42
    ict_max_profit_max_hold_seconds: int = 1200

    def daily_profit_stage_pcts(self) -> list[float]:
        return [float(x.strip()) for x in self.daily_profit_stage_pcts_csv.split(",") if x.strip()]

    def daily_profit_stage_target_mults(self) -> list[float]:
        return [float(x.strip()) for x in self.daily_profit_stage_target_mults_csv.split(",") if x.strip()]

    use_upstox_capital_for_sizing: bool = False  # paper uses fallback_capital_inr unless live trading

    # Quantity per lot (units) — NSE/BSE contract sizes
    lot_size_nifty: int = 65
    lot_size_banknifty: int = 30
    lot_size_sensex: int = 20
    use_upstox_lot_sizes: bool = False  # when false, env values above are authoritative

    simple_max_lots: int = 0  # unused when max_lots_per_trade=0; sizing is capital-derived
    simple_target_lots: int = 0
    simple_min_lots: int = 1

    adaptive_exits_enabled: bool = True
    ml_exit_tuning_enabled: bool = True

    # Chart-driven SL/TP/trailing — fib, pivots, Ichimoku, SMC for all trade types
    chart_exit_levels_enabled: bool = True
    chart_exit_refresh_seconds: int = 30
    chart_trail_tune_seconds: int = 5
    chart_exit_max_target_points: float = 80.0
    chart_exit_max_index_structure_pct: float = 0.04
    chart_confidence_trail_enabled: bool = True
    all_day_high_quality_enabled: bool = True
    # Display chartConf floor after rescale (was 62); rescale(62)≈48.2.
    all_day_min_chart_confidence: float = 48.2
    all_day_min_rank_score: float = 68.0
    # Was 58; rescale(58)≈46.8.
    quick_trail_promote_min_confidence: float = 46.8
    quick_trail_promote_min_best_points: float = 2.0
    # chartConf rescale — uncapped additive score → display [40, 100]
    chart_confidence_scale_raw_lo: float = 40.0
    chart_confidence_scale_raw_hi: float = 200.0
    chart_confidence_display_min: float = 40.0
    chart_confidence_display_max: float = 100.0

    # Edge engine — realtime statistical entry scoring + 2.5+ PF feedback loop
    edge_engine_enabled: bool = True
    edge_session_pf_target: float = 2.5
    edge_session_pf_tighten_below: float = 1.5
    edge_min_score_for_full_size: float = 72.0
    edge_min_score_for_entry: float = 52.0
    edge_lot_scale_min: float = 0.65
    edge_lot_scale_max: float = 1.25
    lot_size_multiplier: float = 1.40
    edge_velocity_exhaustion_ratio: float = 0.35
    edge_rsi_overbought_exit: float = 72.0
    edge_macd_fade_exit_enabled: bool = True

    symbols_csv: str = Field(default="NIFTY,SENSEX", validation_alias="SYMBOLS")

    @computed_field
    @property
    def symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.symbols_csv.split(",") if s.strip()]

    # Persistence
    trade_store_dir: str = "/tmp/nexusquant/trades"
    trade_log_file: str = ""  # default: {trade_store_dir}/trades.log
    radar_archive_enabled: bool = True
    radar_archive_dir: str = ""  # default: {trade_store_dir}/radar_archives
    radar_archive_top_n_per_day: int = 100
    # Keep one trading week of daily archives for EOD replay / tradeability review.
    # Premium tapes are large; unbounded retention fills the disk and stalls the backend.
    radar_archive_retention_days: int = 7
    # When true, daily finalize ZIPs only bundle artifacts needed for EOD replay and
    # funnel/scorecard analysis (premium tape, funnel, scorecard). Skips alerts tape,
    # pipeline history, and per-day FTV calibration blobs.
    radar_analysis_only_storage: bool = True
    # Delete intraday telemetry JSONL after a successful daily finalize (data lives in ZIP).
    radar_purge_telemetry_after_finalize: bool = True
    # When true, refuse to purge session telemetry unless premium_tape.jsonl was bundled
    # into the daily ZIP (prevents losing the only replay tape on partial finalize).
    radar_purge_requires_bundled_premium_tape: bool = True
    radar_learning_enabled: bool = True
    # Throttle the all-strike premium tape to one sample / N seconds. It used to write EVERY
    # observation cycle (0), producing 1GB+/day tapes that (a) fill the disk and (b) make the
    # startup restore read a multi-hundred-MB file — on a watchdog restart that becomes a
    # slow/OOM restart loop. 10s granularity still replays FTV/V base lifts fine, and the LIVE
    # trigger never uses the tape. Set 0 only for short debug windows.
    radar_premium_tape_sample_seconds: int = 10
    # Cap how much of the (append-only, time-ordered) premium tape the startup restore reads.
    # It only needs the last ~35 min, so tail-read at most this many bytes instead of parsing
    # the whole intraday file — bounds startup time/memory regardless of tape size.
    radar_restore_tail_max_bytes: int = 67_108_864  # 64 MiB
    # EOD trade-report replay: tail-cap the premium-tape parse. Pre-throttle tapes reach 1GB+
    # and a full parse + replay takes ~21s, blowing the report request timeout. 256 MiB keeps
    # the endpoint responsive on pathological historical tapes and is a no-op for the (now
    # 10s-sampled) tapes going forward. 0 disables the cap (full read).
    radar_report_tape_max_bytes: int = 268_435_456  # 256 MiB
    radar_alerts_tape_enabled: bool = False
    # Pipeline health JSONL — useful for ops debug, not required for EOD trade replay.
    radar_pipeline_history_enabled: bool = False
    radar_outcome_horizons_seconds_csv: str = "60,180,300,900,1800"
    radar_outcome_target_pct: float = 20.0
    radar_outcome_stop_pct: float = 10.0
    radar_hindsight_flat_window_seconds: int = 120
    radar_hindsight_flat_max_range_pct: float = 8.0
    radar_hindsight_vertical_min_move_pct: float = 40.0
    radar_hindsight_lookahead_seconds: int = 1800
    radar_funnel_dedupe_seconds: int = 60
    radar_health_stale_seconds: int = 45
    radar_archive_finalize_hour: int = 16
    radar_archive_finalize_minute: int = 0
    radar_backup_dir: str = ""
    radar_backup_s3_bucket: str = ""
    radar_backup_s3_prefix: str = "nexusquant/radar"
    radar_backup_retry_max: int = 3
    radar_backup_retry_base_seconds: float = 1.0
    radar_backup_verify_head: bool = True
    daily_token_once: bool = True

    # Swing trading (multi-day paper holds)
    swing_trading_enabled: bool = False
    swing_max_hold_days: int = 5
    swing_target_pct: float = 30.0
    swing_stop_pct: float = 12.0
    swing_trail_arm_pct: float = 20.0
    swing_trail_keep: float = 0.70
    swing_min_lots: int = 25
    swing_target_lots: int = 75
    swing_max_open: int = 2
    swing_max_loss_inr: float = 25_000


def _with_latency_presets(settings: Settings) -> Settings:
    """Apply cadence presets unless individual env vars are set explicitly."""
    if settings.latency_mode == "normal":
        return settings
    preset = LATENCY_PRESETS.get(settings.latency_mode)
    if not preset:
        return settings
    updates: dict[str, Any] = {}
    for key, value in preset.items():
        env_key = key.upper()
        if env_key not in os.environ:
            updates[key] = value
    if updates:
        return settings.model_copy(update=updates)
    return settings


# Audit-week floors — only applied when local_base_audit_week_enabled=true.
# Each value is the earliest (most aggressive) threshold we allow for validation.
AUDIT_WEEK_LOCAL_BASE_OVERRIDES: dict[str, float] = {
    "ftv_s_strict_min_local_base_move_pct": 2.0,
    "winner_local_base_min_local_base_move_pct": 2.0,
    "explosion_local_base_entry_min_move_pct": 8.0,
    "local_base_exploding_entry_min_move_pct": 8.0,
    "explosion_local_base_trust_min_move_pct": 5.0,
    "building_rip_local_base_min_move_pct": 1.5,
    "building_rip_ftv_min_local_base_move_pct": 1.5,
    "building_ltp_monitor_min_ms": 50.0,
    "ict_elite_base_ready_max_move_pct": 8.0,
    "winner_local_base_min_explosion_score": 70.0,
    "ftv_s_strict_min_explosion_score": 80.0,
    # Early local-base pad (e.g. 24→30) — soften velocity/TQS without opening chase.
    "ict_v_rip_min_velocity_3s": 0.8,
    "ict_v_rip_min_velocity_9s": 0.6,
    "ict_v_rip_volume_awake_min_velocity_3s": 0.75,
    "ict_v_rip_min_quality": 45.0,
    "ict_armed_base_launch_min_tqs": 45.0,
    "ict_armed_base_launch_min_score": 55.0,
    "first_lift_trade_min_velocity_3s": 1.0,
    "first_lift_trade_min_velocity_9s": 0.7,
    "first_lift_helper_confirm_min_velocity_3s": 0.9,
}


def audit_week_local_base_overrides() -> dict[str, float]:
    """Return the audit-week threshold map (for health / audit API exposure)."""
    return dict(AUDIT_WEEK_LOCAL_BASE_OVERRIDES)


def _with_audit_week_overrides(settings: Settings) -> Settings:
    """Lower local-base entry/detection floors for the validation week."""
    if not bool(getattr(settings, "local_base_audit_week_enabled", False)):
        return settings
    updates: dict[str, Any] = {}
    for key, audit_value in AUDIT_WEEK_LOCAL_BASE_OVERRIDES.items():
        current = getattr(settings, key, None)
        if current is None:
            continue
        try:
            current_f = float(current)
            audit_f = float(audit_value)
        except (TypeError, ValueError):
            continue
        if "max_" in key:
            updates[key] = max(current_f, audit_f)
        elif "min_" in key or key.endswith("_min_ms"):
            updates[key] = min(current_f, audit_f)
        else:
            updates[key] = audit_f
    if updates:
        return settings.model_copy(update=updates)
    return settings


@lru_cache
def get_settings() -> Settings:
    return _with_audit_week_overrides(_with_latency_presets(Settings()))
