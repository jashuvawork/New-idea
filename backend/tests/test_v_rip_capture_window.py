"""V-rip local-base capture window — Aug24 building_outside_capture_window fix."""

from types import SimpleNamespace
from unittest.mock import patch

from app.config import Settings
from app.engines.explosion_entry_guards import immature_explosion_blocked
from app.engines.morning_premium_capture import is_v_rip_local_base_capture_alert


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_v_rip_local_base_capture_admits_building_at_7pct_pad(mock_settings, _window):
    """Aug24 NIFTY PUT 24250 BUILDING v_rip at 7% pad is a capture event."""
    mock_settings.return_value = Settings()
    alert = {
        "tier": "BUILDING",
        "explosionScore": 55.6,
        "ictVRipReady": True,
        "momentType": "v_rip_session_low",
        "localBaseMovePct": 7.3,
        "ictBaseRelativeMovePct": 7.3,
    }
    assert is_v_rip_local_base_capture_alert(alert) is True


@patch("app.engines.explosion_entry_guards.get_settings")
def test_v_rip_immature_gate_admits_7pct_flat_vertical_pad(mock_settings):
    """Aug25 NIFTY PUT 24250 EXPLODING v_rip at 7.1% must not block immature_local_base."""
    mock_settings.return_value = Settings()
    event = SimpleNamespace(daily_move_pct=6.89, peak_move_pct=8.13)
    ict = SimpleNamespace(
        flat_then_vertical=True,
        local_swing_base=True,
        base_relative_move_pct=7.1,
        volume_awakening=True,
        v_rip_ready=True,
        armed_base_launch=False,
        session_move_pct=8.13,
        reasons=[],
    )
    blocked, reason = immature_explosion_blocked(event, ict=ict)
    assert blocked is False
    assert reason == ""


@patch("app.engines.explosion_entry_guards.get_settings")
def test_v_rip_immature_still_blocks_sub_pad_noise(mock_settings):
    """Sub-2% v_rip pad without volume awakening stays immature."""
    mock_settings.return_value = Settings()
    event = SimpleNamespace(daily_move_pct=1.5, peak_move_pct=1.5)
    ict = SimpleNamespace(
        flat_then_vertical=True,
        local_swing_base=True,
        base_relative_move_pct=1.2,
        volume_awakening=False,
        v_rip_ready=True,
        armed_base_launch=False,
        session_move_pct=1.5,
        reasons=[],
    )
    blocked, reason = immature_explosion_blocked(event, ict=ict)
    assert blocked is True
    assert "immature" in reason


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_v_rip_capture_rejects_outside_pad(mock_settings, _window):
    mock_settings.return_value = Settings()
    alert = {
        "tier": "BUILDING",
        "explosionScore": 55.6,
        "ictVRipReady": True,
        "localBaseMovePct": 30.0,
    }
    assert is_v_rip_local_base_capture_alert(alert) is False
