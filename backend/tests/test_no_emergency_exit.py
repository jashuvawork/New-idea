"""Per-trade INR emergency stops disabled — point stops and trails only."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.simple_profit import evaluate_exit
from app.models.schemas import OptimizedProfile, PaperTrade, Side, StrategyType


def _trade(strategy: StrategyType = StrategyType.SCALP) -> PaperTrade:
    return PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24000,
        lots=40,
        entryPremium=100.0,
        currentPremium=50.0,
        openedAt=datetime.now(timezone.utc),
        strategyType=strategy,
        bestPnlPoints=0.0,
    )


@patch("app.engines.simple_profit.get_settings")
def test_scalp_stop_fires_with_ist_opened_at(mock_settings):
    from zoneinfo import ZoneInfo

    settings = MagicMock()
    settings.emergency_stop_enabled = False
    settings.scalp_stop_min_hold_seconds = 30
    settings.runner_micro_giveback_points = 2.5
    settings.runner_min_best_points = 6.0
    settings.runner_trail_keep_ratio = 0.45
    mock_settings.return_value = settings

    IST = ZoneInfo("Asia/Kolkata")
    trade = PaperTrade(
        id="t2",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850,
        lots=64,
        entryPremium=40.55,
        openedAt=datetime.now(IST) - timedelta(minutes=5),
        strategyType=StrategyType.SCALP,
        bestPnlPoints=1.35,
    )
    profile = OptimizedProfile(
        targetPoints=5.4, stopPoints=2.16, microTargetPoints=1.3,
        maxHoldSeconds=300, sessionLabel="test",
    )
    reason, _ = evaluate_exit(trade, 37.0, profile, lot_multiplier=65)
    assert reason == "simple_stop_loss"


@patch("app.engines.simple_profit.get_settings")
def test_scalp_skips_emergency_inr_stop(mock_settings):
    settings = MagicMock()
    settings.emergency_stop_enabled = False
    settings.emergency_stop_inr = 20_000
    settings.scalp_stop_min_hold_seconds = 0
    settings.runner_micro_giveback_points = 2.5
    settings.runner_min_best_points = 6.0
    settings.runner_trail_keep_ratio = 0.45
    mock_settings.return_value = settings

    profile = OptimizedProfile(
        targetPoints=8.0, stopPoints=3.0, microTargetPoints=2.5,
        maxHoldSeconds=300, sessionLabel="test",
    )
    reason, _ = evaluate_exit(_trade(), 20.0, profile, lot_multiplier=65)
    assert reason != "simple_emergency_inr_stop"


@patch("app.engines.explosion_profit.get_settings")
def test_explosion_skips_emergency_inr_stop(mock_settings):
    settings = MagicMock()
    settings.emergency_stop_enabled = False
    settings.emergency_stop_inr = 20_000
    settings.explosion_stop_min_hold_seconds = 0
    settings.explosion_initial_stop_points = 4.0
    settings.runner_trail_keep_ratio = 0.45
    settings.runner_min_best_points = 6.0
    settings.explosion_trail_keep_ratio = 0.65
    settings.explosion_trail_arm_points = 4.0
    settings.explosion_trail_tight_arm = 12.0
    settings.explosion_trail_tight_points = 3.0
    mock_settings.return_value = settings

    reason, _ = evaluate_explosion_exit(_trade(StrategyType.EXPLOSIVE), 20.0, lot_multiplier=65)
    assert reason != "explosion_emergency_stop"
