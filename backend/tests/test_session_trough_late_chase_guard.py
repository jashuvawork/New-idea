"""Sep07 23700 PE: block entries far above session trough without confirmed lift."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.explosion_entry_guards import session_trough_late_chase_blocked
from app.models.schemas import Side


def _settings(**overrides):
    s = SimpleNamespace(
        explosion_session_trough_late_chase_enabled=True,
        explosion_session_trough_late_chase_min_lift_pct=0.50,
        explosion_session_trough_late_chase_grade_s_max_lift_pct=0.60,
        explosion_session_trough_late_chase_grade_s_max_steps=2,
        explosion_session_trough_first_lift_max_waive_lift_pct=0.40,
    )
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _event(premium=34.35):
    return SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23700.0,
        premium=premium,
    )


def test_blocks_sep07_23700_late_chase_without_first_lift():
    alert = {
        "causalGrade": "A",
        "strikeStepsFromAtm": 1,
        "moneyness": "ATM",
        "ictArmedBaseLaunch": True,
        "ictFirstLift": False,
        "momentType": "fast_bullish_local_base",
    }
    ict = SimpleNamespace(first_lift=False)
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        with patch(
            "app.engines.explosion_detector.get_session_low_premium",
            return_value=22.0,
        ):
            blocked, reason = session_trough_late_chase_blocked(
                _event(34.35),
                ict=ict,
                alert=alert,
            )
    assert blocked is True
    assert reason.startswith("explosion_session_trough_late_chase_")


def test_allows_near_trough_fresh_entry():
    alert = {
        "causalGrade": "A",
        "strikeStepsFromAtm": 2,
        "moneyness": "OTM",
        "ictArmedBaseLaunch": True,
        "ictFirstLift": False,
    }
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        with patch(
            "app.engines.explosion_detector.get_session_low_premium",
            return_value=22.0,
        ):
            blocked, _ = session_trough_late_chase_blocked(
                _event(30.4),
                alert=alert,
            )
    assert blocked is False


def test_allows_grade_s_near_strike_armed_launch_up_to_cap():
    alert = {
        "causalGrade": "S",
        "strikeStepsFromAtm": 2,
        "moneyness": "OTM",
        "ictArmedBaseLaunch": True,
        "ictFirstLift": False,
        "momentType": "armed_base_launch",
    }
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        with patch(
            "app.engines.explosion_detector.get_session_low_premium",
            return_value=22.0,
        ):
            blocked, _ = session_trough_late_chase_blocked(
                _event(34.0),
                alert=alert,
                ranking={"grade": "S"},
            )
    assert blocked is False


def test_blocks_grade_s_above_cap_even_with_armed_launch():
    alert = {
        "causalGrade": "S",
        "strikeStepsFromAtm": 2,
        "moneyness": "OTM",
        "ictArmedBaseLaunch": True,
        "momentType": "armed_base_launch",
    }
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        with patch(
            "app.engines.explosion_detector.get_session_low_premium",
            return_value=22.0,
        ):
            blocked, reason = session_trough_late_chase_blocked(
                _event(36.0),
                alert=alert,
                ranking={"grade": "S"},
            )
    assert blocked is True
    assert "explosion_session_trough_late_chase" in reason


def test_allows_when_first_lift_confirmed_near_trough():
    alert = {
        "causalGrade": "A",
        "ictFirstLift": True,
        "ictArmedBaseLaunch": True,
    }
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        with patch(
            "app.engines.explosion_detector.get_session_low_premium",
            return_value=22.0,
        ):
            blocked, _ = session_trough_late_chase_blocked(
                _event(30.0),
                alert=alert,
            )
    assert blocked is False


def test_blocks_stale_first_lift_far_above_trough():
    """Sep07 23700 @ 11:29: first_lift stamp must not waive 56%+ trough chase."""
    alert = {
        "causalGrade": "A",
        "ictFirstLift": True,
        "ictArmedBaseLaunch": True,
        "momentType": "first_lift_local_base",
    }
    ict = SimpleNamespace(first_lift=True)
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        with patch(
            "app.engines.explosion_detector.get_session_low_premium",
            return_value=22.0,
        ):
            blocked, reason = session_trough_late_chase_blocked(
                _event(34.35),
                ict=ict,
                alert=alert,
            )
    assert blocked is True
    assert "explosion_session_trough_late_chase" in reason
