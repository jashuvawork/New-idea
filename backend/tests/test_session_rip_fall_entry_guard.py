"""Session rip → fall-leg entry block (Nov 25 SENSEX 83600 PE rollover)."""

from types import SimpleNamespace
from unittest.mock import patch

import app.engines.explosion_detector as ed
from app.engines.explosion_detector import _open_key
from app.engines.explosion_entry_guards import explosion_session_rip_fall_entry_blocked
from app.models.schemas import Side
from tests.mock_defaults import settings_mock


def _settings(**overrides):
    s = settings_mock()
    s.explosion_session_rip_fall_entry_block_enabled = True
    s.explosion_session_rip_fall_min_session_run_pct = 0.35
    s.explosion_session_rip_fall_min_fall_from_peak_pct = 0.08
    s.explosion_session_rip_fall_min_lift_from_trough_pct = 0.28
    s.explosion_session_rip_fall_max_velocity_3s = 1.25
    s.explosion_session_rip_fall_max_momentum5_pct = 8.0
    s.explosion_session_rip_fall_near_trough_max_lift_pct = 0.18
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _seed_session(symbol, strike, side, low, peak):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    key = _open_key(symbol, strike, side)
    ed._session_low[key] = float(low)
    ed._session_peak[key] = float(peak)
    ed._session_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")


def teardown_function(_):
    ed._session_low.clear()
    ed._session_peak.clear()


def test_blocks_nov25_style_rollover_after_rip():
    _seed_session("SENSEX", 83600.0, Side.PUT, 175.0, 550.0)
    ev = SimpleNamespace(
        symbol="SENSEX",
        side=Side.PUT,
        strike=83600.0,
        premium=429.0,
        velocity_3s=0.4,
    )
    blocked, reason, meta = explosion_session_rip_fall_entry_blocked(
        ev,
        settings=_settings(),
        momentum5_pct=2.0,
    )
    assert blocked is True
    assert reason == "explosion_session_rip_fall_entry"
    assert meta["fallFromPeakPct"] > 15


def test_allows_near_session_trough_base_put():
    _seed_session("SENSEX", 83600.0, Side.PUT, 175.0, 550.0)
    ev = SimpleNamespace(
        symbol="SENSEX",
        side=Side.PUT,
        strike=83600.0,
        premium=195.0,
        velocity_3s=2.5,
    )
    blocked, _, meta = explosion_session_rip_fall_entry_blocked(ev, settings=_settings())
    assert blocked is False
    assert meta.get("sessionRipFallExempt") == "near_session_trough"


def test_allows_hot_rip_continuation_call():
    _seed_session("SENSEX", 84400.0, Side.CALL, 85.0, 530.0)
    ev = SimpleNamespace(
        symbol="SENSEX",
        side=Side.CALL,
        strike=84400.0,
        premium=520.0,
        velocity_3s=3.5,
    )
    blocked, _, _ = explosion_session_rip_fall_entry_blocked(ev, settings=_settings())
    assert blocked is False


def test_disabled_is_noop():
    _seed_session("SENSEX", 83600.0, Side.PUT, 175.0, 550.0)
    ev = SimpleNamespace(
        symbol="SENSEX",
        side=Side.PUT,
        strike=83600.0,
        premium=429.0,
        velocity_3s=0.4,
    )
    blocked, _, _ = explosion_session_rip_fall_entry_blocked(
        ev,
        settings=_settings(explosion_session_rip_fall_entry_block_enabled=False),
    )
    assert blocked is False