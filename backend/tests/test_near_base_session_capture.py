"""Open slide + rally-off-low near-base capture (Sep29 class)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config import Settings
from app.engines.explosion_detector import (
    reset_detector_state_for_tests,
    scan_chain_explosions,
)
from app.engines.near_base_session_capture import (
    evidence_cheap_base_pad,
    ftv_session_capture_waives_atm_itm,
    otm_tradeable_preserved,
    session_capture_local_base_cap_pct,
    stamp_cheap_base_otm_tradeable,
)
from app.models.schemas import Side


def test_cheap_base_pad_evidence_nifty_otm():
    ev = {
        "symbol": "NIFTY",
        "tier": "BUILDING",
        "premium": 33.0,
        "localBaseMovePct": 8.0,
        "offLowMovePct": 12.0,
        "volumeAwaken": True,
    }
    assert evidence_cheap_base_pad(ev, settings=Settings()) is True


def test_ftv_waives_atm_itm_on_cheap_base_stamp():
    ev = {"tier": "BUILDING", "cheapBaseOtmCapture": True, "side": "CALL"}
    assert ftv_session_capture_waives_atm_itm(ev, settings=Settings()) is True


def test_otm_tradeable_preserved_cheap_base():
    assert otm_tradeable_preserved({"cheapBaseOtmCapture": True}) is True


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_fingerprint", return_value=True)
def test_session_capture_widens_call_local_cap(_rally):
    snap = MagicMock(symbol="NIFTY")
    cap = session_capture_local_base_cap_pct(
        "CALL",
        settings=Settings(near_base_session_capture_max_local_pct=28.0),
        evidence={"symbol": "NIFTY", "side": "CALL", "localBaseMovePct": 10.0, "premium": 40.0},
        state=MagicMock(),
        snap=snap,
    )
    assert cap is not None and cap >= 28.0


def test_stamp_cheap_base_sets_tradeable():
    snap = MagicMock(symbol="NIFTY")
    alert = {
        "symbol": "NIFTY",
        "tier": "BUILDING",
        "premium": 42.0,
        "localBaseMovePct": 6.0,
        "offLowMovePct": 8.0,
        "volumeAwaken": True,
    }
    assert stamp_cheap_base_otm_tradeable(alert, snap=snap) is True
    assert alert.get("tradeable") is True


@patch("app.engines.session_timing.in_open_premium_window", return_value=True)
def test_non_expiry_open_detects_shallow_otm_put(_open):
    """Sep29-style open slide: cheap OTM PUT off chain day-low without expiry day."""
    reset_detector_state_for_tests()
    chain = [
        {
            "strike_price": 22800.0,
            "put_options": {
                "ltp": 18.0,
                "volume": 90000,
                "day_low": 14.0,
                "low": 14.0,
                "close_price": 15.0,
            },
            "call_options": {"ltp": 55.0, "volume": 100000},
        },
        {
            "strike_price": 22750.0,
            "put_options": {"ltp": 22.0, "volume": 80000, "day_low": 18.0, "low": 18.0},
            "call_options": {"ltp": 70.0, "volume": 100000},
        },
    ]
    events = scan_chain_explosions(
        "NIFTY",
        chain,
        spot=22720.0,
        atm=22750.0,
        expiry_day=False,
    )
    puts = [e for e in events if e.side == Side.PUT and e.strike == 22800.0]
    assert puts, "expected shallow OTM PUT on radar at open (non-expiry)"

