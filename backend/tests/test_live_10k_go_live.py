"""₹10k live overlay and milestone bypass for small-cap go-live."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.schemas import AutoTraderState
from app.routers.health import deployment_readiness


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
    assert env["EMERGENCY_STOP_INR"] == "1000"
    assert env["MAX_RISK_PER_TRADE_INR"] == "200"
    assert env["EXPLOSION_PER_TRADE_MAX_LOSS_INR"] == "100"
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
