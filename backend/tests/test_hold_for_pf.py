"""Longer holds and delayed micro locks for 2.5+ profit factor."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.simple_profit import (
    _hold_profile_for_trade,
    evaluate_exit,
    get_session_targets,
)
from app.models.schemas import OptimizedProfile, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _trade(side: Side = Side.PUT, breadth: str = "BEARISH", best: float = 0.0) -> PaperTrade:
    return PaperTrade(
        id="h1",
        symbol="NIFTY",
        side=side,
        strike=23850,
        lots=40,
        entryPremium=40.0,
        openedAt=datetime.now(IST) - timedelta(minutes=2),
        strategyType=StrategyType.SCALP,
        bestPnlPoints=best,
        entryContext={"breadth": breadth},
    )


def _settings() -> MagicMock:
    s = MagicMock()
    s.emergency_stop_enabled = False
    s.scalp_stop_min_hold_seconds = 30
    s.scalp_trail_arm_points = 4.5
    s.scalp_trail_keep_ratio = 0.50
    s.scalp_trail_step_points = 3.0
    s.scalp_trail_tight_arm = 10.0
    s.scalp_trail_tight_points = 4.0
    s.runner_micro_giveback_points = 4.0
    s.runner_min_best_points = 5.0
    s.runner_trail_keep_ratio = 0.38
    s.scalp_micro_giveback_points = 3.0
    s.scalp_no_progress_seconds = 150
    s.scalp_micro_lock_min_best_points = 4.5
    s.scalp_min_hold_before_micro_lock_seconds = 90
    s.bullish_hold_enabled = True
    s.bullish_hold_trail_keep_ratio = 0.48
    s.bullish_hold_max_hold_multiplier = 1.6
    return s


@patch("app.engines.bullish_hold.get_settings")
def test_aligned_put_extends_max_hold(mock_bh_settings):
    mock_bh_settings.return_value.bullish_hold_enabled = True
    mock_bh_settings.return_value.bullish_hold_max_hold_multiplier = 1.6
    base = OptimizedProfile(
        targetPoints=8.0, stopPoints=3.0, microTargetPoints=4.0,
        maxHoldSeconds=300, sessionLabel="normal",
    )
    extended = _hold_profile_for_trade(_trade(Side.PUT, "BEARISH"), base)
    assert extended.maxHoldSeconds == 480
    assert extended.targetPoints > base.targetPoints


@patch("app.engines.simple_profit.get_settings")
def test_micro_lock_delayed_until_best_reaches_threshold(mock_settings):
    mock_settings.return_value = _settings()
    trade = _trade(Side.PUT, "BEARISH", best=3.0)
    profile = OptimizedProfile(
        targetPoints=8.0, stopPoints=3.0, microTargetPoints=4.0,
        maxHoldSeconds=300, sessionLabel="normal",
    )
    reason, _ = evaluate_exit(trade, 43.0, profile, lot_multiplier=65)
    assert reason is None


@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.bullish_hold.get_settings")
def test_trail_lock_after_meaningful_winner_giveback(mock_bh, mock_settings):
    mock_bh.return_value.bullish_hold_enabled = True
    mock_bh.return_value.bullish_hold_max_hold_multiplier = 1.6
    mock_settings.return_value = _settings()
    trade = _trade(Side.PUT, "BEARISH", best=8.0)
    profile = OptimizedProfile(
        targetPoints=10.0, stopPoints=3.0, microTargetPoints=4.0,
        maxHoldSeconds=300, sessionLabel="normal",
    )
    reason, pnl = evaluate_exit(trade, 44.5, profile, lot_multiplier=65)
    assert reason == "scalp_trail_sl"
    assert pnl > 0


def test_normal_session_hold_is_300s():
    with patch("app.engines.simple_profit.get_market_phase", return_value="OPEN"):
        with patch("app.engines.simple_profit.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 24, 10, 30)
            profile = get_session_targets()
    assert profile.maxHoldSeconds == 300
    assert profile.targetPoints == 8.0
