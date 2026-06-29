"""Capital sizing and explosion exit tests."""

import unittest
from unittest.mock import patch

from app.engines.capital_allocator import (
    CapitalSnapshot,
    clamp_lots,
    get_capital_snapshot,
    max_lots_for_capital,
)
from app.engines.explosion_profit import evaluate_explosion_exit, explosion_in_cooldown, record_explosion_stop
from app.models.schemas import PaperTrade, Side, StrategyType
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class CapitalSizingTests(unittest.TestCase):
    def test_max_lots_from_85pct_2l_capital(self):
        snap = CapitalSnapshot(
            availableMarginInr=200_000,
            perTradeCapitalInr=170_000,
        )
        with patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap):
            # SENSEX premium 40, lot 20 → 170000/(40*20)=212
            lots = max_lots_for_capital("SENSEX", 40.0)
            self.assertEqual(lots, 212)
            # NIFTY premium 50, lot 65 → 170000/3250=52
            lots_n = max_lots_for_capital("NIFTY", 50.0)
            self.assertEqual(lots_n, 52)

    def test_clamp_uses_capital_not_100(self):
        snap = CapitalSnapshot(perTradeCapitalInr=170_000)
        with patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap):
            clamped = clamp_lots(500, "SENSEX", 40.0)
            self.assertEqual(clamped, 60)


class ExplosionExitTests(unittest.TestCase):
    def _trade(self, entry: float = 50.0, lots: int = 50) -> PaperTrade:
        return PaperTrade(
            id="t1",
            symbol="NIFTY",
            side=Side.CALL,
            strike=24000,
            entryPremium=entry,
            lots=lots,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
        )

    def test_trailing_sl_locks_winner(self):
        trade = self._trade(50.0, 10)
        trade.bestPnlPoints = 10.0
        trade.entryContext = {"explosionTrailFloorPts": 6.5}
        reason, pnl = evaluate_explosion_exit(trade, 55.5, "EXPLODING", 65)
        self.assertEqual(reason, "explosion_trail_sl")
        self.assertGreater(pnl, 0)

    def test_target_hit(self):
        trade = self._trade(50.0, 10)
        reason, _ = evaluate_explosion_exit(trade, 63.0, "EXPLODING", 65)
        self.assertEqual(reason, "explosion_target_hit")

    def test_cooldown_blocks_reentry(self):
        record_explosion_stop("SENSEX")
        self.assertTrue(explosion_in_cooldown("SENSEX"))


if __name__ == "__main__":
    unittest.main()
