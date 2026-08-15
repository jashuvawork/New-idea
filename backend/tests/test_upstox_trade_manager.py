import asyncio
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.capital_allocator import CapitalSnapshot
from app.models.schemas import (
    AutoTraderState,
    DailyReport,
    PaperTrade,
    Side,
    StrategyType,
)
from app.services.upstox_trade_manager import (
    build_upstox_trade_overview,
    reset_upstox_trade_manager_cache_for_tests,
)

IST = ZoneInfo("Asia/Kolkata")


class FakeUpstox:
    async def get_funds(self):
        return {
            "equity": {
                "available_margin": 125_000,
                "used_margin": 75_000,
                "net": 200_000,
            }
        }

    async def get_positions(self):
        return [
            {
                "instrument_token": "NSE_FO|NIFTY24500CE",
                "trading_symbol": "NIFTY 24500 CE",
                "exchange": "NSE_FO",
                "product": "I",
                "quantity": 130,
                "average_price": 50,
                "last_price": 62,
                "realised": 500,
                "unrealised": 1_560,
                "pnl": 2_060,
            }
        ]

    async def get_order_book(self):
        return [
            {
                "order_id": "order-1",
                "trading_symbol": "NIFTY 24500 CE",
                "transaction_type": "BUY",
                "status": "complete",
                "quantity": 130,
                "filled_quantity": 130,
                "average_price": 50,
                "order_timestamp": "2026-08-15T10:00:00+05:30",
            }
        ]


class FundsFailureUpstox(FakeUpstox):
    async def get_funds(self):
        raise RuntimeError("funds unavailable")


def test_trade_manager_reconciles_broker_and_strategy_data():
    now = datetime.now(IST)
    open_trade = PaperTrade(
        id="open-1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24_500,
        entryPremium=50,
        currentPremium=62,
        lots=2,
        pnlInr=1_560,
        pnlPoints=12,
        openedAt=now,
        sessionDate=now.strftime("%Y-%m-%d"),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={
            "executionMode": "LIVE",
            "brokerOrderId": "order-1",
            "instrumentKey": "NSE_FO|NIFTY24500CE",
            "allocationRank": 1,
            "allocationBudgetInr": 120_000,
            "allocatedCostInr": 6_500,
            "explosionTier": "ELITE",
            "selectionScore": 94,
        },
    )
    closed_trade = PaperTrade(
        id="closed-1",
        symbol="SENSEX",
        side=Side.PUT,
        strike=80_000,
        entryPremium=40,
        currentPremium=50,
        lots=1,
        pnlInr=200,
        pnlPoints=10,
        openedAt=now,
        closedAt=now,
        status="CLOSED",
        sessionDate=now.strftime("%Y-%m-%d"),
        strategyType=StrategyType.EXPLOSIVE,
    )
    state = AutoTraderState(
        liveTradingEnabled=True,
        openPaperTrades=[open_trade],
        closedPaperTrades=[closed_trade],
        dailyReport=DailyReport(
            wins=1,
            losses=0,
            netPnlInr=200,
            winRate=100,
            profitFactor=3,
        ),
        capitalAllocation={"plannedAllocations": []},
    )
    capital = CapitalSnapshot(
        availableMarginInr=125_000,
        usedMarginInr=75_000,
        totalEquityInr=200_000,
        source="upstox",
    )

    reset_upstox_trade_manager_cache_for_tests()
    with (
        patch("app.services.upstox_trade_manager.get_state", return_value=state),
        patch(
            "app.services.upstox_trade_manager.get_capital_snapshot",
            return_value=capital,
        ),
        patch(
            "app.services.upstox_trade_manager.get_lot_sizes_meta",
            return_value={"lotSizes": {"NIFTY": 65}},
        ),
        patch(
            "app.services.upstox_trade_manager.capital_book_summary",
            return_value={
                "capitalBaseInr": 200_000,
                "committedInr": 8_060,
                "remainingInr": 125_000,
                "cashReserveInr": 10_000,
                "activeAllocations": [],
                "plannedAllocations": [],
            },
        ),
    ):
        payload = asyncio.run(
            build_upstox_trade_overview(FakeUpstox(), force=True)
        )

    assert payload["broker"] == {
        "connected": True,
        "complete": True,
        "errors": {},
    }
    assert payload["capital"]["brokerAvailableMarginInr"] == 125_000
    assert payload["brokerPositions"][0]["pnlInr"] == 2_060
    assert payload["brokerOrders"][0]["orderId"] == "order-1"
    assert payload["pnl"]["brokerNetInr"] == 2_060
    assert payload["pnl"]["strategyNetInr"] == 1_760
    assert payload["strategyTrades"]["open"][0]["allocationRank"] == 1
    assert payload["reconciliation"]["safe"] is True


def test_positions_only_success_never_claims_broker_connected():
    state = AutoTraderState()
    capital = CapitalSnapshot(
        availableMarginInr=200_000,
        totalEquityInr=200_000,
        source="fallback",
    )
    reset_upstox_trade_manager_cache_for_tests()
    with (
        patch("app.services.upstox_trade_manager.get_state", return_value=state),
        patch(
            "app.services.upstox_trade_manager.get_capital_snapshot",
            return_value=capital,
        ),
        patch(
            "app.services.upstox_trade_manager.get_lot_sizes_meta",
            return_value={},
        ),
        patch(
            "app.services.upstox_trade_manager.capital_book_summary",
            return_value={
                "capitalBaseInr": 200_000,
                "committedInr": 0,
                "remainingInr": 190_000,
                "cashReserveInr": 10_000,
                "activeAllocations": [],
                "plannedAllocations": [],
            },
        ),
    ):
        payload = asyncio.run(
            build_upstox_trade_overview(FundsFailureUpstox(), force=True)
        )

    assert payload["broker"]["connected"] is False
    assert payload["broker"]["complete"] is False
    assert payload["broker"]["errors"]["funds"] == "funds unavailable"
