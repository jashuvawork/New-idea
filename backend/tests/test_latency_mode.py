"""Latency mode presets — cadence tuning for entry scan and market poll."""

import os
from unittest.mock import patch

import pytest

from app.config import get_settings, reset_settings_for_tests


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    reset_settings_for_tests()
    yield
    reset_settings_for_tests()


def test_aggressive_latency_preset_applied():
    with patch.dict(os.environ, {"LATENCY_MODE": "aggressive"}, clear=False):
        os.environ.pop("ENTRY_SCAN_INTERVAL_MS", None)
        s = get_settings()
    assert s.latency_mode == "aggressive"
    assert s.entry_scan_interval_ms == 500
    assert s.market_poll_interval_ws_ms == 50
    assert s.explosion_open_scan_interval_ms == 400


def test_explicit_env_overrides_latency_preset():
    reset_settings_for_tests()
    with patch.dict(
        os.environ,
        {"LATENCY_MODE": "aggressive", "ENTRY_SCAN_INTERVAL_MS": "900"},
        clear=False,
    ):
        s = get_settings()
    assert s.entry_scan_interval_ms == 900
    assert s.market_poll_interval_ws_ms == 50


def test_normal_latency_keeps_defaults():
    reset_settings_for_tests()
    with patch.dict(os.environ, {"LATENCY_MODE": "normal"}, clear=False):
        os.environ.pop("ENTRY_SCAN_INTERVAL_MS", None)
        s = get_settings()
    # Default tightened so base rips are caught in the 28-55% window before extending.
    assert s.entry_scan_interval_ms == 1000
