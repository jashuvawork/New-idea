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

    # Data cadence — 1s poll for faster SL/exits; throttle via upstox_min_request_interval_ms
    market_poll_seconds: int = 1
    snapshot_cache_seconds: int = 1
    background_market_monitor_enabled: bool = True

    # Upstox WebSocket real-time feed + SSE push to UI
    upstox_ws_enabled: bool = True
    upstox_ws_mode: str = "ltpc"  # ltpc | full | full_d30 | option_greeks
    upstox_ws_reconnect_seconds: int = 5
    upstox_ws_resubscribe_seconds: int = 45
    tick_snapshot_seconds: int = 1  # snapshot cache when WS feed is active
    market_poll_seconds_ws: int = 1  # background monitor when WS active
    sse_enabled: bool = True
    sse_heartbeat_seconds: int = 15

    # Upstox rate limiting / caching
    upstox_min_request_interval_ms: int = 250
    upstox_request_retries: int = 4
    upstox_rate_limit_cooldown_seconds: int = 45
    upstox_chain_cache_seconds: int = 20
    upstox_ltp_cache_seconds: int = 5
    upstox_expiries_cache_seconds: int = 600
    upstox_funds_cache_seconds: int = 90
    upstox_candles_cache_seconds: int = 60
    upstox_max_expiry_probes: int = 2
    capital_refresh_seconds: int = 90
    fetch_constituents_in_snapshot: bool = False

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

    # Explosion capture tuning
    explosion_min_velocity_3s: float = 2.2
    explosion_min_velocity_9s: float = 3.0
    explosion_early_velocity_3s: float = 3.5
    explosion_early_volume_surge: float = 1.8
    explosion_scan_range: int = 800
    explosion_target_elite: float = 25.0
    explosion_target_standard: float = 7.0
    explosion_micro_target_points: float = 3.0
    explosion_trail_arm_points: float = 3.0
    explosion_trail_keep_ratio: float = 0.65
    explosion_trail_step_points: float = 3.5
    explosion_trail_tight_arm: float = 12.0
    explosion_trail_tight_points: float = 5.0
    explosion_initial_stop_points: float = 2.5
    explosion_stop_min_hold_seconds: int = 5
    explosion_no_progress_seconds: int = 120
    explosion_reentry_cooldown_seconds: int = 180
    explosion_emergency_cooldown_seconds: int = 300

    # Per-symbol cooldown after losses — stops NIFTY re-entry churn
    symbol_loss_cooldown_seconds: int = 180
    symbol_emergency_cooldown_seconds: int = 360
    symbol_streak_cooldown_seconds: int = 600
    reentry_score_penalty_per_loss: int = 6
    recent_win_window_seconds: int = 900
    recent_win_rank_bonus: float = 15.0
    calibration_block_min_losses: int = 5

    # Earliest new entries (IST) — skip first minute after 9:15 open
    entry_earliest_hour: int = 9
    entry_earliest_minute: int = 20
    # Stricter explosion gates until this IST time (opening range forming)
    open_caution_until_hour: int = 9
    open_caution_until_minute: int = 25
    open_caution_min_explosion_score: int = 52
    open_caution_score_bonus: int = 3

    # Option premium (LTP) band for entries and scanners
    min_option_premium_inr: float = 25.0
    max_option_premium_inr: float = 175.0

    # Enhanced scalping (more powerful than base spec)
    enhanced_micro_target_points: float = 2.0  # bank smaller wins faster
    enhanced_velocity_threshold: float = 1.25
    enhanced_tqs_entry: int = 50
    runner_alignment_override_score: int = 82
    adaptive_target_enabled: bool = True
    tick_fusion_enabled: bool = True  # multi-timeframe momentum fusion

    # Capital / risk — smaller book per trade; hard cap on lots and INR loss
    fallback_capital_inr: float = 200_000
    max_sizing_capital_inr: float = 200_000
    per_trade_capital_pct: float = 0.55
    aggressive_lot_sizing: bool = True
    aggressive_min_tqs: int = 48
    aggressive_min_explosion_score: int = 52
    explosion_confirmed_min_score: int = 55
    explosion_max_lots: int = 25
    aggressive_min_swing_confidence: int = 65
    aggressive_max_open_scalps: int = 1
    max_lots_per_trade: int = 35
    min_lots_per_trade: int = 1
    max_risk_per_trade_inr: float = 200_000
    min_per_trade_risk_inr: float = 3_000
    per_trade_risk_pct: float = 0.55
    max_exposure_pct: float = 0.55
    position_sl_cap_pct: float = 0.06
    position_tp_target_pct: float = 0.10
    emergency_stop_inr: float = 12_000
    emergency_stop_scale_with_position: bool = True
    scalp_stop_points: float = 2.5
    scalp_stop_min_hold_seconds: int = 10

    # Daily session targets — ₹22K min milestone; staged locks at % of capital (no upside cap)
    daily_profit_target_inr: float = 22_000  # minimum milestone only — does not stop entries
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
