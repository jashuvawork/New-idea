"""Upstox rate-limit cooldown helpers."""

import time
from unittest.mock import MagicMock, patch

from app.services.upstox import (
    clear_rate_limit_cooldown,
    rate_limit_active,
    rate_limit_cooldown_remaining,
    rate_limit_recovery_active,
    _trip_rate_limit_cooldown,
)


def _settings():
    s = MagicMock()
    s.upstox_rate_limit_cooldown_seconds = 30
    return s


@patch("app.services.upstox.get_settings", _settings)
def test_trip_and_clear_cooldown():
    clear_rate_limit_cooldown()
    assert not rate_limit_active()
    _trip_rate_limit_cooldown()
    assert rate_limit_active()
    assert rate_limit_cooldown_remaining() > 0
    clear_rate_limit_cooldown()
    assert not rate_limit_active()


@patch("app.services.upstox.get_settings", _settings)
def test_clear_sets_recovery_grace():
    clear_rate_limit_cooldown()
    assert rate_limit_recovery_active()
    assert not rate_limit_active()


@patch("app.services.upstox.get_settings", _settings)
def test_trip_does_not_shorten_existing_cooldown():
    clear_rate_limit_cooldown()
    _trip_rate_limit_cooldown()
    first_remaining = rate_limit_cooldown_remaining()
    time.sleep(0.05)
    _trip_rate_limit_cooldown()
    second_remaining = rate_limit_cooldown_remaining()
    assert second_remaining >= first_remaining - 0.1
