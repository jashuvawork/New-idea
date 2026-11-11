"""Capital-tier entry symbols — SENSEX-only below ₹2L book."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.bad_day_routing import cross_index_rank_adjustment
from app.engines.capital_allocator import (
    CapitalSnapshot,
    effective_entry_symbols,
    entry_capital_book_inr,
    entry_symbol_allowed,
    expiry_index_priority_suppressed,
)
from app.engines.open_index_lane import allowed_open_lane_sides
from app.models.schemas import AutoTraderState, MarketPhase, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap_capital(inr: float) -> CapitalSnapshot:
    return CapitalSnapshot(
        availableMarginInr=inr,
        totalEquityInr=inr,
        source="fallback",
        perTradeRiskInr=inr * 0.9,
        perTradeCapitalInr=inr * 0.9,
        maxExposureInr=inr * 0.9,
        minLots=1,
        targetLots=1,
        maxLots=1,
    )


@patch("app.engines.capital_allocator.get_capital_snapshot")
def test_below_2l_sensex_only(mock_cap):
    settings = Settings()
    settings.symbols_csv = "NIFTY,SENSEX"
    settings.capital_tier_entry_symbols_enabled = True
    settings.capital_tier_nifty_min_inr = 200_000
    settings.capital_tier_symbols_below_inr_csv = "SENSEX"
    mock_cap.return_value = _snap_capital(35_000)
    assert entry_capital_book_inr(settings) == 35_000
    assert effective_entry_symbols(settings) == frozenset({"SENSEX"})
    assert entry_symbol_allowed("NIFTY", settings) == (False, "below_capital_tier_symbol_blocked")
    assert entry_symbol_allowed("SENSEX", settings) == (True, "ok")


@patch("app.engines.capital_allocator.get_capital_snapshot")
def test_above_2l_both_indices(mock_cap):
    settings = Settings()
    settings.symbols_csv = "NIFTY,SENSEX"
    settings.capital_tier_entry_symbols_enabled = True
    settings.capital_tier_nifty_min_inr = 200_000
    mock_cap.return_value = _snap_capital(250_000)
    assert effective_entry_symbols(settings) == frozenset({"NIFTY", "SENSEX"})
    assert entry_symbol_allowed("NIFTY", settings)[0] is True


@patch("app.engines.capital_allocator.get_capital_snapshot")
def test_exactly_2l_still_sensex_only(mock_cap):
    settings = Settings()
    settings.symbols_csv = "NIFTY,SENSEX"
    settings.capital_tier_entry_symbols_enabled = True
    mock_cap.return_value = _snap_capital(200_000)
    assert effective_entry_symbols(settings) == frozenset({"SENSEX"})


def _index_snap(symbol: str, expiry: str) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime(2026, 11, 3, 9, 20, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=23300.0 if symbol == "NIFTY" else 73000.0,
        dataAvailable=True,
        optionExpiry=expiry,
    )


@patch("app.engines.capital_allocator.get_capital_snapshot")
def test_expiry_priority_suppressed_below_2l(mock_cap):
    settings = Settings()
    settings.capital_tier_entry_symbols_enabled = True
    settings.capital_tier_nifty_min_inr = 200_000
    mock_cap.return_value = _snap_capital(35_000)
    assert expiry_index_priority_suppressed(settings) is True
    mock_cap.return_value = _snap_capital(250_000)
    assert expiry_index_priority_suppressed(settings) is False


@patch("app.engines.capital_allocator.get_capital_snapshot")
def test_open_lanes_legacy_sensex_ce_pe_on_nifty_expiry_week(mock_cap):
    """Tue NIFTY expiry week: tier off → SENSEX PE-only open lane; tier on → SENSEX CE+PE."""
    snapshots = {
        "NIFTY": _index_snap("NIFTY", "2026-11-03"),
        "SENSEX": _index_snap("SENSEX", "2026-11-05"),
    }
    mock_cap.return_value = _snap_capital(35_000)
    tier_on = Settings(
        open_session_expiry_lane_enabled=True,
        open_sensex_call_lane_enabled=True,
        open_sensex_put_lane_enabled=True,
        capital_tier_entry_symbols_enabled=True,
        capital_tier_nifty_min_inr=200_000,
    )
    assert allowed_open_lane_sides("SENSEX", tier_on, snapshots=snapshots) == {
        "CALL",
        "PUT",
    }

    tier_off = Settings(
        open_session_expiry_lane_enabled=True,
        open_sensex_call_lane_enabled=True,
        capital_tier_entry_symbols_enabled=False,
    )
    assert allowed_open_lane_sides("SENSEX", tier_off, snapshots=snapshots) == {"PUT"}


@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.capital_allocator.get_capital_snapshot")
def test_cross_index_rank_skips_expiry_bonus_when_tier_active(mock_cap, mock_settings):
    mock_cap.return_value = _snap_capital(35_000)
    settings = Settings(
        bad_day_routing_enabled=True,
        expiry_day_prefer_same_day_enabled=True,
        expiry_day_symbol_rank_bonus=22.0,
        capital_tier_entry_symbols_enabled=True,
        capital_tier_nifty_min_inr=200_000,
    )
    mock_settings.return_value = settings
    snaps = {
        "NIFTY": _index_snap("NIFTY", "2026-11-03"),
        "SENSEX": _index_snap("SENSEX", "2026-11-05"),
    }
    state = AutoTraderState()

    class _Cand:
        symbol = "NIFTY"
        snap = snaps["NIFTY"]

    assert cross_index_rank_adjustment(_Cand(), state, snaps) == 0.0
