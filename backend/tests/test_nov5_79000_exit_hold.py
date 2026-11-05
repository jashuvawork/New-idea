"""Nov 5 SENSEX 79000 CE — unified peak_keep must not clip a vertical PM mega runner early."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.explosion_profit import unified_profit_ladder_exit_reason
from app.engines.moment_stage_trail import profit_ladder_floor
from tests.test_moment_stage_trail import _settings

IST = ZoneInfo("Asia/Kolkata")


def _nov5_79000_trade(*, best: float, pnl_pts: float, since_peak: float):
    from app.models.schemas import PaperTrade, Side, StrategyType

    entry = 308.98
    opened = datetime(2026, 11, 5, 14, 28, 52, tzinfo=IST)
    peak_at = datetime.now(IST) - timedelta(seconds=since_peak)
    return PaperTrade(
        id="b9bd2809",
        symbol="SENSEX",
        side=Side.CALL,
        strike=79000.0,
        entryPremium=entry,
        currentPremium=entry + pnl_pts,
        lots=29,
        openedAt=opened,
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        maxLtpAt=peak_at,
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 1409.0,
            "stageSize": 75.0,
            "exitPlan": {
                "momentStageLadder": True,
                "projectedMaxTp": 1409.0,
                "stageSize": 75.0,
            },
        },
    )


@patch("app.engines.moment_stage_trail.get_settings")
def test_nov5_79000_shape_no_peak_keep_before_stage_one(mock_ms):
    s = _settings(
        unified_profit_ladder_min_hold_seconds=0,
        unified_profit_ladder_min_seconds_after_peak=0,
        unified_profit_ladder_fall_min_hold_seconds=0,
        unified_profit_ladder_fall_min_seconds_after_peak=45.0,
    )
    mock_ms.return_value = s
    best = 65.52
    trade = _nov5_79000_trade(best=best, pnl_pts=49.0, since_peak=46.0)
    assert profit_ladder_floor(trade, best, settings=s) is None


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_nov5_79000_shape_no_ladder_exit_46s_after_peak(mock_ms, mock_ep):
    """Production exited at ~46s after maxLtp with peak_keep — should hold for stage rip."""
    s = _settings(
        unified_profit_ladder_min_hold_seconds=60,
        unified_profit_ladder_fall_min_hold_seconds=60,
        unified_profit_ladder_fall_min_seconds_after_peak=45.0,
        stage_runner_pre_stage_fall_min_seconds_after_peak=120.0,
    )
    mock_ms.return_value = s
    mock_ep.return_value = s
    best = 65.52
    trade = _nov5_79000_trade(best=best, pnl_pts=49.14, since_peak=46.0)
    with patch(
        "app.engines.explosion_profit._hold_seconds", return_value=208.0,
    ), patch(
        "app.engines.explosion_profit._seconds_since_peak", return_value=46.0,
    ):
        reason = unified_profit_ladder_exit_reason(
            trade,
            best=best,
            pnl_pts=49.14,
            hold_seconds=208.0,
            live_velocity_3s=-0.5,
        )
    assert reason is None
