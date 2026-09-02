"""Tests for top-moment entry gate (FTV / V / ELITE / EXPLODING only)."""

import pytest

from app.engines.top_moment_gate import (
    classify_top_moment_type,
    explosion_alert_is_top_moment,
    top_moment_entry_allowed,
)


def _evidence(**kwargs):
    base = {
        "mode": "explosion",
        "tier": "EXPLODING",
        "flatThenVertical": True,
        "activeBreakout": True,
        "velocity3s": 3.0,
        "velocity9s": 2.0,
        "localBaseMovePct": 12.0,
        "orderflowPositive": True,
        "cvdBuying": True,
    }
    base.update(kwargs)
    return base


def _ranking(grade="A", **kwargs):
    return {"grade": grade, "gradePriority": 3 if grade == "A" else 4, **kwargs}


def test_classify_v_rip():
    assert classify_top_moment_type(_evidence(tier="BUILDING", vRipReady=True)) == "V"


def test_classify_ftv_building_helpers():
    t = classify_top_moment_type(
        _evidence(
            tier="BUILDING",
            buildingRipReady=True,
            buildingRipHelpersOk=True,
        )
    )
    assert t == "FTV"


def test_classify_elite_at_base():
    assert (
        classify_top_moment_type(
            _evidence(tier="ELITE", armedBaseLaunch=True)
        )
        == "ELITE"
    )


def test_classify_exploding_ftv():
    assert (
        classify_top_moment_type(
            _evidence(tier="EXPLODING", flatThenVertical=True, activeBreakout=True)
        )
        == "EXPLODING"
    )


def test_generic_building_blocked():
    assert (
        classify_top_moment_type(
            _evidence(
                tier="BUILDING",
                flatThenVertical=False,
                activeBreakout=False,
            )
        )
        is None
    )


def test_top_moment_allows_grade_a_elite():
    ok, reason, moment = top_moment_entry_allowed(
        _evidence(tier="ELITE", armedBaseLaunch=True),
        _ranking("A"),
    )
    assert ok is True
    assert reason == "ok"
    assert moment == "ELITE"


def test_top_moment_blocks_grade_b():
    from unittest.mock import patch

    with patch("app.config.get_settings") as mock_settings:
        settings = mock_settings.return_value
        settings.top_moments_exploding_elite_grade_b_enabled = False
        settings.top_moments_momentum_rally_grade_b_enabled = False
        ok, reason, _ = top_moment_entry_allowed(
            _evidence(tier="EXPLODING", flatThenVertical=True, activeBreakout=True),
            _ranking("B"),
        )
    assert ok is False
    assert "grade" in reason


def test_exploding_elite_grade_b_waiver_allows_pad_moment():
    ok, reason, moment = top_moment_entry_allowed(
        _evidence(tier="EXPLODING", flatThenVertical=True, activeBreakout=True),
        _ranking("B"),
    )
    assert ok is True
    assert reason == "ok"
    assert moment == "EXPLODING"


def test_momentum_rally_day_mode_allows_grade_b():
    ok, reason, moment = top_moment_entry_allowed(
        _evidence(tier="BUILDING", vRipReady=True),
        _ranking("B"),
        day_mode="MOMENTUM RALLY",
    )
    assert ok is True
    assert reason == "ok"
    assert moment == "V"


def test_top_moment_blocks_without_moment_type():
    ok, reason, _ = top_moment_entry_allowed(
        _evidence(
            tier="BUILDING",
            flatThenVertical=False,
            activeBreakout=False,
        ),
        _ranking("A"),
    )
    assert ok is False
    assert reason == "top_moment_requires_ftv_v_elite_or_exploding"


def test_explosion_alert_is_top_moment_building_helpers():
    alert = {
        "tier": "BUILDING",
        "ictBuildingRipReady": True,
        "buildingRipHelpersOk": True,
    }
    assert explosion_alert_is_top_moment(alert) is True


def test_explosion_alert_is_top_moment_elite():
    assert explosion_alert_is_top_moment({"tier": "ELITE"}) is True


def test_explosion_alert_is_top_moment_cold_building():
    assert explosion_alert_is_top_moment({"tier": "BUILDING"}) is False


def test_explosion_alert_is_top_moment_watch_local_base_low_score():
    alert = {
        "tier": "WATCH",
        "offLowMovePct": 3.0,
        "localBaseMovePct": 5.0,
        "explosionScore": 12.8,
        "velocity3s": 0.15,
        "velocity9s": 0.08,
        "volumeAwaken": True,
        "ictBaseArmed": True,
    }
    assert explosion_alert_is_top_moment(alert) is True


def test_classify_watch_local_base_pad_is_ftv():
    assert (
        classify_top_moment_type(
            {
                "tier": "WATCH",
                "offLowMovePct": 3.0,
                "localBaseMovePct": 5.0,
                "explosionScore": 12.8,
                "velocity3s": 0.15,
                "velocity9s": 0.08,
                "volumeAwakening": True,
                "baseArmed": True,
            }
        )
        == "FTV"
    )


