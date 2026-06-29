"""Daily loss stop gate tests."""

import unittest
from unittest.mock import patch

from app.engines.capital_allocator import update_daily_profit_gate
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class DailyLossStopTests(unittest.TestCase):
    def test_loss_stop_blocks_entries(self):
        state = AutoTraderState()
        state.closedPaperTrades = [
            PaperTrade(
                id="t1",
                symbol="NIFTY",
                side=Side.CALL,
                strike=24000,
                entryPremium=50,
                lots=40,
                pnlInr=-35_000,
                openedAt=datetime.now(IST),
                strategyType=StrategyType.SCALP,
            ),
        ]
        with patch("app.engines.capital_allocator.get_settings") as mock_settings:
            mock_settings.return_value.daily_loss_stop_inr = 30_000
            mock_settings.return_value.daily_profit_target_inr = 44_000
            mock_settings.return_value.daily_profit_trail_inr = 5_000
            mock_settings.return_value.daily_profit_stage_locks_enabled = True
            mock_settings.return_value.daily_profit_stage_pcts = [0.55, 0.88, 1.12]
            mock_settings.return_value.fallback_capital_inr = 200_000
            mock_settings.return_value.max_sizing_capital_inr = 200_000
            gate = update_daily_profit_gate(state)
        self.assertFalse(gate.newEntriesAllowed)
        self.assertEqual(gate.status, "DAILY_LOSS_STOP")


if __name__ == "__main__":
    unittest.main()
