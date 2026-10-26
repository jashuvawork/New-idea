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


def _tape(symbol: str, *, open_: float, hi: float, lo: float, last: float, broker_day: bool = True):
    index_tick_helpers._session_extremes[symbol] = {
        "date": _at(9, 15).date(),
        "open": open_,
        "hi": hi,
        "lo": lo,
        "last": last,
        "fromCashOpen": True,
    }
    snap = SimpleNamespace(spot=last)
    if broker_day:
        from app.models.schemas import ChartAnalysis

        snap.chartAnalysis = ChartAnalysis(
            institutional={
                "dayOpen": open_,
                "dayHigh": hi,
                "dayLow": lo,
            }
        )
    return snap


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_before_0925_macro_gate_is_inactive(side):
    """09:15–09:24: PR #676 capture may run; macro index side check starts at 09:25."""
    snap = _tape("NIFTY", open_=22300.0, hi=22410.0, lo=22285.0, last=22395.0)
    for t in (_at(9, 15, 37), _at(9, 20, 10), _at(9, 24, 59)):
        blocked, reason, _ = open_side_confirmation(
            "NIFTY", side, snap, now=t, settings=_settings(),
        )
        assert blocked is False and reason == ""


def test_oct13_rally_off_open_blocks_pe_allows_ce():
    """NIFTY V-up off the open: CE confirmed, PE blocked (inside 09:25–09:45)."""
    snap = _tape("NIFTY", open_=22300.0, hi=22410.0, lo=22285.0, last=22395.0)
    s = _settings()
    put_blocked, put_reason, _ = open_side_confirmation("NIFTY", Side.PUT, snap, now=_at(9, 26), settings=s)
    call_blocked, _, meta = open_side_confirmation("NIFTY", Side.CALL, snap, now=_at(9, 26), settings=s)
    assert put_blocked and put_reason == "open_side_put_index_not_below_open"
    assert call_blocked is False
    assert meta["movePct"] > 0.10


def test_slide_off_open_allows_pe_blocks_ce():
    snap = _tape("SENSEX", open_=72812.0, hi=72840.0, lo=72610.0, last=72625.0)
    s = _settings()
    put_blocked, _, _ = open_side_confirmation("SENSEX", Side.PUT, snap, now=_at(9, 30), settings=s)
    call_blocked, call_reason, _ = open_side_confirmation("SENSEX", Side.CALL, snap, now=_at(9, 30), settings=s)
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


def test_cash_tick_tape_open_ok_without_broker_day_stamp():
    index_tick_helpers._session_extremes["NIFTY"] = {
        "date": _at(9, 25).date(),
        "open": 22300.0,
        "hi": 22320.0,
        "lo": 22295.0,
        "last": 22310.0,
        "fromCashOpen": True,
    }
    snap = SimpleNamespace(spot=22310.0)
    blocked, reason, _ = open_side_confirmation(
        "NIFTY", Side.CALL, snap, now=_at(9, 25), settings=_settings(),
    )
    assert blocked and reason == "open_side_call_index_not_above_open"


def test_pr676_waives_open_side_for_call_atm_itm_base_lift():
    from types import SimpleNamespace

    from app.models.schemas import ChartAnalysis, Side, SymbolSnapshot

    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-10-01T09:25:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=74005.0,
        atmStrike=74000.0,
        dataAvailable=True,
        chartAnalysis=ChartAnalysis(
            institutional={"dayOpen": 74000.0, "dayHigh": 74020.0, "dayLow": 73980.0},
        ),
    )
    index_tick_helpers._session_extremes["SENSEX"] = {
        "date": _at(9, 25).date(),
        "open": 74000.0,
        "hi": 74020.0,
        "lo": 73980.0,
        "last": 74005.0,
        "fromCashOpen": True,
    }
    cand = SimpleNamespace(
        mode="explosion",
        symbol="SENSEX",
        side=Side.CALL,
        strike=73900.0,
        alert={
            "tier": "EXPLODING",
            "armedBaseLaunch": True,
            "ictFirstLift": True,
            "localBaseMovePct": 11.0,
        },
        pretrade_meta={},
        snap=snap,
    )
    blocked, reason, meta = open_side_confirmation(
        "SENSEX",
        Side.CALL,
        snap,
        candidate=cand,
        now=_at(9, 25),
        settings=_settings(),
    )
    assert blocked is False
    assert meta.get("openSideCaptureWaived") == "call_atm_itm_base_capture"


def test_after_first_order_time_requires_broker_day_open():
    """Restart tick tape without broker dayOpen or cash-open stamp blocks from 09:25."""
    snap = _tape(
        "NIFTY", open_=22700.0, hi=22750.0, lo=22690.0, last=22740.0, broker_day=False,
    )
    index_tick_helpers._session_extremes["NIFTY"].pop("fromCashOpen", None)
    blocked, reason, meta = open_side_confirmation(
        "NIFTY", Side.CALL, snap, now=_at(9, 25), settings=_settings(),
    )
    assert blocked and reason == "open_side_broker_day_open_required"
    assert meta.get("tapeOpenOnly") is True


def test_broker_day_open_beats_a_preopen_tick_open():
    """A pre-open print as the tape open must not confirm a call that is flat to the cash open.

    Oct 23 09:28 Nifty was +0.02% from the cash open. Measuring from a 22680
    pre-open tick made that look like a confirmed rally.
    """
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
    assert meta["movePct"] < 0.10


def test_window_0925_to_0945_and_first_order_stays_0920():
    s = Settings()
    assert s.open_side_confirmation_enabled is False
    assert s.open_side_confirmation_start_hour == 9
    assert s.open_side_confirmation_start_minute == 25
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
def test_default_does_not_block_either_side_from_0915_to_0945(side, open_, hi, lo, last):
    """#676 has no index-side check from the cash open through 09:45."""
    snap = _tape("NIFTY", open_=open_, hi=hi, lo=lo, last=last)
    for minute in (15, 25, 40, 45):
        blocked, reason, _ = open_side_confirmation(
            "NIFTY", side, snap, now=_at(9, minute), settings=Settings(),
        )
        assert blocked is False
        assert reason == ""
    blocked_on, _, _ = open_side_confirmation(
        "NIFTY", side, snap, now=_at(9, 25), settings=_settings(),
    )
    assert blocked_on is True
