"""Readiness must require Frozen October profile when live is armed."""

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.schemas import AutoTraderState
from app.routers.health import deployment_readiness


def _live_ready_patches(settings):
    nifty = SimpleNamespace(dataAvailable=True, marketPhase="LIVE_MARKET")
    fast_snapshot = AsyncMock(
        return_value=SimpleNamespace(snapshots={"NIFTY": nifty, "SENSEX": nifty}),
    )
    return (
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
        patch(
            "app.routers.health.ws_status",
            return_value={"enabled": False, "connected": False},
        ),
        patch(
            "app.engines.auto_trader.get_risk_engine",
            return_value=SimpleNamespace(safe_mode=False),
        ),
        patch("app.engines.auto_trader.get_state", return_value=AutoTraderState()),
        patch("app.loop_watchdog.watchdog_status", return_value={"enabled": False}),
        patch("app.routers.market.get_multi_snapshot_fast", new=fast_snapshot),
        patch(
            "app.engines.performance_milestone.compute_milestone_stats",
            return_value={"readyForLiveMilestone": True, "message": "ok"},
        ),
        patch(
            "app.engines.worst_day_guard.worst_day_blocks_live",
            return_value=(False, "", {}),
        ),
        patch(
            "app.engines.live_paper_parity.live_paper_profile_ok",
            return_value=(True, []),
        ),
    )


def test_ready_for_live_false_when_frozen_october_not_ok():
    settings = SimpleNamespace(
        enable_live_trading=True,
        auto_trading_enabled=True,
        paper_trading=False,
        symbols=["NIFTY", "SENSEX"],
        per_trade_capital_pct=0.9,
        top_ftv_a_normal_max_move_pct=25,
        top_ftv_a_exceptional_max_move_pct=40,
        top_ftv_a_max_capital_pct=0.9,
        ftv_elite_top_only_enabled=False,
        top_moments_only_enabled=False,
        top_moments_min_grade="A",
        top_ftv_a_enabled=True,
        building_rip_ftv_enabled=True,
        building_rip_ftv_max_capital_pct=0.9,
        building_rip_ftv_force_max_lots=True,
        local_base_audit_week_enabled=False,
        peak_prediction_enabled=True,
    )
    with contextlib.ExitStack() as stack:
        for p in _live_ready_patches(settings):
            stack.enter_context(p)
        stack.enter_context(
            patch(
                "app.engines.october_frozen_profile.october_frozen_profile_ok",
                return_value=(False, ["october_frozen_profile_disabled"]),
            )
        )
        stack.enter_context(
            patch(
                "app.engines.october_frozen_profile.october_frozen_profile_summary",
                return_value={
                    "active": False,
                    "padEntryGuardEnabled": False,
                    "symmetricBestTradeCaptureEnabled": False,
                },
            )
        )
        payload = asyncio.run(deployment_readiness())

    assert payload["checks"]["frozenOctoberProfileOk"] is False
    assert payload["readyForLive"] is False
    assert any("Frozen October" in s for s in payload["armLiveSteps"])


def test_ready_for_live_true_when_frozen_and_live_paper_ok():
    settings = SimpleNamespace(
        enable_live_trading=True,
        auto_trading_enabled=True,
        paper_trading=False,
        symbols=["NIFTY", "SENSEX"],
        per_trade_capital_pct=0.9,
        top_ftv_a_normal_max_move_pct=25,
        top_ftv_a_exceptional_max_move_pct=40,
        top_ftv_a_max_capital_pct=0.9,
        ftv_elite_top_only_enabled=False,
        top_moments_only_enabled=False,
        top_moments_min_grade="A",
        top_ftv_a_enabled=True,
        building_rip_ftv_enabled=True,
        building_rip_ftv_max_capital_pct=0.9,
        building_rip_ftv_force_max_lots=True,
        local_base_audit_week_enabled=False,
        peak_prediction_enabled=True,
    )
    with contextlib.ExitStack() as stack:
        for p in _live_ready_patches(settings):
            stack.enter_context(p)
        stack.enter_context(
            patch(
                "app.engines.october_frozen_profile.october_frozen_profile_ok",
                return_value=(True, []),
            )
        )
        stack.enter_context(
            patch(
                "app.engines.october_frozen_profile.october_frozen_profile_summary",
                return_value={
                    "active": True,
                    "padEntryGuardEnabled": True,
                    "symmetricBestTradeCaptureEnabled": True,
                },
            )
        )
        payload = asyncio.run(deployment_readiness())

    assert payload["checks"]["frozenOctoberProfileOk"] is True
    assert payload["checks"]["padEntryGuardEnabled"] is True
    assert payload["readyForLive"] is True
