"""Open-window side confirmation from today's index tape (CE / PE mirrors)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines import index_tick_helpers
from app.engines.open_side_confirmation import open_side_confirmation
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _at(h: int, m: int, s: int = 0) -> datetime:
    return datetime(2026, 10, 13, h, m, s, tzinfo=IST)


def _settings(**kw) -> Settings:
    return Settings(open_side_confirmation_enabled=True, open_side_confirmation_min_minutes=1.0, **kw)


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
    """Oct 13 22300 PE entered 09:15:37 — neither side is confirmed in the first minute."""
    snap = _tape("NIFTY", open_=22300.0, hi=22310.0, lo=22290.0, last=22308.6)
    blocked, reason, _ = open_side_confirmation(
        "NIFTY", side, snap, now=_at(9, 15, 37), settings=_settings(),
    )
    assert blocked and reason == "open_side_unconfirmed_first_bar"


def test_oct13_rally_off_open_blocks_pe_allows_ce():
    """NIFTY V-up off the open: CE confirmed, PE blocked."""
    snap = _tape("NIFTY", open_=22300.0, hi=22410.0, lo=22285.0, last=22395.0)
    s = _settings()
    put_blocked, put_reason, _ = open_side_confirmation("NIFTY", Side.PUT, snap, now=_at(9, 16, 18), settings=s)
    call_blocked, _, meta = open_side_confirmation("NIFTY", Side.CALL, snap, now=_at(9, 16, 18), settings=s)
    assert put_blocked and put_reason == "open_side_put_index_not_below_open"
    assert call_blocked is False
    assert meta["movePct"] > 0.10


def test_slide_off_open_allows_pe_blocks_ce():
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


def test_on_from_0915_to_0945_and_first_order_stays_0920():
    s = Settings()
    assert s.open_side_confirmation_enabled is True
    assert s.open_caution_until_hour == 9 and s.open_caution_until_minute == 45
    assert s.entry_earliest_hour == 9 and s.entry_earliest_minute == 20
    assert s.explosion_entry_earliest_hour == 9 and s.explosion_entry_earliest_minute == 20


@pytest.mark.parametrize(
    "side,open_,hi,lo,last",
    [
        # Oct 1 09:31 NIFTY 22900 PE: index +0.09% above open — refused inside the window.
        (Side.PUT, 22545.0, 22580.0, 22530.0, 22565.0),
        # Oct 14 09:20 NIFTY 22650 CE: index -0.15% below open — refused inside the window.
        (Side.CALL, 22700.0, 22710.0, 22660.0, 22665.0),
    ],
)
def test_default_blocks_the_wrong_side_only_inside_0915_0945(side, open_, hi, lo, last):
    snap = _tape("NIFTY", open_=open_, hi=hi, lo=lo, last=last)
    blocked_open, _, _ = open_side_confirmation(
        "NIFTY", side, snap, now=_at(9, 25), settings=Settings(),
    )
    blocked_later, _, _ = open_side_confirmation(
        "NIFTY", side, snap, now=_at(9, 45), settings=Settings(),
    )
    assert blocked_open is True
    assert blocked_later is False
