"""Staged daily profit lock tests."""

import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.capital_allocator import (
    _compute_stage_lock,
    update_daily_profit_gate,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")
# Fixed midday IST — avoids CI flakiness when the suite crosses 00:00 IST.
NOW = datetime(2026, 6, 15, 12, 30, 0, tzinfo=IST)
SESSION_DATE = NOW.strftime("%Y-%m-%d")


class _FrozenAllocatorDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return NOW.replace(tzinfo=None)
        return NOW.astimezone(tz)


def _legacy_settings():
    return type(
        "S",
        (),
        {
            "daily_profit_target_inr": 22_000,
            "daily_profit_target_from_capital": False,
            "daily_profit_trail_inr": 5_000,
            "daily_profit_stage_locks_enabled": True,
            "daily_profit_stage_block_entries_min_stage": 2,
            "daily_profit_stage_from_target": False,
            "daily_profit_stage_pcts": [0.55, 0.88, 1.12],
            "daily_loss_stop_inr": 0,
            "max_sizing_capital_inr": 200_000,
            "fallback_capital_inr": 200_000,
        },
    )()


class StageLockTests(unittest.TestCase):
    def _run_gate(self, state, settings, *, best_pnl: float, highest_stage: int):
        import app.engines.capital_allocator as ca

        with patch("app.engines.capital_allocator.get_settings", return_value=settings):
            with patch("app.engines.capital_allocator.datetime", _FrozenAllocatorDatetime):
                ca._session_date = SESSION_DATE
                ca._best_pnl = best_pnl
                ca._highest_stage = highest_stage
                return update_daily_profit_gate(state)

    def test_stage_thresholds_on_2l_capital(self):
        thresholds = [110_000, 176_000, 224_000]
        _, floor, stage = _compute_stage_lock(120_000, 120_000, 0, thresholds)
        self.assertEqual(stage, 1)
        self.assertAlmostEqual(floor, 110_000, places=0)

        _, floor, stage = _compute_stage_lock(180_000, 180_000, 1, thresholds)
        self.assertEqual(stage, 2)
        self.assertEqual(floor, 176_000)

        _, floor, stage = _compute_stage_lock(230_000, 230_000, 2, thresholds)
        self.assertEqual(stage, 4)
        self.assertEqual(floor, 230_000)

    def test_stage_lock_blocks_entries_below_floor(self):
        state = AutoTraderState()
        state.closedPaperTrades = [
            PaperTrade(
                id="1",
                symbol="NIFTY",
                side=Side.CALL,
                strike=24000,
                entryPremium=50,
                lots=10,
                openedAt=NOW,
                closedAt=NOW,
                pnlInr=180_000,
                strategyType=StrategyType.SCALP,
                sessionDate=SESSION_DATE,
            )
        ]
        state.closedPaperTrades[0].pnlInr = 170_000
        gate = self._run_gate(
            state, _legacy_settings(), best_pnl=180_000, highest_stage=2,
        )
        self.assertFalse(gate.newEntriesAllowed)
        self.assertEqual(gate.status, "STAGE_LOCK")

    def test_stage1_dip_does_not_block_entries(self):
        """Stage 1 (50% of daily target) — caution only, keep trading toward 18%."""
        state = AutoTraderState()
        state.closedPaperTrades = [
            PaperTrade(
                id="1",
                symbol="NIFTY",
                side=Side.CALL,
                strike=24000,
                entryPremium=50,
                lots=10,
                openedAt=NOW,
                closedAt=NOW,
                pnlInr=15_840,
                strategyType=StrategyType.SCALP,
                sessionDate=SESSION_DATE,
            )
        ]
        settings = _legacy_settings()
        settings.daily_profit_target_inr = 36_000
        settings.daily_profit_stage_from_target = True
        settings.daily_profit_stage_target_mults = lambda: [0.5, 1.0, 1.5]
        settings.daily_profit_stage_block_entries_min_stage = 2
        gate = self._run_gate(
            state, settings, best_pnl=21_655, highest_stage=1,
        )
        self.assertTrue(gate.newEntriesAllowed)
        self.assertEqual(gate.status, "STAGE_CAUTION")

    def test_flat_book_clamps_unrealized_peak_lock(self):
        """After exit, stage lock must not require booked PnL to match open MTM peak."""
        state = AutoTraderState()
        state.closedPaperTrades = [
            PaperTrade(
                id="1",
                symbol="SENSEX",
                side=Side.PUT,
                strike=73200,
                entryPremium=200,
                lots=22,
                openedAt=NOW,
                closedAt=NOW,
                pnlInr=17_058.8,
                strategyType=StrategyType.EXPLOSIVE,
                sessionDate=SESSION_DATE,
            )
        ]
        settings = _legacy_settings()
        settings.daily_profit_target_inr = 18_000
        settings.daily_profit_stage_from_target = True
        settings.daily_profit_stage_target_mults = lambda: [0.5, 1.0, 1.5]
        gate = self._run_gate(
            state, settings, best_pnl=33_541.2, highest_stage=4,
        )
        self.assertTrue(gate.newEntriesAllowed)
        self.assertNotEqual(gate.status, "STAGE_LOCK")

    def test_min_44k_does_not_stop_entries(self):
        state = AutoTraderState()
        state.closedPaperTrades = [
            PaperTrade(
                id="1",
                symbol="NIFTY",
                side=Side.CALL,
                strike=24000,
                entryPremium=50,
                lots=10,
                openedAt=NOW,
                closedAt=NOW,
                pnlInr=50_000,
                strategyType=StrategyType.SCALP,
                sessionDate=SESSION_DATE,
            )
        ]
        gate = self._run_gate(
            state, _legacy_settings(), best_pnl=0.0, highest_stage=0,
        )
        self.assertTrue(gate.newEntriesAllowed)
        self.assertTrue(gate.minTargetHit)


if __name__ == "__main__":
    unittest.main()
