"""Tick-fast exit path — WS LTP overlay and scan scheduling."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.snapshot_fast import overlay_snapshot_ltps, resolve_trade_premium
from app.models.schemas import (
    Breadth,
    HeatmapStrike,
    MarketPhase,
    Side,
    SymbolSnapshot,
)
from app.services.tick_store import record_tick, clear

IST = ZoneInfo("Asia/Kolkata")


def _snap(strike: float = 24000, call_ltp: float = 100.0, put_ltp: float = 95.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        breadth=Breadth(score=50, bias="NEUTRAL", aligned=False),
        heatmap=[
            HeatmapStrike(
                strike=strike,
                callLtp=call_ltp,
                putLtp=put_ltp,
                callInstrumentKey="NSE_FO|12345",
                putInstrumentKey="NSE_FO|67890",
            ),
        ],
    )


def test_resolve_trade_premium_prefers_ws_tick():
    clear()
    record_tick("NSE_FO|67890", 88.5)
    snap = _snap()
    premium = resolve_trade_premium(snap, 24000, Side.PUT, "NSE_FO|67890")
    assert premium == 88.5


def test_overlay_snapshot_ltps_updates_heatmap():
    clear()
    record_tick("NSE_FO|67890", 91.0)
    snap = _snap(put_ltp=80.0)
    out = overlay_snapshot_ltps({"NIFTY": snap})
    row = out["NIFTY"].heatmap[0]
    assert row.putLtp == 91.0


@patch("app.routers.market.get_settings")
@patch("app.routers.market.get_state")
@patch("app.routers.market.is_ws_active")
def test_can_run_tick_fast_requires_open_trades(mock_ws, mock_state, mock_settings):
    from app.routers.market import can_run_tick_fast, _cache

    settings = MagicMock()
    settings.tick_fast_exit_enabled = True
    mock_settings.return_value = settings
    mock_ws.return_value = True

    import app.routers.market as market_mod
    market_mod._cache = MagicMock(dataReady=True)

    st = MagicMock()
    st.openPaperTrades = []
    mock_state.return_value = st
    assert not can_run_tick_fast()

    st.openPaperTrades = [MagicMock()]
    assert can_run_tick_fast()


@patch("app.routers.market.get_settings")
def test_entry_scan_due_after_interval(mock_settings):
    import app.routers.market as market_mod
    from app.routers.market import entry_scan_due, mark_full_scan_done

    settings = MagicMock()
    settings.entry_scan_interval_ms = 250
    mock_settings.return_value = settings

    market_mod._last_full_scan_mono = 0.0
    assert entry_scan_due()

    mark_full_scan_done()
    assert not entry_scan_due()
