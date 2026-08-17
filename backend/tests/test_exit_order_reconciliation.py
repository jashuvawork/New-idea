import asyncio
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from app.models.schemas import PaperTrade, Side, StrategyType
from app.services.order_executor import exit_order_tag, find_existing_exit_order


IST = ZoneInfo("Asia/Kolkata")


def test_existing_exit_order_is_reused_after_restart():
    trade = PaperTrade(
        id="trade-restart-1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24350,
        entryPremium=42.7,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"instrumentKey": "NSE_FO|pe"},
    )
    client = AsyncMock()
    client.get_order_book.return_value = [
        {
            "order_id": "exit-existing",
            "tag": exit_order_tag(trade.id),
            "transaction_type": "SELL",
            "instrument_token": "NSE_FO|pe",
            "status": "complete",
        }
    ]

    assert asyncio.run(find_existing_exit_order(client, trade)) == "exit-existing"
