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
        "date": _at(9, 15).date(),
        "open": open_,
        "hi": hi,
        "lo": lo,
        "last": last,
        "fromCashOpen": True,
    }
    return SimpleNamespace(spot=last)


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_macro_idle_before_0925(side):
    """09:15–09:24 belongs to the cash-candle hold. The macro does not vote yet."""
    snap = _tape("NIFTY", open_=22300.0, hi=22310.0, lo=22290.0, last=22308.6)
    for clock in (_at(9, 15, 37), _at(9, 16, 18), _at(9, 20, 10)):
        blocked, reason, _ = open_side_confirmation(
            "NIFTY", side, snap, now=clock, settings=_settings(),
        )
        assert blocked is False
        assert reason == ""


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_first_bar_still_blocks_when_window_includes_the_open(side):
    """A start pulled back to 09:15 still refuses the unconfirmed first minute."""
    snap = _tape("NIFTY", open_=22300.0, hi=22310.0, lo=22290.0, last=22308.6)
    s = _settings(
        open_side_confirmation_start_hour=9,
        open_side_confirmation_start_minute=15,
    )
    blocked, reason, _ = open_side_confirmation(
        "NIFTY", side, snap, now=_at(9, 15, 37), settings=s,
    )
    assert blocked and reason == "open_side_unconfirmed_first_bar"


def test_oct13_rally_off_open_blocks_pe_allows_ce():
    """NIFTY V-up off the open: from 09:25, CE confirmed, PE blocked."""
    snap = _tape("NIFTY", open_=22300.0, hi=22410.0, lo=22285.0, last=22395.0)
    s = _settings()
    put_blocked, put_reason, _ = open_side_confirmation("NIFTY", Side.PUT, snap, now=_at(9, 25), settings=s)
    call_blocked, _, meta = open_side_confirmation("NIFTY", Side.CALL, snap, now=_at(9, 25), settings=s)
    assert put_blocked and put_reason == "open_side_put_index_not_below_open"
    assert call_blocked is False
    assert meta["movePct"] > 0.10


def test_slide_off_open_allows_pe_blocks_ce():
    snap = _tape("SENSEX", open_=72812.0, hi=72840.0, lo=72610.0, last=72625.0)
    s = _settings()
    put_blocked, _, _ = open_side_confirmation("SENSEX", Side.PUT, snap, now=_at(9, 26), settings=s)
    call_blocked, call_reason, _ = open_side_confirmation("SENSEX", Side.CALL, snap, now=_at(9, 26), settings=s)
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


def test_enabled_at_one_minute_by_default():
    s = Settings()
    assert s.open_side_confirmation_enabled is True
    assert s.open_side_confirmation_start_minute == 25
    assert s.open_side_confirmation_min_minutes == 1.0
    assert s.entry_earliest_minute == 15
    assert s.explosion_entry_earliest_minute == 15
    assert s.open_setup_start_minute == 15
    snap = _tape("NIFTY", open_=22300.0, hi=22410.0, lo=22285.0, last=22395.0)
    for clock in (_at(9, 15, 37), _at(9, 16, 18), _at(9, 20, 0)):
        blocked, reason, _ = open_side_confirmation("NIFTY", Side.CALL, snap, now=clock, settings=s)
        assert blocked is False
        assert reason == ""
    call_blocked, _, meta = open_side_confirmation("NIFTY", Side.CALL, snap, now=_at(9, 25), settings=s)
    assert call_blocked is False
    assert meta["movePct"] > 0.10


def test_confirmation_uses_live_day_open_not_the_preopen_tick():
    from app.models.schemas import ChartAnalysis

    index_tick_helpers._session_extremes["NIFTY"] = {
        "date": _at(9, 28).date(),
        "open": 22680.0,
        "hi": 22763.0,
        "lo": 22680.0,
        "last": 22748.0,
    }
    snap = SimpleNamespace(
        spot=22748.0,
        chartAnalysis=ChartAnalysis(
            institutional={
                "dayOpen": 22743.2,
                "dayHigh": 22786.9,
                "dayLow": 22699.8,
            }
        ),
    )
    blocked, reason, meta = open_side_confirmation(
        "NIFTY", Side.CALL, snap, now=_at(9, 28, 20), settings=_settings(),
    )
    assert blocked and reason == "open_side_call_index_not_above_open"
    assert meta["sessionOpen"] == 22743.2
