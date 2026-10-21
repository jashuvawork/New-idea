"""Mega stage-ladder pullback exits — Oct 21 SENSEX 73400 PE giveback hole."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.moment_stage_trail import profit_ladder_floor

from tests.test_moment_stage_trail import _settings

IST = ZoneInfo("Asia/Kolkata")


def _oct21_sensex_73400(*, pnl_pts: float, seconds: int = 400, since_peak: int = 200):
    from app.models.schemas import PaperTrade, Side, StrategyType

    entry = 340.33
    return PaperTrade(
        id="03ed488f",
        symbol="SENSEX",
        side=Side.PUT,
        strike=73400.0,
        entryPremium=entry,
        currentPremium=entry + pnl_pts,
        lots=26,
        openedAt=datetime.now(IST) - timedelta(seconds=seconds),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=47.67,
        maxLtp=entry + 47.67,
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 800.0,
            "stageSize": 75.0,
            "tpRungLadder": True,
            "tpRungsPts": [28.0, 36.0, 75.0, 150.0, 225.0, 300.0, 375.0, 450.0, 525.0, 600.0, 675.0, 750.0, 800.0],
            "exitPlan": {
                "projectedMaxTp": 800.0,
                "stageSize": 75.0,
                "trailArmPoints": 28.21,
                "microTargetPoints": 27.0,
            },
        },
    )


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_mega_runner_unified_ladder_arms_at_14pct_gain(mock_ms, mock_s):
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _oct21_sensex_73400(pnl_pts=47.0)
    floor, layer = profit_ladder_floor(trade, 47.67, settings=s)
    assert layer == "peak_keep"
    assert floor == pytest.approx(47.67 * 0.75, rel=0.01)


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_oct21_73400_hole_take_banks_green_on_fast_pullback(mock_ms, mock_s, _mp):
    import app.engines.explosion_profit as ep

    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _oct21_sensex_73400(pnl_pts=10.7)
    with patch.object(ep, "_hold_seconds", return_value=400):
        with patch.object(ep, "_seconds_since_peak", return_value=200):
            reason, pnl_inr = evaluate_explosion_exit(
                trade, trade.currentPremium, "EXPLODING", 20, live_velocity_3s=-0.5,
            )
    assert reason in (
        "explosion_profit_ladder_peak_keep",
        "explosion_tp_rung_between_fade",
        "explosion_tp_rung_floor_hole",
        "explosion_tp_rung_floor",
    )
    assert pnl_inr > 0


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_oct21_73400_red_giveback_after_mega_peak(mock_ms, mock_s, _mp):
    import app.engines.explosion_profit as ep

    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _oct21_sensex_73400(pnl_pts=-16.3)
    with patch.object(ep, "_hold_seconds", return_value=400):
        with patch.object(ep, "_seconds_since_peak", return_value=200):
            reason, _ = evaluate_explosion_exit(
                trade, trade.currentPremium, "EXPLODING", 20, live_velocity_3s=-0.5,
            )
    assert reason in (
        "explosion_profit_ladder_peak_keep",
        "explosion_tp_rung_red_giveback",
        "explosion_stage_runner_red_giveback",
        "explosion_early_green_breakeven",
    )


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_oct21_73400_red_giveback_without_three_minute_peak_wait(mock_ms, mock_s, _mp):
    import app.engines.explosion_profit as ep

    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _oct21_sensex_73400(pnl_pts=-20.0)
    with patch.object(ep, "_hold_seconds", return_value=120):
        with patch.object(ep, "_seconds_since_peak", return_value=50):
            reason, _ = evaluate_explosion_exit(
                trade, trade.currentPremium, "EXPLODING", 20, live_velocity_3s=-1.0,
            )
    assert reason in (
        "explosion_stage_runner_red_giveback",
        "explosion_profit_ladder_peak_keep",
        "explosion_tp_rung_red_giveback",
        "explosion_runner_profit_guard",
    )


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_oct21_73400_holds_at_peak(mock_ms, mock_s, _mp):
    import app.engines.explosion_profit as ep

    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _oct21_sensex_73400(pnl_pts=47.67)
    with patch.object(ep, "_hold_seconds", return_value=400):
        with patch.object(ep, "_seconds_since_peak", return_value=30):
            reason, _ = evaluate_explosion_exit(
                trade, trade.currentPremium, "EXPLODING", 20, live_velocity_3s=1.0,
            )
    assert reason is None


def test_oct21_73400_falling_through_75_line_sells_before_three_minutes():
    """After the high, a falling print under the 75% line sells. A 12s dip holds."""
    from app.config import Settings
    from app.engines.explosion_profit import unified_profit_ladder_exit_reason

    s = Settings()
    entry = 340.33
    best = 47.67
    floor = round(best * 0.75, 2)
    under = floor - 8.0

    def _at(age: int, pnl: float, v3: float):
        trade = _oct21_sensex_73400(pnl_pts=pnl, seconds=400)
        trade.maxLtpAt = datetime.now(IST) - timedelta(seconds=age)
        with patch("app.config.get_settings", lambda: s), patch(
            "app.engines.explosion_profit.get_settings", lambda: s
        ), patch("app.engines.moment_stage_trail.get_settings", lambda: s):
            return unified_profit_ladder_exit_reason(
                trade, best=best, pnl_pts=pnl, hold_seconds=400, live_velocity_3s=v3,
            )

    assert _at(12, under, -1.0) is None
    assert _at(50, under, -1.0) == "explosion_profit_ladder_peak_keep"
    assert _at(50, under, 0.4) is None
    assert _at(50, -8.0, -1.0) == "explosion_profit_ladder_peak_keep"
