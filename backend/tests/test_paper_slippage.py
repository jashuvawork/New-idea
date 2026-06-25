"""Unit tests for paper slippage model."""

import unittest

from app.engines.paper_slippage import (
    apply_entry_fill,
    apply_exit_mark,
    finalize_closed_pnl_inr,
    mark_to_market,
)
from app.models.schemas import StrategyType


class PaperSlippageTests(unittest.TestCase):
    def test_scalp_entry_and_exit_worsen_pnl(self):
        fill, meta = apply_entry_fill(50.0, StrategyType.SCALP)
        self.assertGreater(fill, 50.0)
        self.assertEqual(meta["signalPremium"], 50.0)

        exit_mark = apply_exit_mark(53.0, StrategyType.SCALP)
        self.assertLess(exit_mark, 53.0)

        pts, inr = mark_to_market(fill, exit_mark, lots=10, lot_mult=65)
        raw_pts = 53.0 - 50.0
        self.assertLess(pts, raw_pts)
        self.assertEqual(inr, pts * 10 * 65)

    def test_explosion_has_higher_slippage_than_scalp(self):
        _, scalp = apply_entry_fill(40.0, StrategyType.SCALP)
        _, boom = apply_entry_fill(40.0, StrategyType.EXPLOSIVE, tier="ELITE")
        self.assertGreater(boom["entrySlipPoints"], scalp["entrySlipPoints"])

    def test_brokerage_subtracted_on_close(self):
        net = finalize_closed_pnl_inr(5000.0)
        self.assertLess(net, 5000.0)


if __name__ == "__main__":
    unittest.main()
