"""Explosion scan applies NIFTY expiry parity floor without SymbolSnapshot."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import _premium_ok_for_scan
from app.engines.premium_filter import premium_in_band
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def test_premium_in_band_nifty_expiry_hint_sub_18():
    s = settings_mock(nifty_expiry_sensex_parity_enabled=True)
    assert premium_in_band(
        12.0,
        mode="explosion",
        peak_move_pct=20.0,
        symbol="NIFTY",
        expiry_day_hint=True,
        settings=s,
    )


def test_premium_ok_for_scan_nifty_expiry_coil():
    s = settings_mock(nifty_expiry_sensex_parity_enabled=True)
    assert _premium_ok_for_scan(
        12.0,
        18.0,
        s,
        symbol="NIFTY",
        expiry_day=True,
        moneyness="ATM",
        open_window=True,
        near_atm=True,
    )
