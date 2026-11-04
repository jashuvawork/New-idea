"""SENSEX tradeable LTP band ₹18–₹650 (NIFTY stays on global cap)."""

from app.engines.premium_filter import premium_in_band, resolve_premium_band_limits
from app.models.schemas import SymbolSnapshot
from tests.mock_defaults import settings_mock


def test_sensex_explosion_band_18_to_650_with_snap():
    s = settings_mock(
        max_option_premium_inr=350.0,
        explosion_max_premium_inr=350.0,
        sensex_min_option_premium_inr=18.0,
        sensex_max_option_premium_inr=650.0,
    )
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-11-04T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=76500.0,
        atmStrike=76500.0,
        dataAvailable=True,
    )
    lo, hi = resolve_premium_band_limits(
        mode="explosion", peak_move_pct=40.0, snap=snap, settings=s,
    )
    assert lo == 18.0
    assert hi == 650.0
    assert premium_in_band(
        389.65, mode="explosion", peak_move_pct=50.0, snap=snap, settings=s,
    ) is True
    assert premium_in_band(
        650.0, mode="explosion", peak_move_pct=50.0, snap=snap, settings=s,
    ) is True
    assert premium_in_band(
        651.0, mode="explosion", peak_move_pct=50.0, snap=snap, settings=s,
    ) is False
    assert premium_in_band(
        17.0, mode="explosion", peak_move_pct=50.0, snap=snap, settings=s,
    ) is False


def test_nifty_still_capped_at_global_350():
    s = settings_mock(
        max_option_premium_inr=350.0,
        explosion_max_premium_inr=350.0,
        explosion_ict_max_premium_inr=800.0,
        sensex_max_option_premium_inr=650.0,
    )
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-11-04T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=23700.0,
        atmStrike=23700.0,
        dataAvailable=True,
    )
    assert premium_in_band(
        340.0, mode="explosion", peak_move_pct=10.0, snap=snap, settings=s,
    ) is True
    assert premium_in_band(
        400.0, mode="explosion", peak_move_pct=10.0, snap=snap, settings=s,
    ) is False
    assert premium_in_band(
        500.0, mode="explosion", peak_move_pct=35.0, snap=snap, settings=s,
    ) is True
