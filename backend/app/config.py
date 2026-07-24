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

    # News
    news_provider: Literal["finnhub", "none"] = "finnhub"
    finnhub_api_key: str = ""

    # Safety
    enable_live_trading: bool = False
    paper_trading: bool = True
    auto_trading_enabled: bool = True
    shadow_trade_all_signals: bool = True

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
    entry_scan_interval_ms: int = 1000
    expiry_entry_scan_interval_ms: int = 500
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
    news_cache_seconds: int = 60
    background_market_monitor_enabled: bool = True

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
    # Explosion-only book — skip quick/swing (Jul20 bleed was quick/FOMO). Scalps allowed
    # back guarded (below) because they were PF 1.3 across the book and caught Jul17 +43k.
    explosion_only_trading_enabled: bool = True
    # Allow guarded scalps even under explosion-only: first-green lot cap + chart align.
    # Quick_sideways / swing stay off (quick_sideways was the −34k disaster).
    explosion_only_allow_guarded_scalp: bool = True
    # Promote high-confidence radar explosions the missed-trade monitor flags as bullish/base-window.
    # Does NOT trade premium_out_of_band cheap OTM chases (Jul20 24550 @ ₹3 — correctly blocked).
    missed_explosion_promote_enabled: bool = True
    missed_explosion_promote_min_score: float = 70.0
    missed_explosion_promote_min_move_pct: float = 28.0
    missed_explosion_promote_max_move_pct: float = 55.0
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
    # No new EXPLOSIVE entries once the session/peak move is already mostly done.
    explosion_extended_chase_block_enabled: bool = True
    explosion_extended_chase_min_move_pct: float = 70.0
    # Soft zone: keep small size only (before hard block).
    explosion_extended_soft_min_move_pct: float = 50.0
    # Base-relative chase bypass — a fresh flat→vertical break off a consolidation base
    # (SENSEX 76300 PE: 30-100 range then 100-144 break) reads as high day-move but the
    # move FROM THE BASE is still early. Allow it when volume is rising + base move in window.
    ict_base_relative_chase_bypass_enabled: bool = True
    ict_base_relative_chase_max_move_pct: float = 55.0
    ict_base_relative_chase_abs_move_cap_pct: float = 160.0
    # Jul23 SENSEX 76400 PE: day-move +471% after an earlier run-up/dump, but the NEW leg
    # launched from the 14:35 local V-bottom (~42). Chase/entry must use that local base
    # (tradeable 15–40% — earlier than the old 28–70 catch zone); day-session % alone
    # always looks like a chase. ~50% from base was catching, not profitable.
    explosion_chase_use_local_base: bool = True
    explosion_local_base_chase_max_move_pct: float = 40.0
    explosion_local_base_entry_min_move_pct: float = 15.0
    # Ignore micro baseRel (<8%) for immature/chase — Jul24 PUTs showed ~1–2%
    # "local base" noise while day-move was already mature (~28%).
    explosion_local_base_trust_min_move_pct: float = 8.0
    ict_local_base_lookback_polls: int = 16
    ict_local_base_min_dump_pct: float = 25.0
    explosion_extended_soft_lot_cap: int = 6
    explosion_hard_lot_cap: int = 10
    # Early capture window preferred in ranking (base break → first expansion).
    explosion_early_window_min_move_pct: float = 28.0
    explosion_early_window_max_move_pct: float = 55.0
    # Immature explosion block — Jul20 losses at +0.8%/+1.4% "displacement" noise.
    # Require a real premium rip before EXPLOSIVE entries (unless true flat→vertical).
    explosion_immature_block_enabled: bool = True
    explosion_immature_min_session_move_pct: float = 22.0
    # Live confirmation — sticky ELITE / displacement spikes without live heat+structure
    # (Jul23 NIFTY 23900 PE v3=0.26 watch, SENSEX 76200 PE midday displacement-only).
    explosion_live_confirm_enabled: bool = True
    explosion_live_confirm_min_velocity_3s: float = 2.0
    explosion_live_confirm_ict_min_velocity_3s: float = 1.5
    # Jul24 23850 CE: structured near-ATM CALL may use softer live/peak velocity.
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
    explosion_faded_rip_max_live_velocity_3s: float = 0.5
    explosion_faded_rip_lot_cap: int = 6
    explosion_faded_rip_tighter_stop_mult: float = 0.85
    explosion_faded_rip_no_green_exit_enabled: bool = True
    explosion_faded_rip_no_green_seconds: int = 45
    explosion_faded_rip_min_green_points: float = 0.5
    faded_rip_no_green_hold_min_session_move_pct: float = 60.0
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
    fake_explosion_trap_chop_elite_lot_cap: int = 6
    fake_explosion_trap_otm_requires_or_breakout: bool = True
    fake_explosion_trap_post_win_lot_cap: int = 8
    fake_explosion_trap_post_win_max_pnl_inr: float = 3_000.0
    fake_explosion_trap_post_win_lookback: int = 1
    fake_explosion_trap_psychology_escalate: bool = True
    # Midday/chop ELITE without ICT structure → hard block (not soft lot-cap).
    fake_explosion_trap_midday_require_structure: bool = True
    # Size until first green — no full-size explosions before a proven green (Jul20 FOMO).
    size_until_first_green_enabled: bool = True
    size_until_first_green_lot_cap: int = 6
    # Modes capped until a green print in that mode (Jul20 never-green oversize: explosion + scalp).
    size_until_first_green_modes_csv: str = "explosion,scalp"
    # High-conviction override — take MAX lots + hold longer when a genuine base rip is
    # very high confidence (ELITE, score≥90, chartConf≥85, matched side, 28-55% window).
    # Bypasses the first-green + defensive throttles; fake-trap chop cap still applies.
    high_conviction_sizing_enabled: bool = True
    high_conviction_min_score: float = 90.0
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
    # Session mode feedback — promote/demote modes from today's PF (closes learning loop).
    session_mode_feedback_enabled: bool = True
    session_mode_feedback_min_trades: int = 2
    # Composer advisory → hard gate (standDown / side bias).
    composer_hard_gate_enabled: bool = True
    composer_bias_gate_enabled: bool = True
    # Never force ICT max lots on chop/RANGE (good-day override was Jul49-lot hole).
    ict_force_max_lots_block_on_chop: bool = True
    # High-mover / all-in bypasses must not reopen late chases.
    high_mover_bypass_max_move_pct: float = 70.0
    extreme_all_in_bypass_max_move_pct: float = 70.0
    explosion_macd_alignment_required: bool = True
    explosion_deep_otm_min_premium_inr: float = 3.0
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
    explosion_stop_min_hold_seconds: int = 15
    explosion_no_progress_enabled: bool = True
    explosion_no_progress_seconds: int = 150
    explosion_no_progress_aligned_seconds: int = 420
    explosion_no_progress_skip_when_aligned: bool = True
    explosion_reentry_cooldown_seconds: int = 180
    explosion_emergency_cooldown_seconds: int = 300
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

    # Symbol / instrument cooldown — stop same-strike churn after losses
    symbol_loss_cooldown_seconds: int = 180
    symbol_emergency_cooldown_seconds: int = 300
    symbol_streak_cooldown_seconds: int = 600
    reentry_score_penalty_per_loss: int = 5
    instrument_loss_cooldown_seconds: int = 300
    instrument_micro_win_cooldown_seconds: int = 180
    instrument_win_cooldown_seconds: int = 90
    instrument_max_entries_per_day: int = 3
    block_duplicate_open_leg: bool = True
    counter_breadth_min_score: int = 70

    # Controlled trading — pre-trade backtest + fewer entries
    controlled_trading_enabled: bool = True
    controlled_max_trades_per_day: int = 10
    controlled_rally_trade_cap_bonus: int = 4
    min_seconds_between_entries: int = 240
    pretrade_min_rank_score: float = 65.0
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
    best_trades_min_rank_score: float = 62.0
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

    # ITM / ATM / OTM strike selection (AUTO = regime-based)
    moneyness_selection_enabled: bool = True
    trade_moneyness_mode: str = "AUTO"  # AUTO | ITM | OTM | ATM
    moneyness_atm_tolerance_points: float = 50.0
    # Real listed strike intervals — NIFTY is 50, SENSEX/BANKNIFTY are 100. The old
    # hardcoded 100 for NIFTY halved its OTM-depth counting (deep-OTM guards too loose).
    nifty_strike_step: float = 50.0
    sensex_strike_step: float = 100.0
    banknifty_strike_step: float = 100.0
    moneyness_max_otm_steps: int = 2
    expiry_explosion_max_otm_steps: int = 4
    moneyness_max_itm_steps: int = 2
    moneyness_explosion_prefer: str = "ATM"
    # When explosion prefer is ATM, hard-block OTM (Jul23 76100 PE −₹1.3k after ATM miss).
    # ATM + shallow ITM still allowed; deep OTM FOMO is not a soft rank penalty.
    moneyness_explosion_block_otm: bool = True
    # Confirmed local-base CALL rip: allow shallow OTM (2–3 steps) when ATM CE is absent.
    moneyness_local_base_otm_bypass_enabled: bool = True
    moneyness_local_base_max_otm_steps: int = 3
    moneyness_local_base_otm_min_score: float = 75.0
    moneyness_scalp_chop_prefer: str = "ITM"
    moneyness_high_conf_prefer: str = "ITM"
    moneyness_rank_bonus: float = 12.0
    moneyness_mismatch_penalty: float = 15.0
    # ATM/ITM inside the 28–55% base window must not get fake-trap soft lot-cap
    # (Jul23 76300 PE high-conviction was cut to 6 lots then stopped never-green).
    fake_explosion_trap_skip_soft_cut_base_window: bool = True
    # High-conviction max lots win over fake-trap soft cap (hard block still applies).
    high_conviction_bypasses_fake_trap_lot_cap: bool = True

    # Expiry-day playbook — fewer trades, morning focus, worst-day prediction
    expiry_day_guards_enabled: bool = True
    expiry_max_trades_per_day: int = 6
    expiry_worst_day_max_trades: int = 3
    expiry_morning_only: bool = True
    expiry_morning_end_hour: int = 13
    expiry_morning_end_minute: int = 30
    expiry_evening_block_hour: int = 15
    expiry_evening_block_minute: int = 0
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
    expiry_dual_scalp_mode: bool = True
    expiry_dual_scalp_relax_whipsaw: bool = True
    expiry_dual_scalp_opposite_cooldown_seconds: int = 90
    expiry_explosion_open_block_minutes: int = 5

    # Expiry PM ITM quick scalps — day-of / next-day expiry, 14:00–15:25 IST
    expiry_pm_itm_quick_enabled: bool = True
    expiry_pm_itm_window_start_hour: int = 14
    expiry_pm_itm_window_start_minute: int = 0
    expiry_pm_itm_window_end_hour: int = 15
    expiry_pm_itm_window_end_minute: int = 25
    expiry_pm_itm_premium_max_inr: float = 280.0
    expiry_near_expiry_premium_max_inr: float = 300.0
    expiry_pm_itm_min_velocity_pct: float = 0.35
    expiry_pm_itm_min_rank_score: float = 52.0
    expiry_pm_itm_chart_bypass_breadth: bool = True
    expiry_pm_itm_alternate_index_enabled: bool = True
    # When one index is near-expiry (today/tomorrow), prefer the other for explosion/scalp
    pre_expiry_cross_index_enabled: bool = True
    pre_expiry_symbol_rank_penalty: float = 12.0
    pre_expiry_alternate_min_rank: float = 55.0
    pre_expiry_expiry_symbol_explosion_min_rank: float = 45.0
    expiry_aligned_explosion_trade_bypass_enabled: bool = True
    expiry_aligned_explosion_chart_bypass_enabled: bool = True

    # Slow bounce — expensive ITM mean-reversion (RSI/MACD recovery, low velocity)
    quick_sideways_slow_bounce_enabled: bool = True
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
    chart_alignment_rank_bonus: float = 10.0
    # Gap-down leaves spotChart/breadth BEARISH and blanket-blocks CEs (Jul24 NIFTY
    # 23700 CE EXPLODING 98 off a ~110 local base). Local premium base alone lifts
    # session-direction + sibling side/bias blocks; Ichimoku is optional.
    local_base_overrides_session_chart_enabled: bool = True
    local_base_ichimoku_chart_bypass_enabled: bool = True  # legacy alias, still honored
    local_base_chart_bypass_require_ichimoku: bool = False
    local_base_ichimoku_require_cloud: bool = False
    local_base_ichimoku_max_adverse_mom5_pct: float = 0.12
    local_base_chart_bypass_min_score: float = 38.0
    # Radar-lag side-bias fallback (no ICT flags yet) — keep above entry floor so
    # bare ELITE+15% cannot lift counter-breadth locks.
    local_base_chart_bypass_radar_min_move_pct: float = 28.0
    # Also lifts explosion_call_vs_bearish_breadth, market_opposes_side,
    # directional_call_needs_confirmation_*, bad_day/worst_day alignment.
    local_base_overrides_bearish_breadth: bool = True
    spot_chart_timeframe_minutes: int = 5
    spot_chart_1m_bars: int = 300  # 1m history for 5m resample + RSI/MACD warmup

    # Execution-time chart — fresh Upstox fetch right before order
    execution_chart_gate_enabled: bool = True
    execution_chart_force_upstox_refresh: bool = True
    execution_chart_premium_check_enabled: bool = True
    execution_chart_min_premium_momentum_pct: float = -0.15
    execution_chart_candle_count: int = 60

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
    daily_loss_stop_inr: float = 100_000.0
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
    loss_streak_elite_bypass_max_move_pct: float = 70.0
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
    momentum_rally_end_minute: int = 25
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

    # All-day explosive capture — 9:20–15:25 session rips (e.g. NIFTY 23850 PE 14:00 +1360%)
    all_day_explosion_capture_enabled: bool = True
    all_day_explosion_start_hour: int = 9
    all_day_explosion_start_minute: int = 20
    all_day_explosion_end_hour: int = 15
    all_day_explosion_end_minute: int = 25
    all_day_explosion_min_score: float = 38.0
    all_day_explosion_session_move_min_pct: float = 40.0
    all_day_explosion_extreme_move_min_pct: float = 80.0
    # ELITE +100% / 150%+ rips — ALL-IN bypass (AI report → trade).
    # NOTE: these move floors sit ABOVE the extended-chase ceiling
    # (extreme_all_in_bypass_max_move_pct = 70%), so the ALL-IN gate-skip in
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
    explosion_cheap_rip_min_premium_inr: float = 8.0
    explosion_cheap_rip_min_peak_pct: float = 25.0

    runner_trail_keep_ratio: float = 0.38
    runner_micro_giveback_points: float = 4.0
    runner_min_best_points: float = 5.0

    # Option premium (LTP) band for entries and scanners
    min_option_premium_inr: float = 20.0
    max_option_premium_inr: float = 300.0
    explosion_max_premium_inr: float = 400.0

    # Jun 25 profile — hold winners longer for 2.5+ profit factor
    enhanced_micro_target_points: float = 4.0
    enhanced_velocity_threshold: float = 1.2
    enhanced_tqs_entry: int = 50
    runner_alignment_override_score: int = 82
    rapid_scalp_mode_enabled: bool = False
    quick_sideways_enabled: bool = True
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
    scalp_max_lots: int = 0  # 0 = capital-derived max on 85% per trade
    scalp_target_points: float = 12.0  # unused — session targets in simple_profit
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

    # Capital / risk — 85% per trade, max lots = floor(budget / premium×lot_size)
    fallback_capital_inr: float = 200_000
    max_sizing_capital_inr: float = 200_000
    per_trade_capital_pct: float = 0.95
    aggressive_lot_sizing: bool = True
    aggressive_min_tqs: int = 50
    aggressive_min_explosion_score: int = 45
    explosion_confirmed_min_score: int = 45
    explosion_max_lots: int = 0  # 0 = capital-derived max on 85% per trade
    aggressive_min_swing_confidence: int = 65
    aggressive_max_open_scalps: int = 1
    max_lots_per_trade: int = 0  # 0 = no hard cap; size from 85% capital only
    min_lots_per_trade: int = 1
    max_risk_per_trade_inr: float = 200_000
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
    scalp_stop_points: float = 3.0
    scalp_stop_min_points: float = 2.5
    scalp_stop_min_hold_seconds: int = 30
    scalp_trail_arm_points: float = 3.0
    scalp_trail_keep_ratio: float = 0.60
    scalp_trail_step_points: float = 2.0
    scalp_trail_tight_arm: float = 8.0
    scalp_trail_tight_points: float = 3.0
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
    # Structured near-ATM CE soft floor + peak-velocity carry (Jul24 23850 CE).
    worst_day_structured_ce_min_velocity_3s: float = 1.5
    worst_day_breakout_peak_velocity_bypass_enabled: bool = True
    worst_day_breakout_min_symbol_tqs: float = 45.0
    worst_day_breakout_tiers_csv: str = "ELITE,EXPLODING"
    worst_day_breakout_require_chart_align: bool = True
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
    # Early flat→vertical (NIFTY 24400 CE 26→45): capture before 80% is reached.
    ict_early_vertical_min_session_move_pct: float = 28.0
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
    ict_defensive_base_rip_enabled: bool = True
    ict_defensive_base_rip_lot_multiplier: float = 0.55
    ict_defensive_base_rip_max_move_pct: float = 55.0
    # Max-profit trail — do not bank tiny TP on base→vertical ICT (25pt elite TP kills 12→392).
    ict_max_profit_skip_hard_target: bool = True
    ict_max_profit_target_points: float = 180.0
    ict_max_profit_trail_keep_ratio: float = 0.42
    ict_max_profit_max_hold_seconds: int = 1200

    def daily_profit_stage_pcts(self) -> list[float]:
        return [float(x.strip()) for x in self.daily_profit_stage_pcts_csv.split(",") if x.strip()]

    def daily_profit_stage_target_mults(self) -> list[float]:
        return [float(x.strip()) for x in self.daily_profit_stage_target_mults_csv.split(",") if x.strip()]

    use_upstox_capital_for_sizing: bool = True  # paper parity uses real margin when token present

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
    daily_token_once: bool = True

    # Swing trading (multi-day paper holds)
    swing_trading_enabled: bool = True
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


@lru_cache
def get_settings() -> Settings:
    return _with_latency_presets(Settings())
