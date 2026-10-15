"""Open-window side confirmation from today's index tape (CE / PE mirrors)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from unittest.mock import patch

from app.config import Settings
from app.engines import index_tick_helpers
from app.engines.open_side_confirmation import open_side_confirmation
from app.models.schemas import Side
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _at(h: int, m: int, s: int = 0) -> datetime:
    return datetime(2026, 10, 13, h, m, s, tzinfo=IST)


def _settings(**kw) -> Settings:
    return Settings(open_side_confirmation_enabled=True, **kw)


@pytest.fixture(autouse=True)
def _reset_tape():
    index_tick_helpers.reset_index_tick_helpers_for_tests()
    yield
    index_tick_helpers.reset_index_tick_helpers_for_tests()


def _tape(symbol: str, *, open_: float, hi: float, lo: float, last: float):
    index_tick_helpers._session_extremes[symbol] = {
        "date": _at(9, 15).date(), "open": open_, "hi": hi, "lo": lo, "last": last,
    }
    return SimpleNamespace(spot=last)


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_first_bar_blocks_both_sides(side):
    """Oct 13 22300 PE entered 09:15:37 — no side is confirmed in the first 5 minutes."""
    snap = _tape("NIFTY", open_=22300.0, hi=22310.0, lo=22290.0, last=22308.6)
    blocked, reason, _ = open_side_confirmation(
        "NIFTY", side, snap, now=_at(9, 15, 37), settings=_settings(),
    )
    assert blocked and reason == "open_side_unconfirmed_first_bar"


def test_oct13_rally_off_open_blocks_pe_allows_ce():
    """NIFTY V-up off the open: CE (+194%) confirmed, PE blocked."""
    snap = _tape("NIFTY", open_=22300.0, hi=22410.0, lo=22285.0, last=22395.0)
    s = _settings()
    put_blocked, put_reason, _ = open_side_confirmation("NIFTY", Side.PUT, snap, now=_at(9, 21), settings=s)
    call_blocked, _, meta = open_side_confirmation("NIFTY", Side.CALL, snap, now=_at(9, 21), settings=s)
    assert put_blocked and put_reason == "open_side_put_index_not_below_open"
    assert call_blocked is False
    assert meta["movePct"] > 0.10


def test_oct12_slide_off_open_allows_pe_blocks_ce():
    """Oct 12 SENSEX slide (72700 PE +214%): PE confirmed at 09:20, CE blocked."""
    snap = _tape("SENSEX", open_=72812.0, hi=72840.0, lo=72610.0, last=72625.0)
    s = _settings()
    put_blocked, _, _ = open_side_confirmation("SENSEX", Side.PUT, snap, now=_at(9, 20, 10), settings=s)
    call_blocked, call_reason, _ = open_side_confirmation("SENSEX", Side.CALL, snap, now=_at(9, 20, 10), settings=s)
    assert put_blocked is False
    assert call_blocked and call_reason == "open_side_call_index_not_above_open"


@pytest.mark.parametrize(
    "side,hi,lo,last,reason",
    [
        (Side.CALL, 22500.0, 22200.0, 22330.0, "open_side_call_not_in_upper_range"),
        (Side.PUT, 22400.0, 22100.0, 22270.0, "open_side_put_not_in_lower_range"),
    ],
)
def test_reversal_inside_range_blocks_ce_pe(side, hi, lo, last, reason):
    """Past the open in the side's direction, but faded back into the middle of the range."""
    snap = _tape("NIFTY", open_=22300.0, hi=hi, lo=lo, last=last)
    blocked, got, _ = open_side_confirmation("NIFTY", side, snap, now=_at(9, 25), settings=_settings())
    assert blocked and got == reason


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_no_session_tape_fails_closed_ce_pe(side):
    blocked, reason, _ = open_side_confirmation(
        "NIFTY", side, SimpleNamespace(spot=22300.0), now=_at(9, 25), settings=_settings(),
    )
    assert blocked and reason == "open_side_no_session_tape"


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_after_open_window_not_applied_ce_pe(side):
    snap = _tape("NIFTY", open_=22300.0, hi=22410.0, lo=22285.0, last=22300.0)
    blocked, _, _ = open_side_confirmation("NIFTY", side, snap, now=_at(9, 45), settings=_settings())
    assert blocked is False


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_disabled_by_default_ce_pe(side):
    assert Settings().open_side_confirmation_enabled is False
    blocked, _, _ = open_side_confirmation(
        "NIFTY", side, SimpleNamespace(spot=22300.0), now=_at(9, 15, 37), settings=Settings(),
    )
    assert blocked is False


def test_frozen_oct_one_minute_wait_allows_916_not_first_bar():
    """09:16 IST entries — not the Oct 13 09:15:37 blind side pick."""
    snap = _tape("NIFTY", open_=22300.0, hi=22410.0, lo=22285.0, last=22395.0)
    s = _settings(open_side_confirmation_min_minutes=1.0)
    blocked, reason, _ = open_side_confirmation(
        "NIFTY", Side.CALL, snap, now=_at(9, 16, 18), settings=s,
    )
    assert blocked is False
    blocked15, reason15, _ = open_side_confirmation(
        "NIFTY", Side.CALL, snap, now=_at(9, 15, 37), settings=s,
    )
    assert blocked15 and reason15 == "open_side_unconfirmed_first_bar"


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_oct_paper_session_first_lift_waives_open_side_before_index_confirms(side):
    s = settings_mock(
        october_frozen_profile_enabled=True,
        live_paper_parity_enabled=True,
        oct_paper_replica_enabled=True,
        open_side_confirmation_enabled=True,
        open_side_confirmation_min_minutes=1.0,
    )
    snap = _tape("NIFTY", open_=22300.0, hi=22310.0, lo=22290.0, last=22300.0)
    alert = {
        "tier": "ELITE",
        "explosionScore": 90.0,
        "side": side.value,
        "localBaseMovePct": 13.0,
        "sessionRangePosition": 0.4,
        "velocity3s": 5.0,
    }
    if side == Side.CALL:
        alert["offLowMovePct"] = 8.0
    else:
        alert["drawdownFromHighPct"] = 8.0
    with patch("app.engines.session_timing.in_open_premium_window", return_value=True):
        if side == Side.PUT:
            with patch(
                "app.engines.put_slide_ce_mirror.put_slide_pad_context", return_value=True,
            ):
                blocked, reason, meta = open_side_confirmation(
                    "NIFTY", side, snap, now=_at(9, 16, 5), settings=s, alert=alert,
                )
        else:
            blocked, reason, meta = open_side_confirmation(
                "NIFTY", side, snap, now=_at(9, 16, 5), settings=s, alert=alert,
            )
    assert blocked is False
    assert meta.get("openSideWaived") == "oct_paper_session_first_lift"
