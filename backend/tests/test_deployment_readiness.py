"""Deployment readiness must be fast, truthful, and share execution state."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.schemas import AutoTraderState
from app.routers.health import deployment_readiness


def test_readiness_uses_cached_snapshot_and_shared_risk_engine():
    fast_snapshot = AsyncMock(return_value=SimpleNamespace(snapshots={}))
    shared_risk = SimpleNamespace(safe_mode=False)
    milestone = {
        "readyForLiveMilestone": True,
        "message": "Validated",
    }

    with (
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
        patch("app.routers.health.get_market_phase", return_value="CLOSED"),
        patch("app.routers.health.rate_limit_active", return_value=False),
        patch(
            "app.routers.health.rate_limit_cooldown_remaining",
            return_value=0.0,
        ),
        patch(
            "app.routers.health.ws_status",
            return_value={"enabled": False, "connected": False},
        ),
        patch(
            "app.engines.auto_trader.get_risk_engine",
            return_value=shared_risk,
        ) as risk_getter,
        patch(
            "app.engines.auto_trader.get_state",
            return_value=AutoTraderState(),
        ),
        patch(
            "app.loop_watchdog.watchdog_status",
            return_value={"enabled": False},
        ),
        patch(
            "app.routers.market.get_multi_snapshot_fast",
            new=fast_snapshot,
        ),
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

    fast_snapshot.assert_awaited_once_with(overlay_ws=False)
    risk_getter.assert_called_once_with()
    assert payload["checks"]["riskEngineOk"] is True
    assert payload["checks"]["eventLoopHealthy"] is True
    assert payload["checks"]["upstoxRateLimitClear"] is True
    assert payload["health"]["api"] == "ok"
