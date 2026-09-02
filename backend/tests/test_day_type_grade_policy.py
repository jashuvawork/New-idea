"""Tests for day-type min grade policy and fast-day grade-C waiver."""

import pytest
from unittest.mock import patch

from app.config import Settings
from app.engines.day_type_grade_policy import (
    fast_moving_grade_c_waiver,
    large_loss_pause_bypass_for_day_mode,
    resolve_day_type_min_grade,
)
from app.engines.top_moment_gate import (
    resolve_top_moment_min_grade,
    top_moment_entry_allowed,
)


def _settings(**overrides):
    s = Settings()
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_bearish_day_loosens_to_b():
    s = _settings(top_moments_day_type_grade_policy_enabled=True)
    assert resolve_day_type_min_grade(min_grade="A", day_mode="BEARISH DAY", settings=s) == "B"


def test_chop_day_stays_a():
    s = _settings(top_moments_day_type_grade_policy_enabled=True)
    assert resolve_day_type_min_grade(min_grade="A", day_mode="CHOP DAY", settings=s) == "A"


def test_policy_disabled_keeps_base():
    s = _settings(top_moments_day_type_grade_policy_enabled=False)
    assert resolve_day_type_min_grade(min_grade="A", day_mode="BEARISH DAY", settings=s) == "A"


def test_momentum_rally_legacy_override():
    s = _settings(
        top_moments_day_type_grade_policy_enabled=False,
        top_moments_momentum_rally_grade_b_enabled=True,
    )
    assert resolve_top_moment_min_grade(min_grade="A", day_mode="MOMENTUM RALLY", settings=s) == "B"


def test_fast_day_grade_c_waiver_elite_vrip():
    evidence = {
        "tier": "ELITE",
        "vRipReady": True,
        "velocity3s": 3.0,
    }
    ranking = {"grade": "C", "rankScore": 55}
    s = _settings(top_moments_fast_day_grade_c_enabled=True)
    assert fast_moving_grade_c_waiver(
        evidence, ranking, "V", day_mode="MOMENTUM RALLY", settings=s,
    )


def test_fast_day_grade_c_waiver_blocks_low_score():
    evidence = {"tier": "EXPLODING", "vRipReady": True, "velocity3s": 3.0}
    ranking = {"grade": "C", "rankScore": 40}
    s = _settings(top_moments_fast_day_grade_c_enabled=True)
    assert not fast_moving_grade_c_waiver(
        evidence, ranking, "EXPLODING", day_mode="BEARISH DAY", settings=s,
    )


def test_fast_day_grade_c_waiver_allows_sep02_edge_score():
    evidence = {"tier": "EXPLODING", "vRipReady": True, "velocity3s": 3.0}
    ranking = {"grade": "C", "rankScore": 49.4}
    s = _settings(top_moments_fast_day_grade_c_enabled=True)
    assert fast_moving_grade_c_waiver(
        evidence, ranking, "EXPLODING", day_mode="MOMENTUM RALLY", settings=s,
    )


def test_fast_day_grade_c_waiver_not_on_chop_day():
    evidence = {"tier": "ELITE", "vRipReady": True, "velocity3s": 3.0}
    ranking = {"grade": "C", "rankScore": 55}
    s = _settings(top_moments_fast_day_grade_c_enabled=True)
    assert not fast_moving_grade_c_waiver(
        evidence, ranking, "V", day_mode="CHOP DAY", settings=s,
    )


def test_top_moment_allows_grade_c_on_bearish_fast_day():
    ok, reason, moment = top_moment_entry_allowed(
        {
            "tier": "EXPLODING",
            "flatThenVertical": True,
            "activeBreakout": True,
            "velocity3s": 3.0,
            "orderflowPositive": True,
            "cvdBuying": True,
        },
        {"grade": "C", "rankScore": 55},
        day_mode="BEARISH DAY",
    )
    assert ok is True
    assert reason == "ok"
    assert moment == "EXPLODING"


def test_top_moment_blocks_grade_c_on_chop_day():
    with patch("app.config.get_settings") as mock_settings:
        s = Settings()
        s.top_moments_fast_day_grade_c_enabled = True
        s.top_moments_day_type_grade_policy_enabled = True
        mock_settings.return_value = s
        ok, reason, _ = top_moment_entry_allowed(
            {
                "tier": "EXPLODING",
                "flatThenVertical": True,
                "activeBreakout": True,
                "velocity3s": 3.0,
            },
            {"grade": "C", "rankScore": 55},
            day_mode="CHOP DAY",
        )
    assert ok is False
    assert "grade" in reason


def test_large_loss_pause_bypass_expiry_worst_blocked():
    s = _settings()
    policy = large_loss_pause_bypass_for_day_mode("EXPIRY WORST", settings=s)
    assert policy["allowed"] is False


def test_large_loss_pause_bypass_momentum_rally_standard():
    s = _settings()
    policy = large_loss_pause_bypass_for_day_mode("MOMENTUM RALLY", settings=s)
    assert policy["allowed"] is True
    assert policy["strict"] is False
    assert policy["minScore"] == 90.0


def test_large_loss_pause_bypass_chop_day_strict():
    s = _settings()
    policy = large_loss_pause_bypass_for_day_mode("CHOP DAY", settings=s)
    assert policy["allowed"] is True
    assert policy["strict"] is True
    assert policy["minScore"] == 95.0
    assert policy["tiersCsv"] == "ELITE"


_ALL_DAY_MODES = (
    "EXPIRY WORST",
    "EXPIRY DAY",
    "CHOP + RALLY",
    "MOMENTUM RALLY",
    "CHOP (PRE-10)",
    "CHOP DAY",
    "BULLISH DAY",
    "BEARISH DAY",
    "MIXED DAY",
    "LEAN BULLISH",
    "LEAN BEARISH",
    "NORMAL",
)
_STANDARD_BYPASS_MODES = frozenset(_ALL_DAY_MODES) - frozenset(
    {"EXPIRY WORST", "CHOP DAY", "CHOP (PRE-10)"}
)
_STRICT_BYPASS_MODES = frozenset({"CHOP DAY", "CHOP (PRE-10)"})


@pytest.mark.parametrize("day_mode", sorted(_STANDARD_BYPASS_MODES))
def test_large_loss_pause_bypass_all_standard_modes(day_mode: str):
    s = _settings()
    policy = large_loss_pause_bypass_for_day_mode(day_mode, settings=s)
    assert policy["allowed"] is True
    assert policy["strict"] is False
    assert policy["minScore"] == 90.0


@pytest.mark.parametrize("day_mode", sorted(_STRICT_BYPASS_MODES))
def test_large_loss_pause_bypass_all_strict_modes(day_mode: str):
    s = _settings()
    policy = large_loss_pause_bypass_for_day_mode(day_mode, settings=s)
    assert policy["allowed"] is True
    assert policy["strict"] is True
    assert policy["minScore"] == 95.0
