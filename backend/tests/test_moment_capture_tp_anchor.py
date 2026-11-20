"""TP anchor — hold maxProfitCapture trades to computed TP before scratch exits."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_profit import (
    runner_profit_guard_exit_reason,
    stage_runner_mega_pullback_exit_reason,
)
from app.engines.moment_capture_tp_anchor import (
    compute_moment_capture_tp_anchor_pts,
    moment_capture_anchor_hold_active,
)
from app.engines.tp_rung_ladder import tp_rung_exit_reason
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")
SIDES = [Side.CALL, Side.PUT]


def test_nov20_25600_anchor_is_two_x_points():
    s = Settings()
    anchor = compute_moment_capture_tp_anchor_pts(
        entry_premium=88.9,
        projected_max_tp=359.0,
        stage_size=75.0,
        plan_target_pts=46.16,
        settings=s,
    )
    assert anchor == pytest.approx(88.9, rel=0.01)


def test_nov17_82100_anchor_blocks_early_between_rung_best():
    s = Settings()
    anchor = compute_moment_capture_tp_anchor_pts(
        entry_premium=582.05,
        projected_max_tp=800.0,
        stage_size=75.0,
        plan_target_pts=80.0,
        settings=s,
    )
    assert anchor > 48.65
    assert anchor == pytest.approx(100.0, rel=0.05)


@pytest.mark.parametrize("side", SIDES)
def test_anchor_hold_suppresses_runner_guard_nov20_shape(side):
    s = Settings()
    entry, best, anchor = 88.9, 12.6, 88.9
    trade = PaperTrade(
        id=f"anc-{side.value}",
        symbol="NIFTY",
        side=side,
        strike=25600.0,
        entryPremium=entry,
        currentPremium=entry + 3.7,
        lots=5,
        openedAt=datetime.now(IST) - timedelta(minutes=20),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "momentCaptureTpAnchorPts": anchor,
            "projectedMaxTp": 359.0,
            "stageSize": 75.0,
            "runnerGuardBelowSince": (
                datetime.now(IST) - timedelta(seconds=s.runner_profit_guard_confirm_seconds + 5)
            ).isoformat(),
        },
    )
    assert moment_capture_anchor_hold_active(trade, best, settings=s)
    with patch("app.engines.explosion_profit.get_settings", return_value=s):
        assert runner_profit_guard_exit_reason(
            trade, pnl_pts=3.7, live_velocity_3s=0.0,
        ) is None


@pytest.mark.parametrize("side", SIDES)
def test_anchor_hold_defers_stage_hole(side):
    s = Settings()
    trade = PaperTrade(
        id=f"hole-{side.value}",
        symbol="SENSEX",
        side=side,
        strike=82600.0,
        entryPremium=446.95,
        currentPremium=446.95 + 6.8,
        lots=2,
        openedAt=datetime.now(IST) - timedelta(seconds=600),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=32.35,
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "momentCaptureTpAnchorPts": 100.0,
            "projectedMaxTp": 800.0,
            "stageSize": 75.0,
            "exitPlan": {"projectedMaxTp": 800.0, "stageSize": 75.0},
        },
    )
    with patch("app.engines.explosion_profit.get_settings", return_value=s), patch(
        "app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True
    ), patch("app.engines.moment_stage_trail.get_settings", return_value=s):
        assert stage_runner_mega_pullback_exit_reason(
            trade, best=32.35, pnl_pts=6.8, hold_seconds=600, live_velocity_3s=-0.5,
        ) is None


@pytest.mark.parametrize("side", SIDES)
def test_scoped_anchor_allows_runner_guard_near_hod_before_rung_armed(side):
    """Nov20 25700: +12pt best at HOD — runner guard not deferred until rung armed."""
    s = Settings()
    anchor = 141.25
    trade = PaperTrade(
        id=f"scoped-{side.value}",
        symbol="NIFTY",
        side=side,
        strike=25700.0,
        entryPremium=140.65,
        currentPremium=140.65 + 3.7,
        lots=3,
        openedAt=datetime.now(IST) - timedelta(minutes=25),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=12.05,
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "momentCaptureTpAnchorPts": anchor,
            "momentCaptureAnchorNearIndexExtreme": True,
            "runnerGuardBelowSince": (
                datetime.now(IST) - timedelta(seconds=s.runner_profit_guard_confirm_seconds + 5)
            ).isoformat(),
        },
    )
    assert moment_capture_anchor_hold_active(trade, 12.05, settings=s) is False
    assert moment_capture_anchor_hold_active(trade, 27.9, settings=s) is False
    assert moment_capture_anchor_hold_active(trade, 30.0, settings=s) is True