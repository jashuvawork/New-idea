"""Top-score / full-budget entries bypass pre-entry per_trade_risk_exceeded."""

from unittest.mock import MagicMock, patch

from app.engines.auto_trader import _ignore_per_trade_risk_cap_for_entry
from app.engines.capital_allocator import RankedAllocation
from app.engines.entry_day_adaptive import EntryDayAdaptivePolicy
from app.engines.risk_engine import RiskEngine
from app.models.schemas import AutoTraderState, Side, StrategyType


def _allocation(rank: int = 1) -> RankedAllocation:
    return RankedAllocation(
        rank=rank,
        budgetInr=180_000,
        remainingBeforeInr=200_000,
        cashReserveInr=0,
        capitalBaseInr=200_000,
        committedInr=0,
        weight=0.9,
    )


def _normal_policy(**overrides) -> EntryDayAdaptivePolicy:
    base = dict(
        day_type="NORMAL",
        day_mode="NORMAL",
        confidence_tier="MEDIUM",
        coil_top_max_position_frac=0.50,
        coil_top_min_run_pct=0.06,
        coil_top_max_run_pct=0.28,
        building_cold_base_min_velocity_3s=1.2,
        cold_base_lot_cap=3,
        block_building_watch_cold_base=False,
        probe_max_capital_pct=0.40,
        consolidation_max_pad_pct=24.0,
        consolidation_cold_v3_at_base=True,
        top_score_risk_bypass_min_score=80.0,
        bullish_day_relief=False,
    )
    base.update(overrides)
    return EntryDayAdaptivePolicy(**base)


@patch("app.engines.entry_day_adaptive.resolve_entry_day_policy")
@patch("app.engines.auto_trader.get_settings")
def test_top_rank_full_budget_lots_bypasses_risk_cap(mock_settings, mock_policy):
    mock_settings.return_value = MagicMock(
        top_score_per_trade_risk_bypass_enabled=True,
    )
    mock_policy.return_value = _normal_policy()
    assert _ignore_per_trade_risk_cap_for_entry(
        elite_full_lot=False,
        top_rank_full_budget_lots=True,
        high_conviction=False,
        allocation=_allocation(),
        candidate_score=50.0,
        trap_cap_locked=False,
    )


@patch("app.engines.entry_day_adaptive.resolve_entry_day_policy")
@patch("app.engines.auto_trader.get_settings")
def test_rank_one_top_score_bypasses_risk_cap(mock_settings, mock_policy):
    mock_settings.return_value = MagicMock(
        top_score_per_trade_risk_bypass_enabled=True,
    )
    mock_policy.return_value = _normal_policy()
    assert _ignore_per_trade_risk_cap_for_entry(
        elite_full_lot=False,
        top_rank_full_budget_lots=False,
        high_conviction=False,
        allocation=_allocation(rank=1),
        candidate_score=265.9,
        trap_cap_locked=False,
    )


@patch("app.engines.entry_day_adaptive.resolve_entry_day_policy")
@patch("app.engines.auto_trader.get_settings")
def test_low_score_rank_one_does_not_bypass(mock_settings, mock_policy):
    mock_settings.return_value = MagicMock(
        top_score_per_trade_risk_bypass_enabled=True,
    )
    mock_policy.return_value = _normal_policy()
    assert not _ignore_per_trade_risk_cap_for_entry(
        elite_full_lot=False,
        top_rank_full_budget_lots=False,
        high_conviction=False,
        allocation=_allocation(rank=1),
        candidate_score=60.0,
        trap_cap_locked=False,
    )


@patch("app.engines.entry_day_adaptive.resolve_entry_day_policy")
@patch("app.engines.auto_trader.get_settings")
def test_trap_cap_locked_blocks_bypass(mock_settings, mock_policy):
    mock_settings.return_value = MagicMock(
        top_score_per_trade_risk_bypass_enabled=True,
    )
    mock_policy.return_value = _normal_policy()
    assert not _ignore_per_trade_risk_cap_for_entry(
        elite_full_lot=True,
        top_rank_full_budget_lots=True,
        high_conviction=True,
        allocation=_allocation(),
        candidate_score=200.0,
        trap_cap_locked=True,
    )


@patch("app.engines.risk_engine.get_capital_snapshot")
@patch("app.engines.risk_engine.get_settings")
def test_risk_engine_accepts_when_ignore_flag_set(mock_settings, mock_capital):
    settings = MagicMock()
    settings.aggressive_lot_sizing = False
    settings.aggressive_max_open_scalps = 3
    settings.swing_max_open = 1
    settings.per_trade_capital_pct = 0.9
    settings.max_risk_per_trade_inr = 4_000
    settings.swing_max_loss_inr = 20_000
    settings.emergency_stop_enabled = False
    settings.daily_loss_stop_inr = 20_000
    settings.block_duplicate_open_leg = True
    settings.enable_live_trading = False
    settings.live_hold_to_structural_sl = False
    settings.ftv_ranked_allocation_enabled = True
    settings.ftv_allocation_max_positions = 3
    settings.ftv_allocation_max_same_side = 2
    settings.auto_trading_enabled = True
    settings.execution_stop_endpoint_pauses_entries = False
    mock_settings.return_value = settings

    cap = MagicMock()
    cap.availableMarginInr = 200_000
    cap.perTradeCapitalInr = 180_000
    mock_capital.return_value = cap

    engine = RiskEngine()
    ok_blocked, reason_blocked = engine.check_new_entry(
        AutoTraderState(running=True),
        "NIFTY",
        Side.CALL,
        lots=10,
        premium=80.0,
        lot_multiplier=65,
        strategy_type=StrategyType.EXPLOSIVE,
        strike=23950.0,
        stop_points=16.0,
        ignore_per_trade_risk_cap=False,
    )
    assert not ok_blocked
    assert reason_blocked == "per_trade_risk_exceeded"

    ok, reason = engine.check_new_entry(
        AutoTraderState(running=True),
        "NIFTY",
        Side.CALL,
        lots=10,
        premium=80.0,
        lot_multiplier=65,
        strategy_type=StrategyType.EXPLOSIVE,
        strike=23950.0,
        stop_points=16.0,
        ignore_per_trade_risk_cap=True,
    )
    assert ok, reason
    assert reason == "passed"


@patch("app.engines.entry_day_adaptive.resolve_entry_day_policy")
@patch("app.engines.auto_trader.get_settings")
def test_worst_day_disables_top_score_bypass(mock_settings, mock_policy):
    mock_settings.return_value = MagicMock(
        top_score_per_trade_risk_bypass_enabled=True,
    )
    mock_policy.return_value = _normal_policy(
        day_type="WORST",
        top_score_risk_bypass_min_score=0.0,
    )
    assert not _ignore_per_trade_risk_cap_for_entry(
        elite_full_lot=False,
        top_rank_full_budget_lots=False,
        high_conviction=False,
        allocation=_allocation(rank=1),
        candidate_score=265.9,
        trap_cap_locked=False,
    )
