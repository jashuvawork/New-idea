"""V-rip local-base capture window — Aug24 building_outside_capture_window fix."""

from unittest.mock import patch

from app.config import Settings
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
