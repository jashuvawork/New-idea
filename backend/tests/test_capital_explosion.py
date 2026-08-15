"""Capital sizing and explosion exit tests."""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.engines.capital_allocator import (
    CapitalSnapshot,
    cap_lots_to_allocation,
    capital_book_summary,
    clamp_lots,
    get_capital_snapshot,
    max_lots_for_capital,
    next_ranked_allocation_rank,
    ranked_allocation_for_state,
    set_manual_capital_limit,
    tune_exit_plan_for_position,
)
from app.engines.explosion_profit import (
    compute_explosion_lots,
    evaluate_explosion_exit,
    explosion_in_cooldown,
    record_explosion_stop,
)
from app.engines.auto_trader import _is_ranked_ftv_candidate
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class CapitalSizingTests(unittest.TestCase):
    @staticmethod
    def _ranked_settings():
        return SimpleNamespace(
            fallback_capital_inr=200_000,
            max_sizing_capital_inr=200_000,
            per_trade_capital_pct=0.95,
            ftv_ranked_allocation_enabled=True,
            ftv_allocation_weights_csv="0.60,0.25,0.10",
            ftv_allocation_remaining_pct=0.90,
            ftv_allocation_cash_reserve_pct=0.0,
            ftv_allocation_max_positions=3,
            ftv_allocation_max_same_side=2,
            lot_size_nifty=65,
            lot_size_banknifty=30,
            lot_size_sensex=20,
            use_upstox_lot_sizes=False,
        )

    def test_max_lots_from_85pct_2l_capital(self):
        snap = CapitalSnapshot(
            availableMarginInr=200_000,
            perTradeCapitalInr=170_000,
        )
        with patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap):
            lots = max_lots_for_capital("SENSEX", 40.0)
            self.assertEqual(lots, 212)
            lots_n = max_lots_for_capital("NIFTY", 50.0)
            self.assertEqual(lots_n, 52)

    def test_compute_lots_aggressive_uses_full_85pct_budget(self):
        from app.engines.capital_allocator import compute_lots
        from app.models.schemas import StrategyType

        snap = CapitalSnapshot(perTradeCapitalInr=170_000)
        with patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap):
            with patch("app.engines.capital_allocator.get_settings") as mock_settings:
                s = mock_settings.return_value
                s.aggressive_lot_sizing = True
                s.max_lots_per_trade = 0
                s.scalp_max_lots = 0
                s.explosion_max_lots = 0
                s.min_lots_per_trade = 1
                s.simple_min_lots = 1
                s.per_trade_capital_pct = 0.95
                s.lot_size_nifty = 65
                s.use_upstox_lot_sizes = False
                lots = compute_lots("NIFTY", 50.0, 3.0, strategy_type=StrategyType.SCALP)
                self.assertEqual(lots, 52)

    def test_clamp_respects_hard_cap_when_configured(self):
        snap = CapitalSnapshot(perTradeCapitalInr=170_000)
        with patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap):
            with patch("app.engines.capital_allocator.get_settings") as mock_settings:
                s = mock_settings.return_value
                s.max_lots_per_trade = 40
                s.min_lots_per_trade = 1
                s.simple_min_lots = 1
                s.lot_size_sensex = 20
                s.use_upstox_lot_sizes = False
                clamped = clamp_lots(500, "SENSEX", 40.0)
                self.assertEqual(clamped, 40)

    def test_ranked_ftv_allocation_uses_90pct_of_remaining_capital(self):
        state = AutoTraderState()
        snap = CapitalSnapshot(
            availableMarginInr=200_000,
            totalEquityInr=200_000,
            source="fallback",
        )
        settings = self._ranked_settings()
        with (
            patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap),
            patch("app.engines.capital_allocator.get_settings", return_value=settings),
        ):
            first = ranked_allocation_for_state(state, 1)
            lots = cap_lots_to_allocation(100, "NIFTY", 50.0, first)

        self.assertEqual(first.cashReserveInr, 0)
        self.assertEqual(first.budgetInr, 180_000)
        self.assertEqual(lots, 55)
        self.assertLessEqual(lots * 65 * 50, first.budgetInr)

    def test_unused_top_sleeve_rolls_into_second_rank(self):
        state = AutoTraderState(
            openPaperTrades=[
                PaperTrade(
                    id="rank-1",
                    symbol="NIFTY",
                    side=Side.CALL,
                    strike=24_500,
                    entryPremium=50,
                    currentPremium=40,
                    lots=36,
                    openedAt=datetime.now(IST),
                    strategyType=StrategyType.EXPLOSIVE,
                    entryContext={"allocationRank": 1},
                )
            ]
        )
        snap = CapitalSnapshot(
            availableMarginInr=200_000,
            totalEquityInr=200_000,
            source="fallback",
        )
        settings = self._ranked_settings()
        with (
            patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap),
            patch("app.engines.capital_allocator.get_settings", return_value=settings),
        ):
            second = ranked_allocation_for_state(state, 2)
            summary = capital_book_summary(state)

        self.assertEqual(second.committedInr, 117_000)
        self.assertEqual(second.remainingBeforeInr, 83_000)
        self.assertEqual(second.budgetInr, 74_700)
        self.assertEqual(summary["remainingInr"], 83_000)
        self.assertEqual(summary["nextTradeBudgetInr"], 74_700)
        for actual, expected in zip(summary["weights"], [0.9, 0.09, 0.009]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(summary["activeAllocations"][0]["rank"], 1)

    def test_closed_top_sleeve_reuses_vacant_rank_not_open_count(self):
        state = AutoTraderState(
            openPaperTrades=[
                PaperTrade(
                    id="rank-2",
                    symbol="SENSEX",
                    side=Side.PUT,
                    strike=80_000,
                    entryPremium=50,
                    currentPremium=50,
                    lots=52,
                    openedAt=datetime.now(IST),
                    strategyType=StrategyType.EXPLOSIVE,
                    entryContext={"allocationRank": 2},
                )
            ]
        )
        snap = CapitalSnapshot(
            availableMarginInr=200_000,
            totalEquityInr=200_000,
            source="fallback",
        )
        settings = self._ranked_settings()
        with (
            patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap),
            patch("app.engines.capital_allocator.get_settings", return_value=settings),
        ):
            rank = next_ranked_allocation_rank(state)
            allocation = ranked_allocation_for_state(state, rank or 0)

        self.assertEqual(rank, 1)
        self.assertEqual(allocation.committedInr, 52_000)
        self.assertEqual(allocation.budgetInr, 133_200)

    def test_exit_plan_uses_rank_sleeve_as_risk_budget(self):
        settings = self._ranked_settings()
        settings.position_sl_cap_pct = 0.08
        settings.position_tp_target_pct = 0.12
        settings.scalp_stop_points = 3.0
        settings.scalp_stop_min_points = 1.0
        settings.position_sl_preserve_natural_frac = 0.45
        settings.explosion_sl_preserve_natural_frac = 0.85
        settings.position_min_risk_reward = 1.2
        settings.scalp_trail_step_points = 2.0
        snap = CapitalSnapshot(
            availableMarginInr=200_000,
            perTradeCapitalInr=190_000,
        )
        with (
            patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap),
            patch("app.engines.capital_allocator.get_settings", return_value=settings),
        ):
            tuned = tune_exit_plan_for_position(
                {
                    "stopPoints": 10,
                    "naturalStopPoints": 10,
                    "targetPoints": 20,
                    "microTargetPoints": 3,
                    "trailArmPoints": 5,
                },
                lots=20,
                premium=50,
                symbol="NIFTY",
                trade_budget_inr=60_000,
            )

        self.assertEqual(tuned["tradeBudgetInr"], 60_000)
        self.assertLessEqual(tuned["actualSlRiskInr"], 60_000 * 0.08 + 0.01)

    def test_manual_capital_limit_updates_sizing_snapshot(self):
        settings = self._ranked_settings()
        settings.per_trade_capital_pct = 0.95
        settings.simple_min_lots = 1
        with patch("app.engines.capital_allocator.get_settings", return_value=settings):
            snap = set_manual_capital_limit(100_000)

        self.assertEqual(snap.availableMarginInr, 100_000)
        self.assertEqual(snap.perTradeCapitalInr, 95_000)
        self.assertEqual(snap.source, "manual")

    def test_ranked_sleeve_requires_first_lift_or_flat_vertical(self):
        first_lift = SimpleNamespace(
            mode="explosion",
            alert={"ictFirstLift": True},
            explosion_event=None,
        )
        generic = SimpleNamespace(
            mode="explosion",
            alert={"tier": "ELITE"},
            explosion_event=None,
        )

        self.assertTrue(_is_ranked_ftv_candidate(first_lift))
        self.assertFalse(_is_ranked_ftv_candidate(generic))


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
        trade.entryContext = {"explosionTrailFloorPts": 6.5, "exitPlan": {"targetPoints": 30.0}}
        reason, pnl = evaluate_explosion_exit(trade, 55.5, "EXPLODING", 65)
        # Peak-capture giveback runs before trail SL on faded winners.
        self.assertEqual(reason, "explosion_peak_capture")
        self.assertGreater(pnl, 0)

    def test_target_hit_at_12pt(self):
        trade = self._trade(50.0, 10)
        reason, _ = evaluate_explosion_exit(trade, 62.0, "EXPLODING", 65)
        self.assertEqual(reason, "explosion_target_hit")

    def test_target_hit_on_best_even_when_current_faded(self):
        """Faded peak locks via peak-capture before TP-on-best (poll gap path)."""
        trade = self._trade(50.0, 10)
        trade.bestPnlPoints = 12.0
        reason, _ = evaluate_explosion_exit(trade, 58.0, "EXPLODING", 65)
        self.assertEqual(reason, "explosion_peak_capture")

    def test_runner_giveback_before_time_exit(self):
        trade = self._trade(82.52, 22)
        trade.bestPnlPoints = 11.44
        trade.entryContext = {
            "exitPlan": {"targetPoints": 36.0, "stopPoints": 6.0, "trailArmPoints": 4.0},
            "chartConfidence": 75.0,
            "entryChartConfidence": 75.0,
            "breadth": "BEARISH",
        }
        from unittest.mock import patch
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        IST = ZoneInfo("Asia/Kolkata")
        trade.openedAt = datetime.now(IST) - timedelta(seconds=4000)
        with patch("app.engines.explosion_profit.get_settings") as mock_s:
            s = mock_s.return_value
            for k, v in {
                "explosion_target_standard": 12.0,
                "explosion_trail_arm_points": 4.0,
                "explosion_trail_keep_ratio": 0.65,
                "runner_trail_keep_ratio": 0.38,
                "runner_min_best_points": 5.0,
                "runner_micro_giveback_points": 4.0,
                "chart_confidence_half_tp_giveback_ratio": 0.40,
                "explosion_no_progress_enabled": True,
                "explosion_no_progress_seconds": 150,
                "explosion_no_progress_aligned_seconds": 420,
                "explosion_no_progress_skip_when_aligned": True,
                "chart_confidence_hold_enabled": True,
                "chart_confidence_hold_min_confidence": 62.0,
                "chart_confidence_half_tp_lock_pct": 0.50,
                "chart_confidence_hold_min_target_pct": 0.85,
                "high_confidence_min_score": 72.0,
                "all_day_min_chart_confidence": 62.0,
                "emergency_stop_enabled": False,
                "explosion_stop_min_hold_seconds": 15,
                "explosion_trail_step_points": 2.0,
                "explosion_trail_tight_arm": 999.0,
                "explosion_trail_tight_points": 0.0,
                "afternoon_capture_exit_max_hold_seconds": 480,
            }.items():
                setattr(s, k, v)
            reason, pnl = evaluate_explosion_exit(trade, 85.38, "EXPLODING", 65)
            self.assertIn(
                reason,
                (
                    "explosion_peak_capture",
                    "explosion_runner_giveback",
                    "explosion_trail_sl",
                    "explosion_trail_lock",
                ),
            )
        self.assertGreater(pnl, 0)
        self.assertNotIn(reason, ("explosion_time_profit", "explosion_time_stop"))

    def test_cooldown_blocks_reentry(self):
        record_explosion_stop("SENSEX")
        self.assertTrue(explosion_in_cooldown("SENSEX"))

    def test_explosion_lots_use_85pct_capital_max(self):
        from app.engines.explosion_detector import ExplosionEvent
        from app.models.schemas import Side

        snap = CapitalSnapshot(perTradeCapitalInr=170_000)
        event = ExplosionEvent(
            symbol="NIFTY",
            side=Side.CALL,
            strike=24000.0,
            premium=60.0,
            velocity_3s=3.0,
            velocity_9s=4.0,
            velocity_15s=5.0,
            volume_surge=1.5,
            explosion_score=60.0,
            tier="EXPLODING",
            reason="test",
        )
        with patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap):
            lots = compute_explosion_lots(event, 70.0, 60.0)
            self.assertEqual(lots, 43)


if __name__ == "__main__":
    unittest.main()
