"""Coil-top guard — BUILDING/WATCH must enter at local base, not consolidation ceiling."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app.engines.explosion_detector as ed
from app.engines.explosion_detector import _open_key
from app.engines.explosion_entry_guards import coil_top_entry_blocked
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = SimpleNamespace(
        explosion_coil_top_guard_enabled=True,
        explosion_coil_top_lookback_seconds=900.0,
        explosion_coil_top_min_run_pct=0.06,
        explosion_coil_top_max_run_pct=0.28,
        explosion_coil_top_max_position_frac=0.50,
        explosion_coil_top_tiers_csv="WATCH,BUILDING",
        explosion_coil_top_breakout_min_velocity_3s=2.0,
    )
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _seed(symbol, strike, side, prems, *, step_s=20.0):
    key = _open_key(symbol, strike, side)
    t0 = datetime(2026, 9, 4, 12, 0, 0, tzinfo=IST)
    from collections import deque

    ed._local_base_hist[key] = deque(
        (t0 + timedelta(seconds=step_s * i), float(p)) for i, p in enumerate(prems)
    )


def teardown_function(_):
    ed._local_base_hist.clear()


def test_blocks_sep04_style_building_entry_at_coil_top():
    """NIFTY 23900 CE: base ~135, coil high ~150, entry ~147 = top 80% of range."""
    prems = [135 + (i % 4) * 1.5 for i in range(25)] + [148, 149, 147]
    _seed("NIFTY", 23900.0, Side.CALL, prems)
    ev = SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL,
        strike=23900.0,
        premium=147.0,
        tier="BUILDING",
        velocity_3s=1.32,
    )
    with patch(
        "app.engines.explosion_entry_guards.get_settings",
        return_value=_settings(),
    ):
        blocked, reason = coil_top_entry_blocked(ev, tier="BUILDING", velocity_3s=1.32)
    assert blocked is True
    assert reason.startswith("coil_top_position_")


def test_allows_entry_at_local_base_floor():
    """Entry near window low inside the same coil — allowed."""
    prems = [135 + (i % 4) * 1.5 for i in range(25)] + [136, 137, 136.5]
    _seed("NIFTY", 23900.0, Side.CALL, prems)
    ev = SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL,
        strike=23900.0,
        premium=136.5,
        tier="BUILDING",
        velocity_3s=0.8,
    )
    with patch(
        "app.engines.explosion_entry_guards.get_settings",
        return_value=_settings(),
    ):
        blocked, _ = coil_top_entry_blocked(ev, tier="BUILDING", velocity_3s=0.8)
    assert blocked is False


def test_elite_hot_breakout_at_coil_top_allowed():
    """EXPLODING breakout with hot v3 may enter at coil top."""
    prems = [135 + (i % 4) * 1.5 for i in range(25)] + [148, 149, 147]
    _seed("NIFTY", 23900.0, Side.CALL, prems)
    ev = SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL,
        strike=23900.0,
        premium=147.0,
        tier="EXPLODING",
        velocity_3s=2.5,
    )
    with patch(
        "app.engines.explosion_entry_guards.get_settings",
        return_value=_settings(),
    ):
        blocked, _ = coil_top_entry_blocked(ev, tier="EXPLODING", velocity_3s=2.5)
    assert blocked is False


def test_watch_tier_symmetric_put_coil_top():
    prems = [80 + (i % 3) * 1.0 for i in range(25)] + [92, 93, 91.5]
    _seed("SENSEX", 76600.0, Side.PUT, prems)
    ev = SimpleNamespace(
        symbol="SENSEX",
        side=Side.PUT,
        strike=76600.0,
        premium=91.5,
        tier="WATCH",
        velocity_3s=0.6,
    )
    with patch(
        "app.engines.explosion_entry_guards.get_settings",
        return_value=_settings(),
    ):
        blocked, reason = coil_top_entry_blocked(ev, tier="WATCH", velocity_3s=0.6)
    assert blocked is True
    assert "coil_top" in reason
