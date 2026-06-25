"""Tests for paper-live parity broker simulation."""

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.paper_slippage import should_simulate_slippage
from app.models.schemas import PaperTrade, Side, StrategyType, SymbolSnapshot
from app.services.paper_broker import simulate_entry_order, simulate_exit_order

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime.now(IST)


def _trade(**kwargs) -> PaperTrade:
    base = dict(
        id="t1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24500,
        entryPremium=51.0,
        currentPremium=55.0,
        lots=2,
        openedAt=NOW,
        strategyType=StrategyType.SCALP,
    )
    base.update(kwargs)
    return PaperTrade(**base)


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-06-25T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        optionExpiry="2026-06-26",
        heatmap=[],
    )


class PaperLiveParityTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.services.paper_broker.resolve_instrument_key", new_callable=AsyncMock)
    async def test_simulate_entry_matches_live_order_shape(self, mock_resolve):
        mock_resolve.return_value = ("NSE_FO|12345", "2026-06-26", 65)
        client = MagicMock()
        order = await simulate_entry_order(
            client, _snap(), 24500, Side.CALL, lots=2,
            signal_premium=50.0, strategy_type=StrategyType.SCALP,
        )
        self.assertTrue(order["simulated"])
        self.assertEqual(order["order_type"], "MARKET")
        self.assertEqual(order["transaction_type"], "BUY")
        self.assertEqual(order["product"], "I")
        self.assertEqual(order["quantity"], 130)
        self.assertIn("PAPER-IN", order["order_id"])
        self.assertGreater(order["fill_premium"], 50.0)

    async def test_simulate_exit_requires_instrument_key(self):
        trade = _trade()
        with self.assertRaises(Exception):
            await simulate_exit_order(MagicMock(), trade, 55.0)

    async def test_slippage_stays_on_parity_trades(self):
        trade = _trade(
            id="t2",
            entryContext={
                "executionMode": "PAPER_LIVE_PARITY",
                "brokerOrderId": "PAPER-IN-abc",
                "brokerSimulated": True,
            },
        )
        self.assertTrue(should_simulate_slippage(trade))

    async def test_slippage_off_for_real_live_broker_fills(self):
        trade = _trade(
            id="t3",
            entryPremium=50.0,
            entryContext={
                "executionMode": "LIVE",
                "brokerOrderId": "real-order-1",
                "brokerSimulated": False,
            },
        )
        self.assertFalse(should_simulate_slippage(trade))


if __name__ == "__main__":
    unittest.main()
