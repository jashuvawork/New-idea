"""Aug31 NIFTY PUT 23950 — defensive_rip_top must use pad % not session peak."""

from unittest.mock import MagicMock

from app.engines.ict_breakout_monitor import _defensive_base_rip_top_allowed


def _settings(**overrides):
    s = MagicMock()
    s.ict_defensive_base_rip_require_top_quality = True
    s.ict_defensive_base_rip_min_score = 80.0
    s.ict_defensive_base_rip_min_quality = 70.0
    s.ict_defensive_base_rip_min_velocity_3s = 2.5
    s.top_ftv_a_pad_velocity_min_move_pct = 8.0
    s.top_ftv_a_pad_velocity_max_move_pct = 25.0
    s.ict_v_rip_pad_min_move_pct = 2.0
    s.ict_v_rip_max_move_pct = 25.0
    s.ict_v_rip_volume_awake_min_velocity_3s = 0.85
    s.ict_v_rip_min_velocity_3s = 1.2
    s.ict_first_lift_local_base_cold_velocity_3s = -1.5
    s.ict_v_rip_min_score = 40.0
    s.ict_v_rip_min_quality = 50.0
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def test_session_peak_above_pad_hi_blocks_without_pad_move():
    """Regression: session peak 25.3% > pad_hi disables bypass when base_move is peak."""
    settings = _settings()
    ok, reason = _defensive_base_rip_top_allowed(
        tier="EXPLODING",
        quality=81.0,
        score=81.0,
        velocity_3s=1.25,
        settings=settings,
        base_move_pct=25.29,
        volume_awake=True,
        v_rip_ready=True,
        armed_base_launch=False,
        first_lift=True,
    )
    assert ok is False
    assert reason == "defensive_rip_top_v3<2.5"


def test_pad_move_at_21pct_softens_velocity_for_first_lift_v_rip():
    """Aug31 live miss: lb=21%, peak=25.3%, v3=1.25 — pad lane must waive floor."""
    settings = _settings()
    ok, reason = _defensive_base_rip_top_allowed(
        tier="EXPLODING",
        quality=81.0,
        score=81.0,
        velocity_3s=1.25,
        settings=settings,
        base_move_pct=21.0,
        volume_awake=True,
        v_rip_ready=True,
        armed_base_launch=False,
        first_lift=True,
    )
    assert ok is True
    assert reason == "ok"


def test_extended_pad_above_25_still_blocked():
    settings = _settings()
    ok, reason = _defensive_base_rip_top_allowed(
        tier="EXPLODING",
        quality=81.0,
        score=81.0,
        velocity_3s=1.25,
        settings=settings,
        base_move_pct=26.0,
        volume_awake=True,
        v_rip_ready=True,
        armed_base_launch=False,
        first_lift=True,
    )
    assert ok is False
    assert reason == "defensive_rip_top_v3<2.5"
