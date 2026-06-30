"""Ratcheting trail floor and scalp trailing SL/TP exits."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.capital_allocator import tune_exit_plan_for_position
from app.engines.simple_profit import evaluate_exit, get_session_targets
from app.engines.trail_engine import ratcheting_trail_floor
from app.models.schemas import OptimizedProfile, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _scalp_trade(
    entry: float = 40.0,
    *,
    best: float = 0.0,
    opened_minutes_ago: int = 5,
    entry_context: dict | None = None,
) -> PaperTrade:
    return PaperTrade(
        id="trail1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850,
        lots=40,
        entryPremium=entry,
        openedAt=datetime.now(IST) - timedelta(minutes=opened_minutes_ago),
        strategyType=StrategyType.SCALP,
        bestPnlPoints=best,
        entryContext=entry_context or {},
    )


def _scalp_settings() -> MagicMock:
    settings = MagicMock()
    settings.emergency_stop_enabled = False
    settings.scalp_stop_min_hold_seconds = 30
    settings.scalp_trail_arm_points = 3.0
    settings.scalp_trail_keep_ratio = 0.60
    settings.scalp_trail_step_points = 2.0
    settings.scalp_trail_tight_arm = 8.0
    settings.scalp_trail_tight_points = 3.0
    settings.runner_micro_giveback_points = 2.5
    settings.runner_min_best_points = 6.0
    settings.runner_trail_keep_ratio = 0.45
    settings.scalp_micro_giveback_points = 1.5
    settings.scalp_no_progress_seconds = 90
    return settings


def test_ratchet_floor_arms_after_min_profit():
    trade = _scalp_trade()
    floor = ratcheting_trail_floor(
        trade,
        2.5,
        arm_points=3.0,
        keep_ratio=0.6,
        step_points=2.0,
    )
    assert floor is None
    assert trade.entryContext.get("trailFloorPts") is None


def test_ratchet_floor_uses_max_of_ratio_and_step():
    trade = _scalp_trade()
    floor = ratcheting_trail_floor(
        trade,
        8.0,
        arm_points=3.0,
        keep_ratio=0.6,
        step_points=2.0,
        floor_key="scalpTrailFloorPts",
        best_key="scalpTrailBestPts",
    )
    assert floor == 6.0
    assert trade.entryContext["scalpTrailFloorPts"] == 6.0


def test_ratchet_floor_only_moves_up():
    trade = _scalp_trade(entry_context={"scalpTrailFloorPts": 5.5})
    floor = ratcheting_trail_floor(
        trade,
        6.0,
        arm_points=3.0,
        keep_ratio=0.6,
        step_points=2.0,
        floor_key="scalpTrailFloorPts",
        best_key="scalpTrailBestPts",
    )
    assert floor == 5.5


def test_tight_trail_tightens_when_step_is_wider_than_tight_band():
    trade = _scalp_trade()
    floor = ratcheting_trail_floor(
        trade,
        10.0,
        arm_points=3.0,
        keep_ratio=0.6,
        step_points=4.0,
        tight_arm=8.0,
        tight_points=2.0,
        floor_key="scalpTrailFloorPts",
        best_key="scalpTrailBestPts",
    )
    assert floor == 8.0


@patch("app.engines.simple_profit.get_settings")
def test_scalp_trail_sl_fires_on_giveback(mock_settings):
    mock_settings.return_value = _scalp_settings()
    trade = _scalp_trade(entry=40.0, best=8.0)
    profile = OptimizedProfile(
        targetPoints=8.0, stopPoints=3.0, microTargetPoints=2.5,
        maxHoldSeconds=300, sessionLabel="test",
    )
    reason, pnl = evaluate_exit(trade, 45.5, profile, lot_multiplier=65)
    assert reason == "scalp_trail_sl"
    assert pnl > 0


@patch("app.engines.simple_profit.get_settings")
def test_scalp_hard_sl_before_trail_arms(mock_settings):
    mock_settings.return_value = _scalp_settings()
    trade = _scalp_trade(entry=40.55, best=1.35)
    profile = OptimizedProfile(
        targetPoints=5.4, stopPoints=2.16, microTargetPoints=1.3,
        maxHoldSeconds=300, sessionLabel="test",
    )
    reason, _ = evaluate_exit(trade, 37.0, profile, lot_multiplier=65)
    assert reason == "simple_stop_loss"


@patch("app.engines.simple_profit.get_settings")
def test_scalp_target_hit_at_session_tp(mock_settings):
    mock_settings.return_value = _scalp_settings()
    trade = _scalp_trade(entry=40.0, best=9.0)
    profile = OptimizedProfile(
        targetPoints=8.0, stopPoints=3.0, microTargetPoints=2.5,
        maxHoldSeconds=300, sessionLabel="open_drive",
    )
    reason, pnl = evaluate_exit(trade, 48.5, profile, lot_multiplier=65)
    assert reason == "simple_profit_target_hit"
    assert pnl == 8.5 * 40 * 65


@patch("app.engines.capital_allocator.lot_multiplier", return_value=65)
@patch("app.engines.capital_allocator.get_capital_snapshot")
@patch("app.engines.capital_allocator.get_settings")
def test_tune_exit_plan_raises_tp_floor_for_large_position(mock_settings, mock_cap, _mock_mult):
    settings = MagicMock()
    settings.per_trade_capital_pct = 0.85
    settings.position_sl_cap_pct = 0.08
    settings.position_tp_target_pct = 0.12
    settings.scalp_stop_min_points = 2.5
    settings.scalp_stop_points = 3.0
    settings.scalp_trail_step_points = 2.0
    mock_settings.return_value = settings
    mock_cap.return_value = MagicMock(perTradeCapitalInr=170_000, availableMarginInr=200_000)

    plan = tune_exit_plan_for_position(
        {"stopPoints": 3.0, "targetPoints": 6.0, "microTargetPoints": 2.5, "trailArmPoints": 3.0},
        lots=20,
        premium=80.0,
        symbol="NIFTY",
    )
    assert plan["stopPoints"] >= 2.5
    assert plan["targetPoints"] > 6.0
    assert plan["trailArmPoints"] >= 3.0


def test_open_drive_session_tp_is_8pt():
    with patch("app.engines.simple_profit.get_market_phase", return_value="OPEN"):
        with patch("app.engines.simple_profit.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 24, 9, 30)
            profile = get_session_targets()
    assert profile.sessionLabel == "open_drive"
    assert profile.targetPoints == 8.0
