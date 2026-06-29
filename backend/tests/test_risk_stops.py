"""Flat emergency stop — Jun 25 +₹66K profile (no position scaling)."""

from unittest.mock import patch

from app.engines.risk_stops import effective_emergency_stop_inr


@patch("app.engines.risk_stops.get_settings")
def test_emergency_disabled_returns_inf(mock_settings):
    settings = mock_settings.return_value
    settings.emergency_stop_enabled = False
    cap = effective_emergency_stop_inr(100, 65, 4.0)
    assert cap == float("inf")


@patch("app.engines.risk_stops.get_settings")
def test_emergency_flat_20k(mock_settings):
    settings = mock_settings.return_value
    settings.emergency_stop_enabled = True
    settings.emergency_stop_inr = 20_000
    settings.emergency_stop_scale_with_position = False
    cap = effective_emergency_stop_inr(100, 65, 4.0)
    assert cap == 20_000


@patch("app.engines.risk_stops.get_settings")
def test_emergency_scales_when_enabled(mock_settings):
    settings = mock_settings.return_value
    settings.emergency_stop_enabled = True
    settings.emergency_stop_inr = 12_000
    settings.emergency_stop_scale_with_position = True
    cap = effective_emergency_stop_inr(60, 65, 2.5)
    assert cap == 9750.0
