"""SENSEX expiry book must not change when NIFTY expiry parity flag is on."""

from app.engines.expiry_day_guards import resolve_expiry_itm_scan_range
from app.engines.nifty_expiry_sensex_parity import (
    resolve_nifty_expiry_stop_abs_max_points,
)
from app.engines.premium_filter import resolve_premium_band_limits
from app.models.schemas import SymbolSnapshot
from tests.mock_defaults import settings_mock


def test_sensex_premium_band_unchanged_with_nifty_parity_on():
    s = settings_mock(
        nifty_expiry_sensex_parity_enabled=True,
        sensex_min_option_premium_inr=18.0,
        sensex_max_option_premium_inr=650.0,
        max_option_premium_inr=350.0,
        nifty_expiry_min_option_premium_inr=10.0,
        nifty_expiry_max_option_premium_inr=250.0,
    )
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-11-05T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=76500.0,
        atmStrike=76500.0,
        dataAvailable=True,
        optionExpiry="2026-11-05",
    )
    lo, hi = resolve_premium_band_limits(
        mode="explosion", peak_move_pct=40.0, snap=snap, settings=s,
    )
    assert lo == 18.0
    assert hi == 650.0


def test_sensex_scan_and_stops_not_nifty_parity():
    s = settings_mock(nifty_expiry_sensex_parity_enabled=True)
    assert resolve_expiry_itm_scan_range("SENSEX") == 1200.0
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-11-05T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=76500.0,
        atmStrike=76500.0,
        dataAvailable=True,
        optionExpiry="2026-11-05",
    )
    cap = resolve_nifty_expiry_stop_abs_max_points("SENSEX", snap, settings=s)
    assert cap is None
