"""₹10k live overlay and milestone bypass for small-cap go-live."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import evaluate_explosion_exit
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType
from app.routers.health import deployment_readiness

IST = ZoneInfo("Asia/Kolkata")


ROOT = Path(__file__).resolve().parents[2]


def _overlay_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / "deploy/env.live-10k.overlay").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_live_10k_overlay_scales_capital_and_risk():
    env = _overlay_values()
    assert env["FALLBACK_CAPITAL_INR"] == "10000"
    assert env["MAX_SIZING_CAPITAL_INR"] == "10000"
    assert env["USE_UPSTOX_CAPITAL_FOR_SIZING"] == "true"
    assert env["LIVE_MILESTONE_REQUIRED"] == "false"
    assert env["DAILY_LOSS_STOP_INR"] == "1000"
    assert env["EMERGENCY_STOP_ENABLED"] == "false"
    assert env["EMERGENCY_STOP_INR"] == "1000"
    assert env["LIVE_HOLD_TO_STRUCTURAL_SL"] == "true"
    assert env["MAX_RISK_PER_TRADE_INR"] == "200"
    assert env["EXPLOSION_PER_TRADE_MAX_LOSS_INR"] == "0"
    assert env["EXPLOSION_EXCEPTIONAL_PER_TRADE_MAX_LOSS_INR"] == "0"
    assert env["INDEX_CONFIRMED_FTV_PER_TRADE_MAX_LOSS_INR"] == "0"
    assert env["SESSION_LARGE_LOSS_PAUSE_INR"] == "400"
    assert env["ENABLE_LIVE_TRADING"] == "false"


def test_readiness_skips_milestone_when_not_required():
    nifty = SimpleNamespace(dataAvailable=True, marketPhase="LIVE_MARKET")
    fast_snapshot = AsyncMock(
        return_value=SimpleNamespace(snapshots={"NIFTY": nifty, "SENSEX": nifty}),
    )
    shared_risk = SimpleNamespace(safe_mode=False)
    milestone = {
        "readyForLiveMilestone": False,
        "message": "Batch 1 · 12/50 toward review",
    }
    settings = SimpleNamespace(
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_milestone_required=False,
        paper_trading=False,
        symbols=["NIFTY", "SENSEX"],
        per_trade_capital_pct=0.9,
        top_ftv_a_normal_max_move_pct=25,
        top_ftv_a_exceptional_max_move_pct=40,
        top_ftv_a_max_capital_pct=0.9,
    )

    with (
        patch("app.routers.health.get_settings", return_value=settings),
        patch(
            "app.routers.health.get_daily_token_status",
            new=AsyncMock(return_value={"validToday": True}),
        ),
        patch(
            "app.routers.health.trade_store.check_store_health",
            return_value={
                "storeDir": "/tmp/trades",
                "logFile": "/tmp/trades/events.jsonl",
                "logSizeBytes": 0,
                "checks": {"healthy": True},
            },
        ),
        patch(
            "app.routers.health.trade_store.count_today_trades",
            return_value={"open": 0, "closed": 0, "total": 0},
        ),
        patch("app.routers.health.get_market_phase", return_value="LIVE_MARKET"),
        patch("app.routers.health.rate_limit_active", return_value=False),
        patch("app.routers.health.rate_limit_cooldown_remaining", return_value=0.0),
        patch("app.routers.health.ws_status", return_value={"enabled": False, "connected": False}),
        patch("app.engines.auto_trader.get_risk_engine", return_value=shared_risk),
        patch("app.engines.auto_trader.get_state", return_value=AutoTraderState()),
        patch("app.loop_watchdog.watchdog_status", return_value={"enabled": False}),
        patch("app.routers.market.get_multi_snapshot_fast", new=fast_snapshot),
        patch(
            "app.engines.performance_milestone.compute_milestone_stats",
            return_value=milestone,
        ),
        patch(
            "app.engines.worst_day_guard.worst_day_blocks_live",
            return_value=(False, "", {}),
        ),
    ):
        payload = asyncio.run(deployment_readiness())

    assert payload["checks"]["milestoneRequired"] is False
    assert payload["checks"]["milestonePassed"] is True
    assert payload["readyForLive"] is True


def test_live_hold_skips_inr_force_stop_and_rides_to_adaptive_sl():
    """Live + hold_to_sl: no INR cap — exit only at structural adaptive SL."""
    from app.config import get_settings

    s = get_settings()
    trade = PaperTrade(
        id="live1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24500.0,
        entryPremium=50.0,
        currentPremium=48.0,
        lots=2,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=120),
        bestPnlPoints=0.0,
        entryContext={"exitPlan": {"stopPoints": 6.0, "adaptiveStop": True}},
    )
    with (
        patch.object(s, "enable_live_trading", True),
        patch.object(s, "live_hold_to_structural_sl", True),
        patch.object(s, "explosion_failed_launch_exit_enabled", True),
        patch.object(s, "explosion_never_green_stop_enabled", True),
        patch.object(s, "explosion_per_trade_max_loss_inr", 100.0),
        patch.object(s, "explosion_exceptional_per_trade_max_loss_inr", 200.0),
        patch.object(s, "emergency_stop_enabled", True),
        patch.object(s, "emergency_stop_inr", 1000.0),
        patch.object(s, "explosion_peak_fade_lock_enabled", False),
        patch.object(s, "explosion_peak_capture_enabled", False),
        patch.object(s, "explosion_no_progress_enabled", False),
    ):
        reason, _ = evaluate_explosion_exit(trade, 48.0, "ELITE", 65, live_velocity_3s=-1.0)
    assert reason not in (
        "explosion_never_green_stop",
        "explosion_failed_launch",
        "explosion_per_trade_risk_cap",
        "explosion_emergency_stop",
    )

    with (
        patch.object(s, "enable_live_trading", True),
        patch.object(s, "live_hold_to_structural_sl", True),
        patch.object(s, "explosion_peak_fade_lock_enabled", False),
        patch.object(s, "explosion_peak_capture_enabled", False),
        patch.object(s, "explosion_no_progress_enabled", False),
    ):
        reason2, _ = evaluate_explosion_exit(trade, 43.0, "ELITE", 65, live_velocity_3s=-1.0)
    assert reason2 in ("adaptive_stop_loss", "explosion_stop_loss")
