"""Sep07 23750 PE — selector near-miss resolves without stamped causalGrade."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.pad_lane_capture import pad_lane_early_near_miss_waive
from app.engines.rally_capture import explosion_near_miss_waive


def _settings(**overrides):
    s = SimpleNamespace(
        pad_lane_early_near_miss_waive_enabled=True,
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


def _sep07_23750_alert():
    return {
        "side": "PUT",
        "strike": 23750.0,
        "tier": "ELITE",
        "premium": 30.0,
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


def test_sep07_selector_near_miss_waives_without_causal_grade_stamp():
    alert = _sep07_23750_alert()
    with patch(
        "app.engines.rally_capture.get_settings",
        return_value=_settings(),
    ), patch(
        "app.engines.pad_lane_capture.get_settings",
        return_value=_settings(),
    ):
        assert explosion_near_miss_waive(
            alert,
            readiness_reason="first_lift_quality<65",
        ) is True
        assert pad_lane_early_near_miss_waive(
            alert,
            readiness_reason="first_lift_quality<65",
        ) is True
