"""Tests for unified EliteScore engine and weekly trade budget."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.elite_score_engine import (
    STAGE_RANK,
    build_elite_assessment,
    compute_elite_score,
    elite_entry_allowed,
    elite_must_take,
    infer_setup_type,
    infer_stage,
)
from app.engines.elite_trade_budget import (
    elite_budget_blocks_entry,
    elite_trade_budget_allows,
    elite_trade_budget_summary,
    record_elite_trade_entry,
)
from app.models.schemas import AutoTraderState

IST = ZoneInfo("Asia/Kolkata")


def _ftv_evidence(**kwargs):
    base = {
        "tier": "BUILDING",
        "flatThenVertical": True,
        "activeBreakout": True,
        "armedBaseLaunch": True,
        "velocity3s": 2.5,
        "velocity9s": 1.8,
        "localBaseMovePct": 12.0,
        "flatVerticalQuality": 80.0,
        "explosionScore": 75.0,
        "volumeAwaken": True,
        "timingAssessment": "GOOD",
        "timingAction": "allow",
    }
    base.update(kwargs)
    return base


def _v_evidence(**kwargs):
    base = {
        "tier": "BUILDING",
        "flatThenVertical": False,
        "vRipReady": True,
        "activeBreakout": True,
        "armedBaseLaunch": True,
        "firstLift": True,
        "velocity3s": 2.5,
        "velocity9s": 1.8,
        "localBaseMovePct": 12.0,
        "flatVerticalQuality": 79.0,
        "explosionScore": 85.0,
        "volumeAwaken": True,
        "timingAssessment": "GOOD",
        "timingAction": "allow",
    }
    base.update(kwargs)
    return base


def _evidence(**kwargs):
    return _ftv_evidence(**kwargs)


def _ranking(**kwargs):
    base = {"grade": "A", "rankScore": 80.0}
    base.update(kwargs)
    return base


def _settings_v_rip_off():
    from app.config import get_settings

    settings = get_settings()
    object.__setattr__(settings, "elite_trade_v_rip_only_enabled", False)
    return settings


def test_infer_setup_ftv():
    assert infer_setup_type(_ftv_evidence()) == "FTV"


def test_infer_setup_v():
    assert infer_setup_type(_v_evidence()) == "V"


def test_infer_setup_explosive():
    assert infer_setup_type(_ftv_evidence(tier="ELITE", flatThenVertical=False, vRipReady=False)) == "EXPLOSIVE"


def test_infer_stage_armed():
    assert infer_stage(_v_evidence(activeBreakout=False, firstLift=False)) == "ARMED"


def test_infer_stage_expanding():
    assert infer_stage(_v_evidence(tier="ELITE", velocity3s=4.0)) == "EXPANDING"


def test_elite_score_high_for_quality_ftv():
    score, band, parts = compute_elite_score(_ftv_evidence(), _ranking(grade="S"))
    assert score >= 90.0
    assert band in ("ELITE", "ELITE A+")
    assert parts["setupType"] == 12.0


def test_elite_entry_allowed_passes_quality_v():
    ok, reason, assessment = elite_entry_allowed(_v_evidence(), _ranking(grade="A"))
    assert ok is True
    assert reason == "ok"
    assert assessment["setup"] == "V"


def test_elite_entry_blocks_non_v_when_v_rip_only():
    ok, reason, _ = elite_entry_allowed(
        _ftv_evidence(flatVerticalQuality=79.0),
        _ranking(grade="A"),
    )
    assert ok is False
    assert reason == "elite_v_rip_only"


def test_elite_entry_blocks_high_fvq_chase():
    ok, reason, _ = elite_entry_allowed(
        _v_evidence(
            flatVerticalQuality=85.0,
            armedBaseLaunch=False,
            firstLift=True,
            activeBreakout=True,
        ),
        _ranking(rankScore=95.0, grade="S"),
    )
    assert ok is False
    assert reason == "elite_fvq_chase_above_ceiling"


def test_elite_entry_blocks_shallow_first_lift():
    ok, reason, _ = elite_entry_allowed(
        _v_evidence(
            localBaseMovePct=8.0,
            armedBaseLaunch=True,
            activeBreakout=False,
            firstLift=False,
            velocity3s=1.5,
        ),
        _ranking(rankScore=95.0, grade="S"),
    )
    assert ok is False
    assert reason == "elite_shallow_first_lift_blocked"



def test_elite_entry_blocks_shallow_elite_tier_without_lift():
    ok, reason, _ = elite_entry_allowed(
        _v_evidence(
            localBaseMovePct=6.5,
            tier="ELITE",
            velocity3s=4.0,
            firstLift=False,
            activeBreakout=False,
            armedBaseLaunch=True,
            flatVerticalQuality=79.0,
        ),
        _ranking(rankScore=95.0, grade="S"),
    )
    assert ok is False
    assert reason == "elite_shallow_first_lift_blocked"


def test_elite_entry_blocks_high_fvq_armed_launch_without_grade_a_reason():
    ok, reason, _ = elite_entry_allowed(
        _v_evidence(
            flatVerticalQuality=85.0,
            armedBaseLaunch=True,
            firstLift=False,
            activeBreakout=False,
            velocity3s=1.5,
        ),
        _ranking(rankScore=95.0, grade="S"),
    )
    assert ok is False
    assert reason == "elite_fvq_chase_above_ceiling"


def test_elite_entry_allows_shallow_when_triggered():
    ok, reason, _ = elite_entry_allowed(
        _v_evidence(
            localBaseMovePct=8.0,
            firstLift=True,
            activeBreakout=True,
            velocity3s=2.5,
        ),
        _ranking(grade="A"),
    )
    assert ok is True
    assert reason == "ok"


def test_elite_entry_blocks_low_milestone_depth_when_present():
    ok, reason, _ = elite_entry_allowed(
        {**_v_evidence(), "milestoneCount": 1},
        _ranking(grade="A"),
    )
    assert ok is False
    assert reason == "elite_milestone_depth_below_min"


def test_elite_entry_blocks_low_score():
    ok, reason, _ = elite_entry_allowed(
        _v_evidence(flatVerticalQuality=20.0, explosionScore=10.0),
        _ranking(rankScore=20.0, grade="C"),
    )
    assert ok is False
    assert "elite_score" in reason


def test_elite_entry_blocks_chase():
    ok, reason, _ = elite_entry_allowed(
        _v_evidence(
            localBaseMovePct=35.0,
            flatVerticalQuality=79.0,
            explosionScore=90.0,
        ),
        _ranking(rankScore=95.0, grade="S"),
    )
    assert ok is False
    assert reason == "elite_chase_past_local_base_window"


def test_elite_entry_blocks_call_past_tight_local_cap():
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(localBaseMovePct=12.0, side="CALL"),
        _ranking(grade="A"),
    )
    assert ok is False
    assert reason == "elite_call_chase_past_local_base_window"
    assert assessment.get("side") == "CALL"


def test_elite_entry_allows_call_at_tight_local_cap():
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(localBaseMovePct=8.0, side="CALL"),
        _ranking(grade="A"),
    )
    assert ok is True
    assert reason == "ok"
    assert assessment.get("localBaseCapPct") == 10.0


def test_elite_entry_allows_put_at_general_local_cap():
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(localBaseMovePct=18.0, side="PUT"),
        _ranking(grade="A"),
    )
    assert ok is True
    assert reason == "ok"
    assert assessment.get("localBaseCapPct") == 20.0


def test_elite_entry_blocks_call_on_momentum_rally():
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(side="CALL"),
        _ranking(grade="A"),
        day_mode="MOMENTUM RALLY",
        day_type="GOOD",
    )
    assert ok is False
    assert reason == "elite_call_momentum_rally_blocked"
    assert assessment.get("side") == "CALL"


def test_elite_entry_blocks_call_on_momentum_rally_when_side_only_in_ranking():
    """Live rank_entry_candidate often carries side on ranking, not evidence."""
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(),
        {**_ranking(grade="A"), "side": "CALL"},
        day_mode="MOMENTUM RALLY",
        day_type="GOOD",
    )
    assert ok is False
    assert reason == "elite_call_momentum_rally_blocked"
    assert assessment.get("side") == "CALL"


def test_elite_entry_allows_put_on_momentum_rally():
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(side="PUT"),
        _ranking(grade="A"),
        day_mode="MOMENTUM RALLY",
        day_type="GOOD",
    )
    assert ok is True
    assert reason == "ok"
    assert assessment.get("side") == "PUT"


def test_elite_entry_blocks_put_on_bullish_day_when_enabled():
    from app.config import get_settings

    settings = get_settings()
    object.__setattr__(settings, "elite_put_block_bullish_day_enabled", True)
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(side="PUT"),
        _ranking(grade="A"),
        day_mode="BULLISH DAY",
        day_type="GOOD",
        settings=settings,
    )
    assert ok is False
    assert reason == "elite_put_bullish_day_blocked"
    assert assessment.get("side") == "PUT"


def test_elite_entry_blocks_perfect_score_chase():
    ev = _v_evidence(
        localBaseMovePct=18.0,
        flatVerticalQuality=79.0,
        explosionScore=100.0,
        side="PUT",
    )
    ok, reason, _ = elite_entry_allowed(ev, _ranking(rankScore=95.0, grade="S"))
    assert ok is False
    assert reason == "elite_perfect_score_chase_blocked"


def test_elite_entry_allows_perfect_score_near_base():
    ev = _v_evidence(
        localBaseMovePct=10.0,
        flatVerticalQuality=79.0,
        explosionScore=100.0,
        side="PUT",
    )
    ok, reason, _ = elite_entry_allowed(ev, _ranking(rankScore=95.0, grade="S"))
    assert ok is True
    assert reason == "ok"


def test_elite_entry_blocks_bad_timing():
    ok, reason, _ = elite_entry_allowed(
        _v_evidence(timingAssessment="CHASE", timingAction="block"),
        _ranking(),
    )
    assert ok is False
    assert reason == "elite_timing_not_good_or_ok"


def test_elite_entry_blocks_momentum_rally_worst_day_type():
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(),
        _ranking(grade="A"),
        day_mode="MOMENTUM RALLY",
        day_type="WORST",
    )
    assert ok is False
    assert reason == "elite_momentum_rally_worst_blocked"
    assert assessment.get("dayType") == "WORST"
    assert assessment.get("dayMode") == "MOMENTUM RALLY"


def test_elite_entry_allows_chop_rally_worst_day_type():
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(),
        _ranking(grade="A"),
        day_mode="CHOP + RALLY",
        day_type="WORST",
    )
    assert ok is True
    assert reason == "ok"
    assert assessment.get("dayType") == "WORST"
    assert assessment.get("dayMode") == "CHOP + RALLY"


def test_elite_entry_blocks_worst_day_type():
    """Legacy alias: WORST alone without dayMode does not block (needs MOMENTUM RALLY)."""
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(),
        _ranking(grade="A"),
        day_type="WORST",
    )
    assert ok is True
    assert reason == "ok"
    assert assessment.get("dayType") == "WORST"


def test_elite_entry_allows_good_day_type():
    ok, reason, assessment = elite_entry_allowed(
        _v_evidence(),
        _ranking(grade="A"),
        day_type="GOOD",
    )
    assert ok is True
    assert reason == "ok"
    assert assessment.get("dayType") == "GOOD"


def test_elite_worst_day_block_disabled():
    from app.config import get_settings

    settings = get_settings()
    object.__setattr__(settings, "elite_trade_block_worst_day_type_enabled", False)
    ok, reason, _ = elite_entry_allowed(
        _v_evidence(),
        _ranking(grade="A"),
        day_mode="MOMENTUM RALLY",
        day_type="WORST",
        settings=settings,
    )
    assert ok is True
    assert reason == "ok"


def test_elite_entry_blocks_base_stage():
    ok, reason, _ = elite_entry_allowed(
        _ftv_evidence(
            armedBaseLaunch=False,
            eliteBaseReady=False,
            firstLift=False,
            activeBreakout=False,
            velocity3s=1.0,
            flatVerticalQuality=79.0,
            explosionScore=90.0,
        ),
        _ranking(rankScore=85.0, grade="S"),
        settings=_settings_v_rip_off(),
    )
    assert ok is False
    assert reason == "elite_stage_below_armed"


def test_elite_must_take_grade_s_ftv():
    ev = _ftv_evidence(flatVerticalQuality=90.0, localBaseMovePct=10.0)
    assessment = build_elite_assessment(ev, _ranking(grade="S"))
    assert elite_must_take(ev, _ranking(grade="S"), assessment) is True


def test_elite_must_take_rejects_grade_a():
    assessment = build_elite_assessment(_ftv_evidence(), _ranking(grade="A"))
    assert elite_must_take(_ftv_evidence(), _ranking(grade="A"), assessment) is False


@patch("app.engines.elite_trade_budget._iso_week", return_value="2026-W36")
def test_weekly_budget_cap_blocks(_mock_week):
    from app.config import get_settings

    object.__setattr__(get_settings(), "elite_trade_engine_enabled", True)
    state = AutoTraderState(dailyStrategy={
        "eliteTradeBudget": {"isoWeek": "2026-W36", "entriesUsed": 8, "mustTakeUsed": 0},
    })
    assessment = {"mustTake": False, "eliteScore": 92.0}
    ok, reason, summary = elite_trade_budget_allows(state, assessment)
    assert ok is False
    assert reason == "elite_weekly_cap_reached"
    assert summary["entriesRemaining"] == 0


@patch("app.engines.elite_trade_budget._iso_week", return_value="2026-W36")
def test_weekly_budget_must_take_bypasses_cap(_mock_week):
    from app.config import get_settings

    object.__setattr__(get_settings(), "elite_trade_engine_enabled", True)
    state = AutoTraderState(dailyStrategy={
        "eliteTradeBudget": {"isoWeek": "2026-W36", "entriesUsed": 8, "mustTakeUsed": 0},
    })
    assessment = {"mustTake": True, "eliteScore": 96.0}
    ok, reason, _ = elite_trade_budget_allows(state, assessment)
    assert ok is True
    assert reason == "must_take_bypass"


@patch("app.engines.elite_trade_budget._iso_week", return_value="2026-W36")
def test_record_elite_trade_entry_increments(_mock_week):
    state = AutoTraderState()
    summary = record_elite_trade_entry(
        state,
        {"eliteScore": 94.0, "eliteBand": "ELITE", "setup": "FTV", "stage": "ARMED"},
        symbol="NIFTY",
        side="CALL",
        strike=24250.0,
    )
    assert summary["entriesUsed"] == 1
    assert summary["entriesRemaining"] == 7
    assert state.dailyStrategy["eliteTradeBudget"]["lastEntry"]["symbol"] == "NIFTY"


@patch("app.engines.elite_trade_budget._iso_week", return_value="2026-W36")
def test_elite_budget_blocks_entry_when_cap_hit(_mock_week):
    from app.config import get_settings

    object.__setattr__(get_settings(), "elite_trade_engine_enabled", True)
    state = AutoTraderState(dailyStrategy={
        "eliteTradeBudget": {"isoWeek": "2026-W36", "entriesUsed": 8, "mustTakeUsed": 0},
    })
    blocked, reason, _ = elite_budget_blocks_entry(state, _v_evidence(), _ranking())
    assert blocked is True
    assert reason == "elite_weekly_cap_reached"


def test_top_moment_gate_delegates_to_elite_engine():
    from app.config import get_settings
    from app.engines.top_moment_gate import top_moment_entry_allowed

    settings = get_settings()
    object.__setattr__(settings, "elite_trade_engine_enabled", True)
    object.__setattr__(settings, "elite_trade_min_score", 90.0)
    object.__setattr__(settings, "elite_trade_max_local_base_pct", 20.0)
    object.__setattr__(settings, "elite_trade_min_stage", "ARMED")
    object.__setattr__(settings, "elite_trade_must_take_enabled", True)
    object.__setattr__(settings, "elite_trade_must_take_min_grade", "S")
    object.__setattr__(settings, "elite_trade_must_take_min_fvq", 85.0)
    object.__setattr__(settings, "elite_trade_must_take_max_local_base_pct", 15.0)

    with patch("app.config.get_settings", return_value=settings):
        ok, reason, moment = top_moment_entry_allowed(_v_evidence(), _ranking())
    assert ok is True
    assert reason == "ok"
    assert moment in ("FTV", "ELITE", "EXPLODING", "V")
