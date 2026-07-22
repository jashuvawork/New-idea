"""Unit tests for paper slippage model."""

import unittest

from app.engines.paper_slippage import (
    apply_entry_fill,
    apply_exit_mark,
    compute_charges_inr,
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

    def test_realistic_charges_scale_with_turnover(self):
        # SENSEX 77200 PE today: entry 368.43, exit 384.35, 4 lots x 20
        charges = compute_charges_inr(368.43, 384.35, lots=4, lot_mult=20)
        # Real Zerodha-style round trip on ~₹60k turnover ≈ ₹60-75
        self.assertGreater(charges, 50.0)
        self.assertLess(charges, 90.0)

    def test_charges_grow_with_size(self):
        small = compute_charges_inr(368.43, 384.35, lots=4, lot_mult=20)
        big = compute_charges_inr(368.43, 384.35, lots=25, lot_mult=20)
        # Turnover-based → bigger position costs materially more (flat ₹40 wouldn't)
        self.assertGreater(big, small * 3)

    def test_finalize_uses_turnover_when_provided(self):
        flat = finalize_closed_pnl_inr(5000.0)
        real = finalize_closed_pnl_inr(
            5000.0, entry_premium=368.43, exit_premium=384.35, lots=25, lot_mult=20,
        )
        # 25-lot real charges >> flat ₹40 → net is lower than the flat-fee net
        self.assertLess(real, flat)

    def test_zero_qty_no_charge(self):
        self.assertEqual(compute_charges_inr(100.0, 110.0, lots=0, lot_mult=20), 0.0)


if __name__ == "__main__":
    unittest.main()
