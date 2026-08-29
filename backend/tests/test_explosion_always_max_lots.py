"""Explosion entries must use capital max lots — no 3/6-lot throttles."""

from unittest.mock import MagicMock, patch

from app.engines.auto_trader import _top_rank_full_budget_lots_allowed
from app.engines.capital_allocator import (
    CapitalSnapshot,
    RankedAllocation,
    apply_explosion_always_max_lots,
    tune_exit_plan_for_position,
)
from app.engines.session_mode_feedback import cap_lots_until_first_green
from app.models.schemas import AutoTraderState


@patch("app.engines.capital_allocator.get_settings")
@patch("app.engines.capital_allocator.max_lots_for_capital", return_value=42)
def test_apply_explosion_always_max_lots_floors(_max, mock_settings):
    s = MagicMock()
    s.explosion_always_force_max_lots = True
    mock_settings.return_value = s
    assert apply_explosion_always_max_lots(6, "NIFTY", 61.0, mode="explosion") == 42
    assert apply_explosion_always_max_lots(6, "NIFTY", 61.0, mode="scalp") == 6


@patch("app.engines.capital_allocator.get_settings")
@patch("app.engines.capital_allocator.max_lots_for_capital", return_value=42)
def test_apply_respects_disabled_flag(_max, mock_settings):
    s = MagicMock()
    s.explosion_always_force_max_lots = False
    mock_settings.return_value = s
    assert apply_explosion_always_max_lots(6, "NIFTY", 61.0, mode="explosion") == 6


@patch("app.engines.session_mode_feedback.get_settings")
def test_first_green_skipped_when_always_max_config(mock_settings):
    s = MagicMock()
    s.size_until_first_green_enabled = True
    s.size_until_first_green_lot_cap = 6
    s.size_until_first_green_modes_csv = "explosion,scalp"
    s.explosion_always_force_max_lots = True
    mock_settings.return_value = s
    state = AutoTraderState()
    # When always-max bypasses first-green in auto_trader, cap helper still caps if called.
    assert cap_lots_until_first_green(40, state, mode="explosion") == 6


def test_always_max_preserves_lots_without_ftv_full_sleeve():
    """Aug28 morning EXPLODING: max lots must survive SL size-tune without FTV stamp."""
    allocation = RankedAllocation(
        rank=1,
        budgetInr=180_000,
        remainingBeforeInr=200_000,
        cashReserveInr=0,
        capitalBaseInr=200_000,
        committedInr=0,
        weight=0.9,
    )
    assert _top_rank_full_budget_lots_allowed(
        enabled=True,
        allocation=allocation,
        strict_first_lift=False,
        top_explosion_max=True,
        faded_rip=False,
        post_win_capped=False,
        explosion_always_max=True,
    )

    settings = MagicMock()
    settings.position_sl_cap_pct = 0.08
    settings.position_tp_target_pct = 0.12
    settings.scalp_stop_points = 3.0
    settings.scalp_stop_min_points = 1.0
    settings.position_sl_preserve_natural_frac = 0.45
    settings.explosion_sl_preserve_natural_frac = 0.85
    settings.position_min_risk_reward = 1.2
    settings.scalp_trail_step_points = 2.0
    settings.per_trade_capital_pct = 0.9
    snap = CapitalSnapshot(
        availableMarginInr=200_000,
        perTradeCapitalInr=180_000,
    )
    with (
        patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap),
        patch("app.engines.capital_allocator.get_settings", return_value=settings),
        patch("app.engines.capital_allocator.lot_multiplier", return_value=65),
        patch(
            "app.engines.capital_allocator.max_lots_for_capital",
            return_value=33,
        ),
    ):
        lots = apply_explosion_always_max_lots(1, "NIFTY", 81.9, mode="explosion")
        assert lots == 33
        tuned = tune_exit_plan_for_position(
            {
                "stopPoints": 18,
                "naturalStopPoints": 18,
                "targetPoints": 36,
                "microTargetPoints": 6,
                "trailArmPoints": 10,
            },
            lots=lots,
            premium=81.9,
            symbol="NIFTY",
            trade_budget_inr=180_000,
            preserve_lots_over_sl_budget=True,
        )

    assert tuned["lots"] == 33
    assert tuned["slRiskBudgetOverride"] is True