def test_disabled_gate_passes():
    ok, reason, _ = top_moment_entry_allowed(
        _evidence(tier="BUILDING"),
        _ranking("C"),
        top_moments_only_enabled=False,
    )
    assert ok is True
    assert reason == "disabled"


def test_classify_slow_grind_building_without_structure_blocked():
    assert (
        classify_top_moment_type(
            _evidence(
                tier="BUILDING",
                slowGrindSuddenLift=True,
                flatThenVertical=False,
                activeBreakout=False,
            )
        )
        is None
    )


def test_classify_slow_grind_building_with_flat_vertical_at_base_is_ftv():
    assert (
        classify_top_moment_type(
            _evidence(
                tier="BUILDING",
                slowGrindSuddenLift=True,
                flatThenVertical=True,
                armedBaseLaunch=True,
            )
        )
        == "FTV"
    )


def test_classify_slow_grind_elite_still_ftv():
    assert (
        classify_top_moment_type(
            _evidence(tier="ELITE", slowGrindSuddenLift=True)
        )
        == "FTV"
    )


def test_explosion_alert_blocks_building_slow_grind_coil_only():
    alert = {
        "tier": "BUILDING",
        "slowGrindSuddenLiftReady": True,
        "ictFlatThenVertical": False,
        "ictBreakout": False,
    }
    assert explosion_alert_is_top_moment(alert) is False


def test_qualifies_for_top_moment_max_lots_elite():
    from app.engines.top_moment_gate import qualifies_for_top_moment_max_lots

    ok, reason, moment = qualifies_for_top_moment_max_lots(
        _evidence(tier="ELITE", armedBaseLaunch=True),
        _ranking("A"),
    )
    assert ok is True
    assert reason == "ok"
    assert moment == "ELITE"


def test_qualifies_for_top_moment_max_lots_blocks_generic_building():
    from app.engines.top_moment_gate import qualifies_for_top_moment_max_lots

    ok, reason, moment = qualifies_for_top_moment_max_lots(
        _evidence(
            tier="BUILDING",
            flatThenVertical=False,
            activeBreakout=False,
        ),
        _ranking("A"),
    )
    assert ok is False
    assert reason == "top_moment_requires_ftv_v_elite_or_exploding"
    assert moment is None


def test_explosion_alert_is_top_moment_slow_grind_stamp():
    alert = {
        "tier": "BUILDING",
        "slowGrindSuddenLiftReady": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
    }
    assert explosion_alert_is_top_moment(alert) is True


def test_top_moment_allows_slow_grind_flat_velocity():
    ok, reason, moment = top_moment_entry_allowed(
        _evidence(
            tier="BUILDING",
            slowGrindSuddenLift=True,
            velocity3s=-0.3,
            flatThenVertical=True,
            activeBreakout=True,
        ),
        _ranking("A"),
    )
    assert ok is True
    assert reason == "ok"
    assert moment == "FTV"


@pytest.mark.parametrize(
    "flag,v3",
    [
        ("squeezeRelease", -0.4),
        ("indexLedOptionLag", -0.2),
        ("stealthCvdCoil", -0.3),
        ("microPullbackRetest", -0.8),
        ("premiumFvgPad", -0.5),
        ("doubleDipVbase", -0.3),
    ],
)
def test_top_moment_allows_pad_lane_flat_velocity(flag, v3):
    ok, reason, moment = top_moment_entry_allowed(
        _evidence(
            tier="BUILDING",
            velocity3s=v3,
            velocity9s=0.1,
            flatThenVertical=True,
            activeBreakout=True,
            **{flag: True},
        ),
        _ranking("A"),
    )
    assert ok is True
    assert reason == "ok"
    assert moment == "FTV"


@pytest.mark.parametrize(
    "flag,stamp_key",
    [
        ("squeezeRelease", "squeezeReleaseReady"),
        ("indexLedOptionLag", "indexLedOptionLagReady"),
        ("stealthCvdCoil", "stealthCvdCoilReady"),
        ("microPullbackRetest", "microPullbackRetestReady"),
        ("premiumFvgPad", "premiumFvgPadReady"),
        ("doubleDipVbase", "doubleDipVbaseReady"),
    ],
)
def test_explosion_alert_is_top_moment_pad_lane_stamp(flag, stamp_key):
    alert = {
        "tier": "BUILDING",
        stamp_key: True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
    }
    assert explosion_alert_is_top_moment(alert) is True


def test_qualifies_for_top_moment_max_lots_disabled():
    from app.engines.top_moment_gate import qualifies_for_top_moment_max_lots

    ok, reason, _ = qualifies_for_top_moment_max_lots(
        _evidence(tier="BUILDING"),
        _ranking("C"),
        top_moments_max_lots_only_enabled=False,
    )
    assert ok is True
    assert reason == "disabled"
