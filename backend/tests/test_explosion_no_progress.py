"""Explosion no-progress exit — skip/extend on bullish directional holds."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import ExplosionExitParams, evaluate_explosion_exit
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _trade(**ctx) -> PaperTrade:
    return PaperTrade(
        id="e1",
        symbol="SENSEX",
        side=Side.CALL,
        strike=77600,
        lots=50,
        entryPremium=40.0,
        currentPremium=40.0,
        openedAt=datetime.now(IST) - timedelta(seconds=120),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=1.0,
        entryContext=ctx,
    )


def _params() -> ExplosionExitParams:
    return ExplosionExitParams(
        stop_points=4.0,
        target_points=25.0,
        trail_arm_points=10.0,
        trail_keep_ratio=0.65,
        micro_target_points=3.0,
        adaptive_stop=True,
    )


def _settings():
    s = MagicMock()
    s.emergency_stop_enabled = False
    s.explosion_stop_min_hold_seconds = 0
    s.explosion_trail_tight_arm = 12.0
    s.explosion_trail_tight_points = 3.0
    s.explosion_trail_step_points = 2.0
    s.runner_trail_keep_ratio = 0.45
    s.runner_min_best_points = 6.0
    s.runner_micro_giveback_points = 2.5
    s.explosion_trail_keep_ratio = 0.65
    s.explosion_trail_arm_points = 10.0
    s.explosion_initial_stop_points = 4.0
    s.explosion_no_progress_enabled = True
    s.explosion_no_progress_seconds = 90
    s.explosion_no_progress_aligned_seconds = 420
    s.explosion_no_progress_skip_when_aligned = True
    s.bullish_hold_enabled = True
    return s


@patch("app.engines.explosion_profit.get_settings")
def test_no_progress_fires_without_alignment(mock_settings):
    mock_settings.return_value = _settings()
    trade = _trade(breadth="NEUTRAL")
    reason, _ = evaluate_explosion_exit(trade, 41.0, "ELITE", 20, params=_params())
    assert reason == "explosion_no_progress"


@patch("app.engines.explosion_profit.get_settings")
def test_no_progress_skipped_on_bullish_breadth_hold(mock_settings):
    mock_settings.return_value = _settings()
    trade = _trade(breadth="BULLISH")
    reason, _ = evaluate_explosion_exit(trade, 41.0, "ELITE", 20, params=_params())
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
def test_no_progress_skipped_on_bullish_chart(mock_settings):
    mock_settings.return_value = _settings()
    trade = _trade(executionChart={"indexChart": {"direction": "BULLISH"}})
    reason, _ = evaluate_explosion_exit(trade, 41.0, "ELITE", 20, params=_params())
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
def test_no_progress_extended_when_alignment_skip_disabled(mock_settings):
    s = _settings()
    s.explosion_no_progress_skip_when_aligned = False
    s.explosion_no_progress_aligned_seconds = 300
    mock_settings.return_value = s
    trade = _trade(breadth="BULLISH")
    trade.openedAt = datetime.now(IST) - timedelta(seconds=200)
    reason, _ = evaluate_explosion_exit(trade, 41.0, "ELITE", 20, params=_params())
    assert reason is None

    trade.openedAt = datetime.now(IST) - timedelta(seconds=310)
    reason, _ = evaluate_explosion_exit(trade, 41.0, "ELITE", 20, params=_params())
    assert reason == "explosion_no_progress"


@patch("app.engines.explosion_profit.get_settings")
def test_adaptive_stop_fires_before_no_progress_on_large_loss(mock_settings):
    mock_settings.return_value = _settings()
    trade = _trade(breadth="NEUTRAL", selectionScore=108.0)
    trade.openedAt = datetime.now(IST) - timedelta(seconds=135)
    trade.bestPnlPoints = 0.0
    reason, pnl = evaluate_explosion_exit(trade, 20.0, "EXPLODING", 65, params=_params())
    assert reason == "adaptive_stop_loss"
    assert pnl < 0
