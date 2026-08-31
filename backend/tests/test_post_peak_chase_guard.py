"""Live post-peak/post-trough chase guard — don't buy near the top of a completed run.

Symmetric for CE and PE (we always buy the option premium). A near-base entry is exempt
by construction (current premium sits at the recent window low); a late chase (current near
the window peak after a >=25% run) is blocked. Mirrors the Aug31 live PUT 23950 that bought
near the exhausted down-move low, V-reversed, and stopped out.
"""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from types import SimpleNamespace

import app.engines.explosion_detector as ed
from app.engines.explosion_detector import _open_key, recent_premium_run
from app.engines.explosion_entry_guards import post_peak_chase_blocked
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = SimpleNamespace(
        explosion_post_peak_chase_guard_enabled=True,
        explosion_post_peak_chase_lookback_seconds=900.0,
        explosion_post_peak_chase_min_run_pct=0.25,
        explosion_post_peak_chase_near_top_frac=0.12,
    )
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _seed(symbol, strike, side, prems, *, step_s=20.0):
    """Seed detector premium history with a (time, premium) series."""
    key = _open_key(symbol, strike, side)
    t0 = datetime(2026, 8, 31, 11, 0, 0, tzinfo=IST)
    from collections import deque

    ed._local_base_hist[key] = deque(
        (t0 + timedelta(seconds=step_s * i), float(p)) for i, p in enumerate(prems)
    )


def teardown_function(_):
    ed._local_base_hist.clear()


def test_blocks_chase_near_top_of_completed_run():
    # Premium ran 40 -> 130 (a completed +125% run), now sitting at 126 near the top.
    prems = [40 + i * 3 for i in range(30)] + [130, 128, 126]
    _seed("NIFTY", 23950.0, Side.PUT, prems)
    ev = SimpleNamespace(symbol="NIFTY", side=Side.PUT, strike=23950.0, premium=126.0)
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        blocked, reason = post_peak_chase_blocked(ev)
    assert blocked is True
    assert reason == "explosion_post_peak_chase"


def test_allows_near_base_entry():
    # Flat base ~40, current still at the base (a genuine near-base entry) -> allowed.
    prems = [40 + (i % 3) * 0.5 for i in range(30)] + [41.0]
    _seed("NIFTY", 24150.0, Side.CALL, prems)
    ev = SimpleNamespace(symbol="NIFTY", side=Side.CALL, strike=24150.0, premium=41.0)
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        blocked, _ = post_peak_chase_blocked(ev)
    assert blocked is False


def test_allows_early_lift_off_base():
    # Ran a little (40 -> 48, +20% < 25% min_run) — still early, not a spent move.
    prems = [40 + (i % 2) * 0.3 for i in range(28)] + [44, 46, 48]
    _seed("SENSEX", 76900.0, Side.CALL, prems)
    ev = SimpleNamespace(symbol="SENSEX", side=Side.CALL, strike=76900.0, premium=48.0)
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        blocked, _ = post_peak_chase_blocked(ev)
    assert blocked is False


def test_symmetric_put_chase_blocked():
    # PUT premium ran 50 -> 120 as the market fell, now 116 near the top = post-trough chase.
    prems = [50 + i * 2.5 for i in range(28)] + [120, 118, 116]
    _seed("SENSEX", 76500.0, Side.PUT, prems)
    ev = SimpleNamespace(symbol="SENSEX", side=Side.PUT, strike=76500.0, premium=116.0)
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        blocked, _ = post_peak_chase_blocked(ev)
    assert blocked is True


def test_disabled_is_noop():
    prems = [40 + i * 3 for i in range(30)] + [130, 128, 126]
    _seed("NIFTY", 23950.0, Side.PUT, prems)
    ev = SimpleNamespace(symbol="NIFTY", side=Side.PUT, strike=23950.0, premium=126.0)
    with patch(
        "app.engines.explosion_entry_guards.get_settings",
        return_value=_settings(explosion_post_peak_chase_guard_enabled=False),
    ):
        blocked, _ = post_peak_chase_blocked(ev)
    assert blocked is False


def test_recent_premium_run_reads_history():
    prems = [40 + i * 3 for i in range(30)] + [130, 128, 126]
    _seed("NIFTY", 23950.0, Side.PUT, prems)
    r = recent_premium_run("NIFTY", 23950.0, Side.PUT, lookback_seconds=900.0)
    assert r["high"] >= 126.0
    assert r["run"] > 0.25
    assert r["current"] == 126.0
