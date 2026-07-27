"""Scalp adaptive SL is calculated from premium, not fixed 3pt."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.adaptive_exits import compute_adaptive_exit_plan
from app.engines.psychology_engine import PsychologyState
from app.models.schemas import (
    Breadth,
    MarketPhase,
    OptimizedProfile,
    Regime,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=23950.0,
        atmStrike=23950.0,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=60.0,
        breadth=Breadth(bias="BULLISH", score=70, aligned=True),
    )


def _psy() -> PsychologyState:
    return PsychologyState(
        score=0,
        label="NEUTRAL",
        exit_bias="BALANCED",
        news_bias="NEUTRAL",
        breadth_bias="BULLISH",
    )


def _settings(**overrides):
    s = MagicMock()
    s.scalp_stop_min_points = 2.5
    s.scalp_stop_points = 3.0
    s.scalp_stop_pct_of_premium = 0.10
    s.scalp_stop_max_points = 15.0
    s.scalp_trail_arm_points = 3.0
    s.scalp_trail_keep_ratio = 0.60
    s.scalp_trail_step_points = 2.0
    s.scalp_trail_tight_arm = 8.0
    s.scalp_trail_tight_points = 3.0
    s.explosion_target_standard = 12.0
    s.explosion_target_elite = 25.0
    s.explosion_trail_arm_points = 4.0
    s.explosion_trail_keep_ratio = 0.65
    s.explosion_trail_step_points = 2.5
    s.explosion_trail_tight_arm = 8.0
    s.explosion_trail_tight_points = 3.0
    s.explosion_micro_target_points = 3.0
    s.extreme_explosion_all_in_enabled = False
    s.extreme_explosion_elite_move_min_pct = 80.0
    s.extreme_explosion_hold_min_best_points = 8.0
    s.chart_exit_levels_enabled = False
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@patch("app.engines.adaptive_exits.get_ml_engine")
@patch("app.engines.adaptive_exits.get_settings")
def test_scalp_stop_from_premium_not_fixed_3pt(mock_settings, mock_ml):
    """Jul27 23900 CE @121 — SL should be ~12pt (10%), not fixed 3pt."""
    s = _settings()
    mock_settings.return_value = s
    ml = MagicMock()
    ml.extract_features.return_value = {}
    ml.predict_win_probability.return_value = 0.55
    mock_ml.return_value = ml

    profile = OptimizedProfile(
        targetPoints=8.0, stopPoints=3.0, microTargetPoints=2.5,
        maxHoldSeconds=300, sessionLabel="normal",
    )
    plan = compute_adaptive_exit_plan(
        _snap(),
        StrategyType.SCALP,
        _psy(),
        profile,
        side="CALL",
        confidence=90.0,
        entry_premium=121.0,
    )
    assert plan.stopPoints >= 10.0, plan.stopPoints
    assert plan.stopPoints <= 15.0, plan.stopPoints
    assert any("premium" in r.lower() for r in plan.reasoning)


@patch("app.engines.adaptive_exits.get_ml_engine")
@patch("app.engines.adaptive_exits.get_settings")
def test_scalp_stop_respects_max_cap(mock_settings, mock_ml):
    s = _settings(scalp_stop_max_points=12.0)
    mock_settings.return_value = s
    ml = MagicMock()
    ml.extract_features.return_value = {}
    ml.predict_win_probability.return_value = 0.55
    mock_ml.return_value = ml

    profile = OptimizedProfile(
        targetPoints=8.0, stopPoints=3.0, microTargetPoints=2.5,
        maxHoldSeconds=300, sessionLabel="normal",
    )
    plan = compute_adaptive_exit_plan(
        _snap(),
        StrategyType.SCALP,
        _psy(),
        profile,
        side="CALL",
        confidence=90.0,
        entry_premium=200.0,  # 10% = 20 → capped at 12
    )
    assert plan.stopPoints == 12.0


@patch("app.engines.adaptive_exits.get_ml_engine")
@patch("app.engines.adaptive_exits.get_settings")
def test_scalp_stop_floor_for_cheap_premium(mock_settings, mock_ml):
    s = _settings()
    mock_settings.return_value = s
    ml = MagicMock()
    ml.extract_features.return_value = {}
    ml.predict_win_probability.return_value = 0.55
    mock_ml.return_value = ml

    profile = OptimizedProfile(
        targetPoints=8.0, stopPoints=3.0, microTargetPoints=2.5,
        maxHoldSeconds=300, sessionLabel="normal",
    )
    plan = compute_adaptive_exit_plan(
        _snap(),
        StrategyType.SCALP,
        _psy(),
        profile,
        side="CALL",
        confidence=70.0,
        entry_premium=20.0,  # floored to premium=25 → 2.5
    )
    assert plan.stopPoints >= 2.5
