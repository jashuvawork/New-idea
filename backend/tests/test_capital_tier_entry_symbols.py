"""Capital-tier entry symbols — SENSEX-only below ₹2L book."""

from unittest.mock import MagicMock, patch

from app.engines.capital_allocator import (
    CapitalSnapshot,
    effective_entry_symbols,
    entry_capital_book_inr,
    entry_symbol_allowed,
)
from app.config import Settings


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
