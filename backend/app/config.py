"""NexusQuant configuration — all settings from environment."""

from functools import lru_cache
from typing import Literal

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
    shadow_trade_all_signals: bool = True

    # Data cadence
    market_poll_seconds: int = 3
    snapshot_cache_seconds: int = 3
    background_market_monitor_enabled: bool = True

    # Trading mode
    paper_simple_profit_mode: bool = True
    paper_dual_strategy_enabled: bool = False
    explosion_capture_mode: bool = True  # PRIMARY — capture daily premium explosions

    # Explosion capture tuning
    explosion_min_velocity_3s: float = 2.0
    explosion_min_velocity_9s: float = 3.0
    explosion_scan_range: int = 800
    explosion_target_elite: float = 25.0
    explosion_target_standard: float = 12.0

    # Enhanced scalping (more powerful than base spec)
    enhanced_micro_target_points: float = 2.5  # faster micro lock vs 3.0 base
    enhanced_velocity_threshold: float = 1.8  # lower bar for quick scalps
    enhanced_tqs_entry: int = 68  # vs 72 base — more opportunities
    adaptive_target_enabled: bool = True
    tick_fusion_enabled: bool = True  # multi-timeframe momentum fusion

    # Capital / risk defaults
    default_capital_inr: float = 500_000
    max_risk_per_trade_inr: float = 12_000
    emergency_stop_inr: float = 18_000
    simple_max_lots: int = 14
    simple_target_lots: int = 10
    simple_min_lots: int = 6

    adaptive_exits_enabled: bool = True
    ml_exit_tuning_enabled: bool = True

    symbols: list[str] = ["NIFTY", "SENSEX", "BANKNIFTY"]

    # Persistence
    trade_store_dir: str = "/tmp/nexusquant/trades"
    daily_token_once: bool = True

    # Swing trading (multi-day paper holds)
    swing_trading_enabled: bool = True
    swing_max_hold_days: int = 5
    swing_target_pct: float = 30.0
    swing_stop_pct: float = 12.0
    swing_trail_arm_pct: float = 20.0
    swing_trail_keep: float = 0.70
    swing_min_lots: int = 4
    swing_target_lots: int = 8
    swing_max_open: int = 2
    swing_max_loss_inr: float = 25_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
