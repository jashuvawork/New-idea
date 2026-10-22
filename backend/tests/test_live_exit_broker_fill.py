"""Live exits book the broker average, not the snapshot that triggered the sell."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.paper_slippage import mark_to_market
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    HeatmapStrike,
    MarketPhase,
    PaperTrade,
    Side,
    StrategyType,
    SymbolSnapshot,
)
from app.services.order_executor import (
    live_order_fill,
    live_order_fill_complete,
    lots_fitting_broker_margin,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(ltp: float) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        breadth=Breadth(score=50, bias="NEUTRAL", aligned=False),
        heatmap=[
            HeatmapStrike(
                strike=23150,
                callLtp=ltp,
                putLtp=40.0,
                callInstrumentKey="NSE_FO|23150CE",
                putInstrumentKey="NSE_FO|23150PE",
            ),
        ],
    )


def test_live_order_fill_reads_average_price():
    class _Client:
        async def get_order_book(self):
            return [
                {"order_id": "other", "status": "complete", "average_price": 1},
                {
                    "order_id": "261016000188354",
                    "status": "complete",
                    "average_price": 79.67,
                    "filled_quantity": 1235,
                },
            ]

    fill = asyncio.run(live_order_fill(_Client(), "261016000188354"))
    assert live_order_fill_complete(fill)
    assert fill["averagePrice"] == 79.67


def test_live_exit_books_broker_average_not_trigger_mark():
    """23150 CE: trigger mark 82.70 booked +₹14,326. Broker average is the exit."""
    import app.engines.auto_trader as auto_trader
    from app.config import get_settings

    entry = 71.1
    mark = 82.7
    broker_average = 79.67
    lots = 19
    trade = PaperTrade(
        id="eb4a31f3",
        symbol="NIFTY",
        side=Side.CALL,
        strike=23150,
        entryPremium=entry,
        currentPremium=mark,
        lots=lots,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={
            "instrumentKey": "NSE_FO|23150CE",
            "brokerOrderId": "261016000179042",
            "brokerEntryFillPremium": entry,
            "brokerQuantity": lots * 65,
            "lotSize": 65,
            "brokerSimulated": False,
            "executionMode": "LIVE",
            "explosionTier": "EXPLODING",
        },
    )
    state = AutoTraderState(openPaperTrades=[trade])
    auto_trader._auto_trader_state = state
    auto_trader._state_loaded = True
    settings = get_settings().model_copy(
        update={
            "adaptive_exits_enabled": False,
            "edge_engine_enabled": False,
            "explosion_capture_mode": True,
            "enable_live_trading": True,
            "auto_trading_enabled": True,
            "paper_live_parity_enabled": False,
            "paper_trading": False,
        }
    )
    snapshots = {"NIFTY": _snap(mark)}
    fills = [
        {"status": "open", "averagePrice": 0.0, "filledQuantity": 0.0},
        {"status": "complete", "averagePrice": broker_average, "filledQuantity": 1235},
    ]

    async def _run():
        await auto_trader.process_exits_only(snapshots, client=MagicMock())
        assert trade.status == "OPEN"
        assert trade.entryContext["brokerExitOrderId"] == "exit-23150"
        await auto_trader.process_exits_only(snapshots, client=MagicMock())

    with (
        patch.object(auto_trader, "get_settings", return_value=settings),
        patch.object(
            auto_trader,
            "evaluate_explosion_exit",
            return_value=("explosion_peak_keep_trail", 11.6 * lots * 65),
        ),
        patch.object(auto_trader, "find_existing_exit_order", return_value=None),
        patch.object(
            auto_trader,
            "place_exit_order",
            return_value={"order_id": "exit-23150"},
        ) as place_exit,
        patch.object(auto_trader, "live_order_fill", side_effect=fills),
        patch.object(auto_trader.trade_store, "record_trade_closed"),
        patch.object(auto_trader.trade_store, "record_trade_mark"),
        patch("app.services.trade_store.record_trade_report"),
        patch("app.engines.snapshot_lag_analyzer.build_trade_close_report", return_value={}),
    ):
        asyncio.run(_run())

    _pts, broker_inr = mark_to_market(entry, broker_average, lots, 65)
    assert place_exit.call_count == 1
    assert trade.status == "CLOSED"
    assert trade.exitReason == "explosion_peak_keep_trail"
    assert trade.currentPremium == broker_average
    assert trade.pnlInr == broker_inr
    assert trade.pnlInr != round(11.6 * lots * 65, 2)
    assert trade.entryContext["brokerExitFillPremium"] == broker_average
    assert trade.entryContext["brokerExitMarkPremium"] == mark


def test_margin_fit_shrinks_the_sensex_order_that_was_239_short():
    """17 lots at 714.55 became a 732 limit and missed free margin by ₹238.78."""
    fitted = lots_fitting_broker_margin(17, 20, 714.55, 248_641.22)
    assert fitted < 17
    assert fitted >= 1
    guard = 714.55 * 1.03
    assert fitted * 20 * guard <= 248_641.22 - 500


def test_rejected_entry_is_dropped_without_another_sell():
    """A rejected buy is not a position. Do not sell it — each sell is a notification."""
    import app.engines.auto_trader as auto_trader
    from app.config import get_settings

    trade = PaperTrade(
        id="3a68ef9e",
        symbol="SENSEX",
        side=Side.PUT,
        strike=73800,
        entryPremium=714.55,
        currentPremium=780.0,
        lots=17,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={
            "instrumentKey": "BSE_FO|1125579",
            "brokerOrderId": "261022000024340",
            "brokerQuantity": 340,
            "lotSize": 20,
            "brokerSimulated": False,
            "executionMode": "LIVE",
        },
    )
    state = AutoTraderState(openPaperTrades=[trade])
    auto_trader._auto_trader_state = state
    auto_trader._state_loaded = True
    settings = get_settings().model_copy(
        update={
            "enable_live_trading": True,
            "auto_trading_enabled": True,
            "paper_trading": False,
        }
    )
    client = MagicMock()
    client.get_positions = MagicMock(return_value=_async([]))

    async def _run():
        await auto_trader.process_exits_only(
            {"SENSEX": _sensex_snap(780.0)},
            client=client,
        )

    with (
        patch.object(auto_trader, "get_settings", return_value=settings),
        patch.object(
            auto_trader,
            "live_order_fill",
            return_value={
                "status": "rejected",
                "averagePrice": 0.0,
                "filledQuantity": 0.0,
                "statusMessage": "You need to add Rs. 238.78 in your account to place this trade.",
            },
        ),
        patch.object(auto_trader, "place_exit_order") as place_exit,
        patch.object(auto_trader.trade_store, "record_trade_closed"),
    ):
        asyncio.run(_run())

    assert place_exit.call_count == 0
    assert trade.status == "CLOSED"
    assert trade.exitReason == "broker_entry_rejected"
    assert trade.pnlInr == 0
    assert state.openPaperTrades == []


def test_rejected_exit_waits_before_the_next_sell():
    import app.engines.auto_trader as auto_trader
    from app.config import get_settings

    trade = PaperTrade(
        id="eb4a31f3",
        symbol="NIFTY",
        side=Side.CALL,
        strike=23150,
        entryPremium=71.1,
        currentPremium=82.7,
        lots=19,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={
            "instrumentKey": "NSE_FO|23150CE",
            "brokerOrderId": "buy-1",
            "brokerEntryFillPremium": 71.1,
            "brokerExitOrderId": "sell-1",
            "brokerQuantity": 19 * 65,
            "lotSize": 65,
            "brokerSimulated": False,
            "executionMode": "LIVE",
            "explosionTier": "EXPLODING",
        },
    )
    state = AutoTraderState(openPaperTrades=[trade])
    auto_trader._auto_trader_state = state
    auto_trader._state_loaded = True
    settings = get_settings().model_copy(
        update={
            "adaptive_exits_enabled": False,
            "edge_engine_enabled": False,
            "explosion_capture_mode": True,
            "enable_live_trading": True,
            "auto_trading_enabled": True,
            "paper_trading": False,
        }
    )

    async def _run():
        await auto_trader.process_exits_only({"NIFTY": _snap(82.7)}, client=MagicMock())
        await auto_trader.process_exits_only({"NIFTY": _snap(82.7)}, client=MagicMock())

    with (
        patch.object(auto_trader, "get_settings", return_value=settings),
        patch.object(
            auto_trader,
            "evaluate_explosion_exit",
            return_value=("explosion_peak_keep_trail", 1.0),
        ),
        patch.object(auto_trader, "find_existing_exit_order", return_value=None),
        patch.object(auto_trader, "place_exit_order", return_value={"order_id": "sell-2"}) as place_exit,
        patch.object(
            auto_trader,
            "live_order_fill",
            return_value={
                "status": "rejected",
                "averagePrice": 0.0,
                "filledQuantity": 0.0,
                "statusMessage": "You need to add Rs. 3177775.28 in your account to place this trade.",
            },
        ),
        patch.object(auto_trader.trade_store, "record_trade_mark"),
    ):
        asyncio.run(_run())

    assert place_exit.call_count == 0
    assert trade.status == "OPEN"
    assert trade.entryContext["brokerExitRejected"]
    assert "brokerExitRetryAfter" in trade.entryContext


def _async(value):
    async def _inner():
        return value
    return _inner()


def _sensex_snap(ltp: float) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        breadth=Breadth(score=50, bias="NEUTRAL", aligned=False),
        heatmap=[
            HeatmapStrike(
                strike=73800,
                callLtp=20.0,
                putLtp=ltp,
                callInstrumentKey="BSE_FO|1125579CE",
                putInstrumentKey="BSE_FO|1125579",
            ),
        ],
    )
