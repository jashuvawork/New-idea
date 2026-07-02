"""Regression — auto_trader must import resolve_trade_premium for exit cycles."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.auto_trader import _find_premium
from app.models.schemas import Breadth, HeatmapStrike, MarketPhase, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        breadth=Breadth(score=50, bias="NEUTRAL", aligned=False),
        heatmap=[
            HeatmapStrike(
                strike=24000,
                callLtp=100.0,
                putLtp=95.0,
                callInstrumentKey="NSE_FO|12345",
                putInstrumentKey="NSE_FO|67890",
            ),
        ],
    )


def test_find_premium_uses_resolve_trade_premium():
    snap = _snap()
    assert _find_premium(snap, 24000, Side.CALL) == 100.0


@patch("app.engines.auto_trader.get_settings")
@patch("app.engines.auto_trader._risk_engine")
def test_process_open_trades_imports_resolve_trade_premium(mock_risk, mock_settings):
    """Exit loop must not raise NameError on resolve_trade_premium."""
    from app.engines.auto_trader import _process_open_trades, get_state
    from app.models.schemas import AutoTraderState, PaperTrade, StrategyType

    settings = MagicMock()
    settings.adaptive_exits_enabled = False
    settings.explosion_capture_mode = True
    settings.swing_trading_enabled = False
    settings.enable_live_trading = False
    settings.paper_live_parity_enabled = False
    settings.edge_engine_enabled = False
    mock_settings.return_value = settings

    trade = PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24000,
        entryPremium=100.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"explosionTier": "BUILDING", "instrumentKey": "NSE_FO|12345"},
    )
    state = AutoTraderState(openPaperTrades=[trade])
    import app.engines.auto_trader as at

    at._auto_trader_state = state

    import asyncio

    result = asyncio.run(_process_open_trades(state, {"NIFTY": _snap()}, None))
    assert isinstance(result, list)
