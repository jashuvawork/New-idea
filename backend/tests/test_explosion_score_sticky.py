"""Explosion score peak-hold — stops bursty velocity flickering score below gates."""

from app.engines.explosion_detector import (
    _apply_sticky_score,
    reset_detector_state_for_tests,
)


def setup_function(_):
    reset_detector_state_for_tests()


def test_score_held_through_velocity_dip():
    """SENSEX 76500 PE Jul23 profile: 71 → 36 → 44 in one sustained rip → held ~71."""
    k = "SENSEX:PUT:76500"
    assert _apply_sticky_score(k, 71.0, "EXPLODING") == 71.0
    assert _apply_sticky_score(k, 36.0, "EXPLODING") >= 62  # held, not flickered
    assert _apply_sticky_score(k, 44.0, "ELITE") >= 62


def test_score_upgrades_to_new_peak():
    k = "NIFTY:CALL:24000"
    _apply_sticky_score(k, 60.0, "EXPLODING")
    assert _apply_sticky_score(k, 88.0, "ELITE") == 88.0  # new higher peak wins


def test_watch_noise_not_stuck_high():
    """A low WATCH read shouldn't create a sticky high for a strike with no rip."""
    k = "NIFTY:PUT:23000"
    out = _apply_sticky_score(k, 20.0, "WATCH")
    assert out == 20.0


def test_isolated_strikes_do_not_bleed():
    _apply_sticky_score("SENSEX:PUT:76500", 90.0, "ELITE")
    other = _apply_sticky_score("SENSEX:CALL:77000", 30.0, "BUILDING")
    assert other == 30.0