def test_rank_two_small_sleeve_shrinks_to_one_without_preserve():
    """Aug28 rank-2 OTM leg: tight ₹21k sleeve + 18pt SL used to crush 7→1 lot."""
    allocation = RankedAllocation(
        rank=2,
        budgetInr=21_699,
        remainingBeforeInr=24_110,
        cashReserveInr=0,
        capitalBaseInr=200_000,
        committedInr=175_890,
        weight=0.9,
    )
    assert not _top_rank_full_budget_lots_allowed(
        enabled=True,
        allocation=allocation,
        strict_first_lift=False,
        top_explosion_max=True,
        faded_rip=False,
        post_win_capped=False,
        explosion_always_max=False,
    )

    settings = MagicMock()
    settings.position_sl_cap_pct = 0.08
    settings.position_tp_target_pct = 0.12
    settings.scalp_stop_points = 3.0
    settings.scalp_stop_min_points = 1.0
    settings.position_sl_preserve_natural_frac = 0.45
    settings.explosion_sl_preserve_natural_frac = 0.85
    settings.position_min_risk_reward = 1.2
    settings.scalp_trail_step_points = 2.0
    settings.per_trade_capital_pct = 0.9
    snap = CapitalSnapshot(
        availableMarginInr=200_000,
        perTradeCapitalInr=180_000,
    )
    plan = {
        "stopPoints": 18,
        "naturalStopPoints": 18,
        "targetPoints": 36,
        "microTargetPoints": 6,
        "trailArmPoints": 10,
    }
    with (
        patch("app.engines.capital_allocator.get_capital_snapshot", return_value=snap),
        patch("app.engines.capital_allocator.get_settings", return_value=settings),
        patch("app.engines.capital_allocator.lot_multiplier", return_value=65),
    ):
        shrunk = tune_exit_plan_for_position(
            plan,
            lots=7,
            premium=46.0,
            symbol="NIFTY",
            trade_budget_inr=allocation.budgetInr,
            preserve_lots_over_sl_budget=False,
        )
        preserved = tune_exit_plan_for_position(
            plan,
            lots=7,
            premium=46.0,
            symbol="NIFTY",
            trade_budget_inr=allocation.budgetInr,
            preserve_lots_over_sl_budget=True,
        )

    assert shrunk["lots"] == 1
    assert preserved["lots"] == 7
    assert preserved["slRiskBudgetOverride"] is True


def test_grade_b_armed_base_without_ftv_stamp_preserves_max_lots():
    """Grade-B armed base: no full-sleeve stamp, but always-max keeps capital lots."""
    allocation = RankedAllocation(
        rank=1,
        budgetInr=180_000,
        remainingBeforeInr=200_000,
        cashReserveInr=0,
        capitalBaseInr=200_000,
        committedInr=0,
        weight=0.9,
    )
    assert _top_rank_full_budget_lots_allowed(
        enabled=True,
        allocation=allocation,
        strict_first_lift=False,
        top_explosion_max=True,
        faded_rip=False,
        post_win_capped=False,
        explosion_always_max=True,
    )


def test_building_armed_base_grade_a_policy_grants_full_sleeve():
    from types import SimpleNamespace

    from app.engines.auto_trader import _building_armed_base_grade_a_policy_max_lots

    allocation = RankedAllocation(
        rank=1,
        budgetInr=180_000,
        remainingBeforeInr=200_000,
        cashReserveInr=0,
        capitalBaseInr=200_000,
        committedInr=0,
        weight=0.9,
    )
    policy = SimpleNamespace(
        mode="BUILDING_ARMED_BASE_GRADE_A",
        allowed=True,
        max_capital_pct=0.90,
    )
    with patch(
        "app.engines.capital_allocator.max_lots_for_capital_pct",
        return_value=33,
    ):
        lots, full_sleeve = _building_armed_base_grade_a_policy_max_lots(
            lots=6,
            symbol="NIFTY",
            premium=81.9,
            policy_decision=policy,
            allocation=allocation,
        )
    assert full_sleeve is True
    assert lots == 33
