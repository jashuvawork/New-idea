"""Strict top-trades-only gate — block chop/EXPLODING second-tier entries."""

from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings, get_settings
from app.engines.elite_score_engine import (
    build_elite_assessment,
    elite_entry_allowed,
    top_trades_only_blocks_entry,
)
from app.models.schemas import Breadth, SpotChart


@pytest.fixture(autouse=True)
def _enable_top_trades_strict():
    object.__setattr__(get_settings(), "top_trades_only_strict_enabled", True)
    object.__setattr__(get_settings(), "elite_trade_engine_enabled", True)
    yield


def _ranking(**overrides):
    base = {"grade": "A", "rankScore": 80.0, "side": "PUT"}
    base.update(overrides)
    return base


def _aligned_bullish_snap():
    snap = MagicMock(symbol="NIFTY")
    snap.spotChart = SpotChart(
        direction="BULLISH",
        momentum5Pct=0.12,
        trendStrength=70.0,
        emaBias="BULLISH",
        macdBias="BULLISH",
    )
    snap.breadth = Breadth(bias="BULLISH", score=70, aligned=True)
    return snap


def _evidence(**overrides):
    base = {
        "tier": "ELITE",
        "symbol": "NIFTY",
        "localBaseMovePct": 12.0,
        "timingAssessment": "GOOD",
        "armedBaseLaunch": True,
        "firstLift": True,
        "velocity3s": 2.0,
        "flatVerticalQuality": 70.0,
    }
    base.update(overrides)
    return base


def test_blocks_chop_day_expoding_grade_a():
    ev = _evidence(tier="EXPLODING")
    ranking = _ranking()
    assessment = build_elite_assessment(ev, ranking)
    assessment = {
        **assessment,
        "eliteScore": 92.9,
        "grade": "A",
        "setup": "V",
        "localBasePct": 17.9,
        "mustTake": False,
        "dayMode": "CHOP DAY",
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev, ranking, assessment, day_mode="CHOP DAY", side="PUT",
    )
    assert blocked is True
    assert reason == "top_trades_chop_day_not_must_take"


def test_allows_must_take_on_chop():
    ev = _evidence(tier="EXPLODING")
    ranking = _ranking(grade="S")
    assessment = {
        "mustTake": True,
        "eliteScore": 96.0,
        "grade": "S",
        "setup": "FTV",
        "localBasePct": 10.0,
        "dayMode": "CHOP DAY",
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev, ranking, assessment, day_mode="CHOP DAY", side="PUT",
    )
    assert blocked is False


def test_blocks_exploding_tier_on_directional_day():
    ev = _evidence(tier="EXPLODING")
    ranking = _ranking()
    assessment = build_elite_assessment(ev, ranking)
    assessment = {
        **assessment,
        "eliteScore": 91.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 12.0,
        "mustTake": False,
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev, ranking, assessment, day_mode="BEARISH DAY", side="PUT",
    )
    assert blocked is True
    assert reason == "top_trades_requires_elite_tier"


def test_allows_elite_near_base_on_directional_day():
    ev = _evidence(tier="ELITE")
    ranking = _ranking()
    assessment = build_elite_assessment(ev, ranking)
    assessment = {
        **assessment,
        "eliteScore": 92.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 12.0,
        "mustTake": False,
    }
    blocked, _ = top_trades_only_blocks_entry(
        ev, ranking, assessment, day_mode="BEARISH DAY", side="PUT",
    )
    assert blocked is False


def test_near_base_elite_put_waives_expiry_worst_chop_block():
    """Sep 9–17 PE on EXPIRY WORST — near-base ELITE FTV/V must not die on chop block."""
    ev = _evidence(tier="ELITE", setup="FTV")
    ranking = _ranking()
    assessment = {
        "mustTake": False,
        "eliteScore": 95.0,
        "grade": "A",
        "setup": "FTV",
        "localBasePct": 12.0,
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev, ranking, assessment, day_mode="EXPIRY WORST", side="PUT",
    )
    assert blocked is False
    assert reason == ""


def test_near_base_elite_call_waives_chop_day_without_rally_unlock():
    """Sep 9–17 CE near-base on CHOP DAY — symmetric chop waiver (not CE-only path)."""
    ev = _evidence(tier="ELITE", side="CALL")
    ranking = _ranking(side="CALL")
    assessment = {
        "mustTake": False,
        "eliteScore": 94.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 11.0,
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev, ranking, assessment, day_mode="CHOP DAY", side="CALL",
    )
    assert blocked is False
    assert reason == ""


@patch("app.engines.elite_score_engine.resolve_elite_session_day_type", return_value=("CHOP DAY", "CHOP"))
def test_elite_entry_blocks_sep21_style_put(_day):
    """Sep 21 NIFTY 23350 PE: grade-A EXPLODING chop pad — blocked by top-trades gate."""
    settings = Settings()
    ev = _evidence(
        tier="EXPLODING",
        localBaseMovePct=17.9,
        flatVerticalQuality=70.0,
        explosionScore=60.0,
        volumeAwaken=True,
        vRipReady=True,
    )
    ranking = _ranking(rankScore=92.9)
    ok, reason, _ = elite_entry_allowed(
        ev, ranking, settings=settings, side="PUT", day_mode="CHOP DAY",
    )
    assert ok is False
    assert reason in (
        "top_trades_chop_day_not_must_take",
        "top_trades_requires_elite_tier",
    )


