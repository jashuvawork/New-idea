"""Execution backend — live vs paper sim at order boundary."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.engines.execution_backend import (
    is_live_execution,
    needs_broker_order_path,
    uses_paper_broker_simulation,
)
from app.models.schemas import Side, StrategyType
from tests.mock_defaults import settings_mock


def test_is_live_execution_requires_auto_trading():
    s = settings_mock(enable_live_trading=True, auto_trading_enabled=False)
    assert is_live_execution(s) is False
    s2 = settings_mock(enable_live_trading=True, auto_trading_enabled=True)
    assert is_live_execution(s2) is True


def test_paper_broker_simulation_only_when_not_live():
    s = settings_mock(
        enable_live_trading=False,
        paper_live_parity_enabled=True,
        paper_simulate_broker_orders=True,
    )
    assert uses_paper_broker_simulation(s) is True
    assert needs_broker_order_path(s) is True
    live = settings_mock(
        enable_live_trading=True,
        auto_trading_enabled=True,
        paper_live_parity_enabled=True,
        paper_simulate_broker_orders=True,
    )
    assert uses_paper_broker_simulation(live) is False
    assert needs_broker_order_path(live) is True


def test_submit_entry_order_live_path():
    import asyncio

    from app.engines.execution_backend import submit_entry_order

    settings = settings_mock(enable_live_trading=True, auto_trading_enabled=True)
    snap = MagicMock()
    client = MagicMock()

    async def _run():
        with patch(
            "app.services.order_executor.place_entry_order",
            new_callable=AsyncMock,
            return_value={
                "instrument_key": "k",
                "order_id": "oid",
                "quantity": 50,
                "lot_size": 25,
                "fill_premium": 120.5,
            },
        ):
            return await submit_entry_order(
                settings=settings,
                client=client,
                snap=snap,
                strike=22450.0,
                side=Side.CALL,
                lots=2,
                signal_premium=118.0,
                strategy_type=StrategyType.EXPLOSIVE,
            )

    order, ctx, fill = asyncio.run(_run())
    assert fill == 120.5
    assert ctx["brokerSimulated"] is False
    assert ctx["brokerFill"] is True
    assert order["order_id"] == "oid"
