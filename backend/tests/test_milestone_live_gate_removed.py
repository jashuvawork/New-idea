"""Milestone must not block live deployment readiness."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.schemas import AutoTraderState
from app.routers.health import deployment_readiness


def test_milestone_does_not_block_ready_for_live():
    milestone = {
        "readyForLiveMilestone": False,
        "message": "50 more closed trades needed for batch 1 review",
        "tradeCount": 0,
        "targetTrades": 50,
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
        patch("app.routers.health.get_market_phase", return_value="LIVE_MARKET"),
        patch("app.routers.health.rate_limit_active", return_value=False),
        patch(
            "app.routers.health.rate_limit_cooldown_remaining",
            return_value=0.0,
        ),
        patch(
            "app.routers.health.ws_status",
            return_value={"enabled": True, "connected": True, "streamStale": False},
        ),
        patch(
            "app.engines.auto_trader.get_risk_engine",
            return_value=SimpleNamespace(safe_mode=False),
        ),
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
            new=AsyncMock(
                return_value=SimpleNamespace(
                    snapshots={
                        "NIFTY": SimpleNamespace(
                            dataAvailable=True,
                            marketPhase=SimpleNamespace(value="LIVE_MARKET"),
                        )
                    }
                ),
            ),
        ),
        patch(
            "app.engines.performance_milestone.compute_milestone_stats",
            return_value=milestone,
        ),
        patch(
            "app.engines.worst_day_guard.worst_day_blocks_live",
            return_value=(False, "", {}),
        ),
        patch(
            "app.routers.health.get_settings",
            return_value=SimpleNamespace(
                symbols=["NIFTY", "SENSEX"],
                enable_live_trading=True,
                auto_trading_enabled=True,
                paper_trading=False,
                per_trade_capital_pct=0.9,
                top_ftv_a_normal_max_move_pct=45.0,
                top_ftv_a_exceptional_max_move_pct=65.0,
                top_ftv_a_max_capital_pct=0.9,
                ftv_elite_top_only_enabled=True,
                top_moments_only_enabled=True,
                top_moments_min_grade="A",
                top_ftv_a_enabled=True,
                local_base_audit_week_enabled=False,
                peak_prediction_enabled=True,
                building_rip_ftv_enabled=True,
                building_rip_ftv_max_capital_pct=0.9,
                building_rip_ftv_force_max_lots=True,
            ),
        ),
    ):
        payload = asyncio.run(deployment_readiness())

    assert payload["checks"]["milestoneRequired"] is False
    assert payload["checks"]["milestonePassed"] is True
    assert payload["checks"]["milestoneAdvisoryOnly"] is True
    assert payload["readyForLive"] is True
    assert not any(
        "50 more closed trades" in step
        for step in payload.get("armLiveSteps") or []
    )
