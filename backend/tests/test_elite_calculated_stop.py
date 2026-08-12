"""ELITE/EXPLODING SL is calculated from premium — not crushed to ~8–10pt (Jul30)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.adaptive_exits import compute_adaptive_exit_plan
from app.engines.capital_allocator import tune_exit_plan_for_position
from app.engines.chart_exit_levels import merge_chart_into_exit_plan
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


def _snap(premium: float = 80.0, score: float = 92.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77500.0,
        atmStrike=77500.0,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=85.0,
        breadth=Breadth(bias="BULLISH", score=80, aligned=True),
        topExplosion={
            "tier": "ELITE",
            "premium": premium,
            "velocity3s": 3.2,
            "score": score,
            "dailyMovePct": 35.0,
        },
    )


def _psy() -> PsychologyState:
    return PsychologyState(
        score=0,
        label="NEUTRAL",
        exit_bias="BALANCED",
        news_bias="NEUTRAL",
        breadth_bias="BULLISH",
    )


def _explosion_settings(**overrides):
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
    s.explosion_stop_pct_of_premium = 0.10
    s.explosion_stop_max_pct_of_premium = 0.18
    s.explosion_stop_abs_max_points = 40.0
    s.explosion_chart_stop_min_natural_frac = 0.85
    s.explosion_sl_preserve_natural_frac = 0.85
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
    s.position_sl_cap_pct = 0.08
    s.position_tp_target_pct = 0.12
    s.position_sl_preserve_natural_frac = 0.45
    s.position_min_risk_reward = 1.2
    s.per_trade_capital_pct = 0.85
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _profile() -> OptimizedProfile:
    return OptimizedProfile(
        targetPoints=12.0,
        stopPoints=6.0,
        microTargetPoints=3.0,
        maxHoldSeconds=900,
        sessionLabel="normal",
    )


@patch("app.engines.adaptive_exits.get_ml_engine")
@patch("app.engines.adaptive_exits.get_settings")
def test_elite_high_score_natural_stop_from_premium(mock_settings, mock_ml):
    """Jul30 77500 CE ELITE ~₹80 — natural SL ~10%+ widen, not flat 8pt."""
    s = _explosion_settings()
    mock_settings.return_value = s
    ml = MagicMock()
    ml.extract_features.return_value = {}
    ml.predict_win_probability.return_value = 0.55
    mock_ml.return_value = ml

    plan = compute_adaptive_exit_plan(
        _snap(premium=80.0, score=95.0),
        StrategyType.EXPLOSIVE,
        _psy(),
        _profile(),
        side="CALL",
        confidence=95.0,
        entry_premium=80.0,
        entry_velocity_3s=3.2,
        explosion_tier="ELITE",
    )
    # 80×10%=8 → vel×1.25 → ELITE×1.12 → score×1.10 ≈ 12.3 (before ML)
    assert plan.naturalStopPoints >= 11.0, plan.naturalStopPoints
    assert plan.stopPoints >= 11.0, plan.stopPoints
    assert plan.stopPoints == plan.naturalStopPoints
    assert any("premium" in r.lower() for r in plan.reasoning)
    assert any("High explosion score" in r for r in plan.reasoning)


@patch("app.engines.adaptive_exits.get_ml_engine")
@patch("app.engines.adaptive_exits.get_settings")
def test_explosion_stop_not_flat_20pt_cap(mock_settings, mock_ml):
    """Premium-relative cap replaces old flat 20pt ceiling."""
    s = _explosion_settings()
    mock_settings.return_value = s
    ml = MagicMock()
    ml.extract_features.return_value = {}
    ml.predict_win_probability.return_value = 0.75  # ML widen for explosive
    mock_ml.return_value = ml

    plan = compute_adaptive_exit_plan(
        _snap(premium=200.0),
        StrategyType.EXPLOSIVE,
        _psy(),
        _profile(),
        side="CALL",
        confidence=92.0,
        entry_premium=200.0,
        entry_velocity_3s=4.5,
        explosion_tier="ELITE",
    )
    # Cap = min(40, max(12, 200×0.18)) = 36 — natural should clear old 20pt wall
    assert plan.naturalStopPoints > 20.0, plan.naturalStopPoints
    assert plan.naturalStopPoints <= 40.0, plan.naturalStopPoints


@patch("app.engines.chart_exit_levels.compute_chart_exit_levels")
@patch("app.engines.chart_exit_levels.get_settings")
def test_chart_merge_floors_at_natural_stop(mock_settings, mock_levels):
    """High-conf chart blend must not crush natural ~26pt → ~8pt."""
    s = _explosion_settings(chart_exit_levels_enabled=True)
    s.chart_confidence_half_tp_lock_pct = 0.50
    mock_settings.return_value = s

    levels = MagicMock()
    levels.confidence = 90.0
    levels.confidenceRaw = 180.0
    levels.sources = ["structure", "swing"]
    levels.promoteToTrailing = True
    levels.stopPoints = 4.0  # nearest tiny structure
    levels.targetPoints = 15.0
    levels.targetPoints2 = 22.0
    levels.trailArmPoints = 3.0
    levels.trailKeepRatio = 0.60
    levels.trailStepPoints = 2.5
    levels.microTargetPoints = 3.0
    levels.to_dict.return_value = {"confidence": 90.0}
    mock_levels.return_value = levels

    natural = 26.0
    base = {
        "stopPoints": natural,
        "targetPoints": 25.0,
        "trailArmPoints": 8.0,
        "trailKeepRatio": 0.65,
        "trailStepPoints": 3.5,
        "microTargetPoints": 3.0,
        "naturalStopPoints": natural,
        "reasoning": ["Explosion SL from premium"],
    }
    merged = merge_chart_into_exit_plan(base, _snap(), "CALL", 80.0)
    # Without floor: 26*(1-0.72)+4*0.72 ≈ 10.2; with local-support path or
    # premium keep: stop stays ≥ natural (no crush to ~8pt).
    assert merged["stopPoints"] >= natural * 0.85 - 0.05, merged["stopPoints"]
    assert merged["naturalStopPoints"] == natural
    assert merged["stopPoints"] >= 22.0, merged["stopPoints"]


@patch("app.engines.capital_allocator.lot_multiplier", return_value=20)
@patch("app.engines.capital_allocator.get_capital_snapshot")
@patch("app.engines.capital_allocator.get_settings")
def test_size_tune_keeps_calculated_elite_stop(mock_settings, mock_cap, _mult):
    """Max lots must not crush ELITE natural SL to toy ~8pt."""
    s = _explosion_settings()
    mock_settings.return_value = s
    cap = MagicMock()
    cap.perTradeCapitalInr = 250_000.0
    cap.availableMarginInr = 300_000.0
    mock_cap.return_value = cap

    natural = 26.0
    plan = {
        "stopPoints": 22.1,  # after chart floor
        "targetPoints": 25.0,
        "microTargetPoints": 3.0,
        "trailArmPoints": 8.0,
        "trailStepPoints": 3.5,
        "naturalStopPoints": natural,
        "reasoning": ["Natural SL floor"],
    }
    # 49 lots × 20: budget SL ≈ 250k*0.08/(49*20) ≈ 20.4; preserve 85% of 26 = 22.1
    tuned = tune_exit_plan_for_position(plan, lots=49, premium=80.0, symbol="SENSEX")
    assert tuned["stopPoints"] >= 22.0, tuned["stopPoints"]
    assert tuned["naturalStopPoints"] == natural
    assert tuned["entryStopPoints"] == tuned["stopPoints"]


@patch("app.engines.capital_allocator.lot_multiplier", return_value=20)
@patch("app.engines.capital_allocator.get_capital_snapshot")
@patch("app.engines.capital_allocator.get_settings")
def test_size_tune_prefers_natural_over_budget_crush(mock_settings, mock_cap, _mult):
    s = _explosion_settings()
    mock_settings.return_value = s
    cap = MagicMock()
    cap.perTradeCapitalInr = 100_000.0  # tight budget → ~5pt at 80 lots
    cap.availableMarginInr = 120_000.0
    mock_cap.return_value = cap

    natural = 24.0
    plan = {
        "stopPoints": 24.0,
        "targetPoints": 25.0,
        "microTargetPoints": 3.0,
        "trailArmPoints": 8.0,
        "trailStepPoints": 3.5,
        "naturalStopPoints": natural,
        "reasoning": [],
    }
    tuned = tune_exit_plan_for_position(plan, lots=80, premium=90.0, symbol="SENSEX")
    assert tuned["stopPoints"] >= natural * 0.85 - 0.05, tuned["stopPoints"]
    assert any("Keep calculated SL" in r for r in tuned["reasoning"])
    # Preserve SL by shrinking size — don't claim SL ≤ budget while oversizing.
    max_sl = 100_000.0 * 0.08
    assert tuned["lots"] < 80
    assert tuned["actualSlRiskInr"] <= max_sl + 1.0
    assert any("Shrink lots" in r for r in tuned["reasoning"])
    assert "SL ≤₹" in " ".join(tuned["reasoning"])


@patch("app.engines.capital_allocator.lot_multiplier", return_value=75)
@patch("app.engines.capital_allocator.get_capital_snapshot")
@patch("app.engines.capital_allocator.get_settings")
def test_size_tune_aug11_style_max_lots_over_budget(mock_settings, mock_cap, _mult):
    """Aug11 NIFTY 63-lot kept ~9pt SL while message claimed SL ≤₹15.2k."""
    s = _explosion_settings()
    mock_settings.return_value = s
    cap = MagicMock()
    cap.perTradeCapitalInr = 190_000.0
    cap.availableMarginInr = 220_000.0
    mock_cap.return_value = cap

    natural = 10.6
    plan = {
        "stopPoints": 9.02,
        "targetPoints": 12.0,
        "microTargetPoints": 3.0,
        "trailArmPoints": 8.0,
        "trailStepPoints": 3.5,
        "naturalStopPoints": natural,
        "reasoning": [],
    }
    tuned = tune_exit_plan_for_position(plan, lots=63, premium=45.7, symbol="NIFTY")
    max_sl = 190_000.0 * 0.08
    assert tuned["stopPoints"] >= natural * 0.85 - 0.05, tuned["stopPoints"]
    assert tuned["lots"] < 63
    assert tuned["actualSlRiskInr"] <= max_sl + 1.0
    # Never advertise a false SL ceiling.
    joined = " ".join(tuned["reasoning"])
    assert "SL ≤₹" in joined
    assert tuned["actualSlRiskInr"] <= tuned["maxSlBudgetInr"] + 1.0
