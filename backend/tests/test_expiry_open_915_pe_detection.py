"""9:15 expiry open — cheap shallow-OTM PUT must appear on radar (Sep 28 22800 PE class)."""

from __future__ import annotations

from unittest.mock import patch

from app.engines.explosion_detector import (
    reset_detector_state_for_tests,
    scan_chain_explosions,
)
from app.models.schemas import Side


@patch("app.engines.session_timing.in_open_premium_window", return_value=True)
def test_open_915_detects_shallow_otm_put_off_chain_low(_open):
    """22800 PE @ ₹12 off day-low ₹10 when spot ~22818 / ATM 22850."""
    reset_detector_state_for_tests()

    chain = [
        {
            "strike_price": 22800.0,
            "call_options": {"ltp": 55.0, "volume": 100000},
            "put_options": {
                "ltp": 12.0,
                "volume": 80000,
                "day_low": 10.0,
                "low": 10.0,
                "day_high": 14.0,
                "high": 14.0,
                "close_price": 10.5,
            },
        },
        {
            "strike_price": 22850.0,
            "call_options": {"ltp": 40.0, "volume": 100000},
            "put_options": {"ltp": 18.0, "volume": 90000, "day_low": 16.0, "low": 16.0},
        },
    ]
    events = scan_chain_explosions(
        "NIFTY",
        chain,
        spot=22818.0,
        atm=22850.0,
        expiry_day=True,
    )
    puts = [e for e in events if e.side == Side.PUT and e.strike == 22800.0]
    assert puts, "expected NIFTY 22800 PUT on radar at 9:15 open trough lift"
    assert puts[0].tier in ("BUILDING", "EXPLODING", "ELITE", "WATCH")


@patch("app.engines.session_timing.in_open_premium_window", return_value=True)
def test_open_915_prior_close_gap_triggers_scan(_open):
    """First poll with prior close ₹10 → ₹12 (+20%) must not be dropped."""
    reset_detector_state_for_tests()

    chain = [
        {
            "strike_price": 22850.0,
            "put_options": {
                "ltp": 12.0,
                "volume": 0,
                "close_price": 10.0,
                "day_low": 10.0,
                "low": 10.0,
            },
        },
    ]
    events = scan_chain_explosions(
        "NIFTY",
        chain,
        spot=22818.0,
        atm=22850.0,
        expiry_day=True,
    )
    puts = [e for e in events if e.side == Side.PUT and e.strike == 22850.0]
    assert puts, "ATM PUT should detect on prior-close gap at open"
