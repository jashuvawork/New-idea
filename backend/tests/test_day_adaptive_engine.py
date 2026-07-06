"""Tests for day-adaptive engine — worst/chop/good day routing."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.day_adaptive_engine import (
    apply_rank_floor_adaptive,
    build_day_adaptive_profile,
    classify_day_type,
    mode_rank_bonus,
    should_pause_regular_scalps,
)
from app.models.schemas import AutoTraderState, Breadth, MarketPhase, Regime, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = get_settings()
    s.day_adaptive_enabled = True
    s.day_adaptive_worst_rank_cap = 68.0
    s.day_adaptive_chop_rank_cap = 70.0
    s.day_adaptive_good_day_rank_relief = 3.0
    return s


def _snap(bias: str = "NEUTRAL", regime: str = "RANGE_BOUND") -> SymbolSnapshot:
    reg = Regime.RANGE_BOUND if regime == "RANGE_BOUND" else Regime.TREND_EXPANSION
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=65,
        regime=reg,
        breadth=Breadth(bias=bias, score=55, aligned=bias != "NEUTRAL"),
    )


@patch("app.engines.whipsaw_guards.is_bearish_sideways_session", return_value=True)
def test_classify_worst_day(_bear):
    day_type = classify_day_type("CHOP DAY", "MEDIUM", {"SENSEX": _snap()})
    assert day_type == "WORST"


@patch("app.engines.whipsaw_guards.is_bearish_sideways_session", return_value=False)
@patch("app.engines.chop_day_guards.is_chop_session", return_value=True)
@patch("app.engines.chop_day_guards.in_momentum_rally_window", return_value=False)
def test_classify_chop_day(_rally, _chop, _bear):
    day_type = classify_day_type("CHOP DAY", "MEDIUM", {"SENSEX": _snap()})
    assert day_type == "CHOP"


@patch("app.engines.whipsaw_guards.is_bearish_sideways_session", return_value=False)
@patch("app.engines.chop_day_guards.is_chop_session", return_value=False)
@patch("app.engines.chop_day_guards.in_momentum_rally_window", return_value=True)
def test_classify_good_day(_rally, _chop, _bear):
    day_type = classify_day_type("MOMENTUM RALLY", "HIGH", {"SENSEX": _snap(bias="BULLISH", regime="TREND")})
    assert day_type in ("GOOD", "ELITE")


def test_worst_day_favors_quick_sideways():
    profile = build_day_adaptive_profile("EXPIRY WORST", "LOW", {"SENSEX": _snap()})
    assert profile.preferred_modes[0] == "quick_sideways"
    assert mode_rank_bonus("quick_sideways", profile) > mode_rank_bonus("scalp", profile)


def test_rank_floor_cap_on_worst_day():
    profile = build_day_adaptive_profile("EXPIRY WORST", "LOW", {})
    capped = apply_rank_floor_adaptive(78.0, profile, candidate_mode="explosion")
    assert capped <= profile.min_rank_cap


def test_good_day_rank_relief():
    profile = build_day_adaptive_profile("BULLISH DAY", "HIGH", {"SENSEX": _snap(bias="BULLISH", regime="TREND")})
    relieved = apply_rank_floor_adaptive(68.0, profile)
    assert relieved < 68.0


def test_pause_scalps_not_quick_sideways_on_worst():
    profile = build_day_adaptive_profile("EXPIRY WORST", "LOW", {})
    assert should_pause_regular_scalps(profile, edge_pause_scalps=True) is True
    assert profile.preferred_modes[0] == "quick_sideways"