@patch(
    "app.engines.aligned_side_guard.session_side_alignment_blocks",
    return_value=(True, "session_side_counter_chart"),
)
def test_sep21_put_blocked_by_chop_side_alignment(_align):
    """High-score counter-trend PUT on chop day — side alignment beats selection score."""
    settings = Settings()
    ev = _evidence(
        tier="EXPLODING",
        side="PUT",
        localBaseMovePct=17.9,
        explosionScore=95.0,
    )
    ranking = _ranking(side="PUT", rankScore=192.0)
    assessment = {
        "mustTake": False,
        "eliteScore": 92.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 17.9,
    }
    snap = MagicMock()
    state = MagicMock()
    blocked, reason = top_trades_only_blocks_entry(
        ev,
        ranking,
        assessment,
        day_mode="CHOP + RALLY",
        side="PUT",
        state=state,
        snap=snap,
        settings=settings,
    )
    assert blocked is True
    assert reason == "session_side_counter_chart"
    _align.assert_called_once()


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_fingerprint", return_value=True)
def test_chop_rally_ce_unlock_waives_chop_block(_rally):
    settings = Settings()
    ev = _evidence(tier="ELITE", symbol="NIFTY")
    ranking = _ranking(side="CALL")
    state = MagicMock()
    snap = _aligned_bullish_snap()
    assessment = {
        "mustTake": False,
        "eliteScore": 88.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 8.0,
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev,
        ranking,
        assessment,
        day_mode="CHOP + RALLY",
        side="CALL",
        state=state,
        snap=snap,
        settings=settings,
    )
    assert blocked is False
    assert reason == ""


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_fingerprint", return_value=True)
def test_chop_rally_allows_building_tier(_rally):
    settings = Settings()
    ev = _evidence(tier="BUILDING", buildingRipBullish=True, symbol="NIFTY")
    ranking = _ranking(side="CALL")
    state = MagicMock()
    snap = _aligned_bullish_snap()
    assessment = {
        "mustTake": False,
        "eliteScore": 86.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 8.0,
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev,
        ranking,
        assessment,
        day_mode="CHOP + RALLY",
        side="CALL",
        state=state,
        snap=snap,
        readiness_reason="building_rip_bullish_ready",
        settings=settings,
    )
    assert blocked is False


@patch("app.engines.best_trade_policy.call_at_base_best_trade_fingerprint", return_value=True)
@patch("app.engines.elite_score_engine.resolve_elite_session_day_type", return_value=("CHOP DAY", "CHOP"))
def test_ce_at_base_waives_chop_block(_day, _ce):
    settings = Settings()
    ev = _evidence(tier="ELITE", symbol="NIFTY")
    ranking = _ranking(side="CALL")
    state = MagicMock()
    snap = _aligned_bullish_snap()
    assessment = {
        "mustTake": False,
        "eliteScore": 92.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 12.0,
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev,
        ranking,
        assessment,
        day_mode="CHOP DAY",
        side="CALL",
        state=state,
        snap=snap,
        settings=settings,
    )
    assert blocked is False
    assert reason == ""


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_fingerprint", return_value=True)
def test_expiry_worst_building_ce_rally_unlock_waives_chop(_rally):
    """EXPIRY WORST BUILDING CE at base — rally unlock waives chop + elite tier."""
    settings = Settings()
    ev = _evidence(tier="BUILDING", buildingRipBullish=True, symbol="NIFTY")
    ranking = _ranking(side="CALL")
    state = MagicMock()
    snap = _aligned_bullish_snap()
    assessment = {
        "mustTake": False,
        "eliteScore": 86.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 12.0,
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev,
        ranking,
        assessment,
        day_mode="EXPIRY WORST",
        side="CALL",
        state=state,
        snap=snap,
        readiness_reason="building_rip_bullish_ready",
        settings=settings,
    )
    assert blocked is False
    assert reason == ""


@patch("app.engines.pe_win_ce_mirror._ce_rally_fingerprint_bar", return_value=True)
def test_bullish_day_building_ce_aligned_fingerprint(_fp):
    """BULLISH DAY BUILDING CE — session-aligned fingerprint, no rally unlock required."""
    settings = Settings()
    ev = _evidence(tier="BUILDING", buildingRipBullish=True, symbol="NIFTY")
    ranking = _ranking(side="CALL")
    state = MagicMock()
    snap = _aligned_bullish_snap()
    assessment = {
        "mustTake": False,
        "eliteScore": 87.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 10.0,
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev,
        ranking,
        assessment,
        day_mode="BULLISH DAY",
        side="CALL",
        state=state,
        snap=snap,
        readiness_reason="building_rip_bullish_ready",
        settings=settings,
    )
    assert blocked is False
    assert reason == ""


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_fingerprint", return_value=True)
def test_bearish_day_building_ce_rally_unlock(_rally):
    """BEARISH DAY BUILDING CE — index rally flip unlocks best-trade tier waiver."""
    settings = Settings()
    ev = _evidence(tier="BUILDING", buildingRipBullish=True, symbol="NIFTY")
    ranking = _ranking(side="CALL")
    state = MagicMock()
    snap = _aligned_bullish_snap()
    assessment = {
        "mustTake": False,
        "eliteScore": 86.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 11.0,
    }
    blocked, reason = top_trades_only_blocks_entry(
        ev,
        ranking,
        assessment,
        day_mode="BEARISH DAY",
        side="CALL",
        state=state,
        snap=snap,
        readiness_reason="building_rip_bullish_ready",
        settings=settings,
    )
    assert blocked is False
    assert reason == ""
