"""Explosion near-miss waivers — grade inference + armed-base pad lag relief."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.rally_capture import (
    armed_base_pad_near_miss_waive,
    explosion_near_miss_waive,
    infer_alert_causal_grade,
    near_strike_armed_near_miss_waive,
)


def _settings(**overrides):
    s = SimpleNamespace(
        near_strike_armed_near_miss_waive_enabled=True,
        near_strike_armed_near_miss_min_grade="S",
        near_strike_armed_near_miss_max_steps=2,
        near_strike_armed_near_miss_max_local_pct=15.0,
        armed_base_pad_near_miss_waive_enabled=True,
        armed_base_pad_near_miss_min_explosion_score=80.0,
        armed_base_pad_near_miss_max_local_pct=15.0,
    )
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_infer_grade_s_without_stamped_causal_grade():
    """Sep07 23750 PE — grade-S evidence but causalGrade not stamped yet."""
    alert = {
        "tier": "ELITE",
        "explosionScore": 268.0,
        "strikeStepsFromAtm": 2,
        "moneyness": "OTM",
        "ictArmedBaseLaunch": True,
        "momentType": "armed_base_launch",
        "localBaseMovePct": 8.0,
        "volumeAwaken": True,
        "velocity3s": 2.5,
        "velocity9s": 2.0,
    }
    assert infer_alert_causal_grade(alert) == "S"


def test_near_strike_waive_without_stamped_causal_grade():
    alert = {
        "tier": "ELITE",
        "explosionScore": 268.0,
        "strikeStepsFromAtm": 2,
        "moneyness": "OTM",
        "ictArmedBaseLaunch": True,
        "momentType": "armed_base_launch",
        "localBaseMovePct": 8.0,
        "volumeAwaken": True,
        "velocity3s": 2.5,
        "velocity9s": 2.0,
    }
    with patch(
        "app.engines.rally_capture.get_settings",
        return_value=_settings(),
    ):
        assert near_strike_armed_near_miss_waive(alert) is True


def test_armed_base_pad_waive_high_score_at_local_base():
    alert = {
        "tier": "ELITE",
        "explosionScore": 120.0,
        "ictArmedBaseLaunch": True,
        "localBaseMovePct": 10.0,
        "moneyness": "OTM",
        "strikeStepsFromAtm": 2,
        "volumeAwaken": True,
    }
    with patch(
        "app.engines.rally_capture.get_settings",
        return_value=_settings(),
    ):
        assert armed_base_pad_near_miss_waive(alert) is True


def test_armed_base_pad_blocks_chase_above_local_cap():
    alert = {
        "tier": "ELITE",
        "explosionScore": 120.0,
        "ictArmedBaseLaunch": True,
        "localBaseMovePct": 22.0,
    }
    with patch(
        "app.engines.rally_capture.get_settings",
        return_value=_settings(),
    ):
        assert armed_base_pad_near_miss_waive(alert) is False


def test_explosion_near_miss_blocks_velocity_failure():
    alert = {
        "tier": "ELITE",
        "explosionScore": 120.0,
        "ictArmedBaseLaunch": True,
        "localBaseMovePct": 8.0,
    }
    with patch(
        "app.engines.rally_capture.get_settings",
        return_value=_settings(),
    ):
        assert explosion_near_miss_waive(
            alert,
            readiness_reason="first_lift_live_velocity_negative",
        ) is False


def test_explosion_near_miss_call_mirror_v_rip_session_high():
    alert = {
        "tier": "EXPLODING",
        "explosionScore": 95.0,
        "strikeStepsFromAtm": 1,
        "moneyness": "OTM",
        "armedBaseLaunch": True,
        "momentType": "v_rip_session_high",
        "localBaseMovePct": 6.0,
        "volumeAwaken": True,
        "velocity3s": 2.0,
        "velocity9s": 1.8,
    }
    with patch(
        "app.engines.rally_capture.get_settings",
        return_value=_settings(),
    ):
        assert explosion_near_miss_waive(alert) is True
