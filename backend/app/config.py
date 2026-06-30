"""NexusQuant configuration — all settings from environment."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Data cadence — sub-second when WebSocket active; ms intervals override *_seconds
    market_poll_seconds: int = 1
    snapshot_cache_seconds: int = 1
    market_poll_interval_ms: int = 500
    market_poll_interval_ws_ms: int = 100
    tick_snapshot_interval_ms: int = 100
    snapshot_cache_interval_ms: int = 400
    tick_wake_debounce_ms: int = 25
    tick_fast_exit_enabled: bool = True
    entry_scan_interval_ms: int = 500
    news_cache_seconds: int = 60
    background_market_monitor_enabled: bool = True

    # Upstox WebSocket real-time feed + SSE push to UI
    upstox_ws_enabled: bool = True
    upstox_ws_mode: str = "ltpc"  # ltpc | full | full_d30 | option_greeks
    upstox_ws_reconnect_seconds: int = 5
    upstox_ws_resubscribe_seconds: int = 30
    tick_snapshot_seconds: int = 1  # legacy; tick_snapshot_interval_ms preferred
    market_poll_seconds_ws: int = 1  # legacy; market_poll_interval_ws_ms preferred
    sse_enabled: bool = True
    sse_heartbeat_seconds: int = 2

    # Upstox rate limiting / caching
    upstox_min_request_interval_ms: int = 100
    upstox_request_retries: int = 4
    upstox_rate_limit_cooldown_seconds: int = 45
    upstox_chain_cache_seconds: int = 8
    upstox_ltp_cache_seconds: int = 2
    upstox_expiries_cache_seconds: int = 600
    upstox_funds_cache_seconds: int = 90
    upstox_candles_cache_seconds: int = 60
    upstox_max_expiry_probes: int = 2
    capital_refresh_seconds: int = 90
    fetch_constituents_in_snapshot: bool = True
    index_momentum_enabled: bool = True
    open_caution_moment_min_rank: float = 48.0

    # Trading mode
    paper_simple_profit_mode: bool = True
    paper_dual_strategy_enabled: bool = False
    explosion_capture_mode: bool = True  # PRIMARY — capture daily premium explosions

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

    # Explosion capture — Jun 25 +₹66K profile: micro locks, trails, 12pt standard target
    explosion_min_velocity_3s: float = 2.0
    explosion_min_velocity_9s: float = 3.0
    explosion_early_velocity_3s: float = 3.0
    explosion_early_volume_surge: float = 1.5
    explosion_scan_range: int = 800
    explosion_target_elite: float = 25.0
    explosion_target_standard: float = 12.0
    explosion_micro_target_points: float = 3.0
    explosion_trail_arm_points: float = 4.0
    explosion_trail_keep_ratio: float = 0.65
    explosion_trail_step_points: float = 3.5
    explosion_trail_tight_arm: float = 12.0
    explosion_trail_tight_points: float = 5.0
    explosion_initial_stop_points: float = 4.0
    explosion_stop_min_hold_seconds: int = 15
    explosion_no_progress_seconds: int = 90
    explosion_reentry_cooldown_seconds: int = 120
    explosion_emergency_cooldown_seconds: int = 300

    # Symbol / instrument cooldown — stop same-strike churn after losses
    symbol_loss_cooldown_seconds: int = 180
    symbol_emergency_cooldown_seconds: int = 300
    symbol_streak_cooldown_seconds: int = 600
    reentry_score_penalty_per_loss: int = 5
    instrument_loss_cooldown_seconds: int = 300
    instrument_micro_win_cooldown_seconds: int = 180
    instrument_win_cooldown_seconds: int = 90
    instrument_max_entries_per_day: int = 3
    counter_breadth_min_score: int = 70

    # Controlled trading — pre-trade backtest + fewer entries
    controlled_trading_enabled: bool = True
    controlled_max_trades_per_day: int = 12
    min_seconds_between_entries: int = 120
    pretrade_min_rank_score: float = 55.0
    pretrade_min_symbol_trades_for_stats: int = 3
    pretrade_block_symbol_pf_below: float = 0.5
    pretrade_block_symbol_net_inr_below: float = -15_000.0
    pretrade_similar_side_lookback: int = 5
    pretrade_similar_side_min_trades: int = 3
    pretrade_block_similar_pf_below: float = 0.4
    index_selection_pf_bonus: float = 12.0

    # Chart alignment — CE/PE must match index candle direction
    chart_alignment_enabled: bool = True
    chart_min_trend_strength: float = 25.0
    chart_min_momentum_pct: float = 0.04
    chart_override_min_score: float = 75
    chart_alignment_rank_bonus: float = 10.0

    # Execution-time chart — fresh Upstox fetch right before order
    execution_chart_gate_enabled: bool = True
    execution_chart_force_upstox_refresh: bool = True
    execution_chart_premium_check_enabled: bool = True
    execution_chart_min_premium_momentum_pct: float = -0.35
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

    # Entries from 9:15 IST; open caution until 9:45 on chop days
    entry_earliest_hour: int = 9
    entry_earliest_minute: int = 15
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
    daily_loss_stop_inr: float = 30_000.0
    daily_max_trades_chop: int = 20
    daily_max_trades_pre10_chop: int = 5
    pre10_chop_min_rank_score: float = 60.0
    loss_streak_pause_count: int = 3
    loss_streak_pause_seconds: int = 1200
    chop_lots_high: int = 40
    chop_lots_mid: int = 20
    chop_lots_min_rank: float = 48.0
    chop_lots_high_min_rank: float = 55.0
    momentum_bypass_velocity_pct: float = 2.5
    momentum_bypass_volume_surge: float = 1.4
    momentum_bypass_explosion_score: float = 48.0
    momentum_rally_start_hour: int = 11
    momentum_rally_start_minute: int = 0
    momentum_rally_end_hour: int = 13
    momentum_rally_end_minute: int = 45
    runner_trail_keep_ratio: float = 0.38
    runner_micro_giveback_points: float = 4.0
    runner_min_best_points: float = 5.0

    # Option premium (LTP) band for entries and scanners
    min_option_premium_inr: float = 25.0
    max_option_premium_inr: float = 175.0

    # Jun 25 profile — hold winners longer for 2.5+ profit factor
    enhanced_micro_target_points: float = 4.0
    enhanced_velocity_threshold: float = 1.2
    enhanced_tqs_entry: int = 50
    runner_alignment_override_score: int = 82
    rapid_scalp_mode_enabled: bool = False
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
    per_trade_capital_pct: float = 0.85
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
    per_trade_risk_pct: float = 0.85
    max_exposure_pct: float = 0.85
    position_sl_cap_pct: float = 0.08
    position_tp_target_pct: float = 0.12
    emergency_stop_enabled: bool = False
    emergency_stop_inr: float = 20_000
    emergency_stop_scale_with_position: bool = False
    scalp_stop_points: float = 3.0
    scalp_stop_min_points: float = 2.5
    scalp_stop_min_hold_seconds: int = 30
    scalp_trail_arm_points: float = 4.5
    scalp_trail_keep_ratio: float = 0.50
    scalp_trail_step_points: float = 3.0
    scalp_trail_tight_arm: float = 10.0
    scalp_trail_tight_points: float = 4.0
    scalp_micro_giveback_points: float = 3.0
    scalp_no_progress_seconds: int = 150

    # Daily target — Jun 25 milestone profile
    daily_profit_target_inr: float = 44_000
    daily_profit_trail_inr: float = 5_000  # legacy; unused when stage locks enabled
    daily_profit_stage_locks_enabled: bool = True
    daily_profit_stage_pcts_csv: str = "0.55,0.88,1.12"  # env: DAILY_PROFIT_STAGE_PCTS

    def daily_profit_stage_pcts(self) -> list[float]:
        return [float(x.strip()) for x in self.daily_profit_stage_pcts_csv.split(",") if x.strip()]

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
