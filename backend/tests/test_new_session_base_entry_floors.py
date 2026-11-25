"""newSessionBase entry window / immature floors."""

from types import SimpleNamespace

from app.engines.explosion_entry_guards import (
    explosion_entry_window_blocked,
    immature_explosion_blocked,
)
from tests.mock_defaults import settings_mock


def _settings():
    return settings_mock()


def test_entry_window_allows_low_pad_when_new_session_base():
    event = SimpleNamespace(
        tier="BUILDING",
        explosion_score=30,
        premium=108.0,
        symbol="SENSEX",
        strike=83600.0,
        side="PUT",
        session_move_pct=12.0,
    )
    ict = SimpleNamespace(
        base_relative_move_pct=40.0,
        local_swing_base=True,
        flat_then_vertical=True,
        first_lift=True,
        volume_awakening=True,
        active=True,
        session_move_pct=12.0,
        armed_base_launch=False,
    )
    alert = {
        "newSessionBase": True,
        "newBaseKind": "session_trough",
        "localBaseMovePct": 8.0,
        "effectiveBasePremium": 100.0,
    }
    blocked, reason = explosion_entry_window_blocked(
        event,
        ict=ict,
        alert=alert,
    )
    assert blocked is False, reason


def test_immature_allows_low_pad_when_new_session_base():
    event = SimpleNamespace(
        tier="BUILDING",
        explosion_score=30,
        premium=104.0,
        symbol="SENSEX",
        strike=83600.0,
        side="PUT",
        session_move_pct=5.0,
    )
    ict = SimpleNamespace(
        base_relative_move_pct=0.0,
        local_swing_base=True,
        flat_then_vertical=True,
        first_lift=False,
        volume_awakening=True,
        active=True,
        session_move_pct=5.0,
        armed_base_launch=False,
    )
    alert = {
        "newSessionBase": True,
        "localBaseMovePct": 4.0,
        "effectiveBasePremium": 100.0,
    }
    blocked, reason = immature_explosion_blocked(event, ict=ict, alert=alert)
    assert blocked is False, reason