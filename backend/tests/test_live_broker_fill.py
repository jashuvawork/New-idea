"""Live broker fill price polling for entry/exit PnL."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.services.order_executor import fetch_order_average_price


def test_fetch_order_average_price_returns_fill_when_complete():
    client = MagicMock()
    client.get_order_book = AsyncMock(
        side_effect=[
            [{"order_id": "123", "status": "open", "filled_quantity": 0}],
            [
                {
                    "order_id": "123",
                    "status": "complete",
                    "filled_quantity": 910,
                    "average_price": 193.25,
                }
            ],
        ]
    )
    price = asyncio.run(
        fetch_order_average_price(client, "123", max_wait_seconds=2.0, poll_interval=0.01)
    )
    assert price == 193.25


def test_fetch_order_average_price_none_on_rejected():
    client = MagicMock()
    client.get_order_book = AsyncMock(
        return_value=[{"order_id": "123", "status": "rejected", "average_price": 0}]
    )
    price = asyncio.run(
        fetch_order_average_price(client, "123", max_wait_seconds=0.5, poll_interval=0.01)
    )
    assert price is None
