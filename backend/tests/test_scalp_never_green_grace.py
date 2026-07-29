"""Jul29 SENSEX 77500 CE — never-green shakeout must not kill recovering ITM scalp."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.capital_allocator import tune_exit_plan_for_position
from app.engines.session_mode_feedback import (
    cap_lots_until_first_green,
    session_has_green_mode,
)
from app.engines.simple_profit import evaluate_exit
from app.models.schemas import (
    AutoTraderState,
    OptimizedProfile,
    PaperTrade,
    Side,
    StrategyType,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.scalp_never_green_grace_enabled = True
    s.scalp_never_green_grace_seconds = 150.0
    s.scalp_never_green_stop_mult = 2.5
    s.scalp_never_green_min_chart_confidence = 55.0
    s.scalp_never_green_min_premium_inr = 80.0
    s.size_until_first_green_enabled = True
    s.size_until_first_green_lot_cap = 6
    s.size_until_first_green_modes_csv = "explosion,scalp"
    s.size_until_first_green_require_closed_win = True
    s.position_sl_cap_pct = 0.08
    s.position_tp_target_pct = 0.12
    s.position_min_risk_reward = 1.2
    s.position_sl_preserve_natural_frac = 0.45
    s.per_trade_capital_pct = 0.95
    s.scalp_stop_points = 3.0
    s.scalp_stop_min_points = 2.5
    s.scalp_stop_min_hold_seconds = 30
    s.scalp_trail_arm_points = 3.0
    s.scalp_trail_keep_ratio = 0.6
    s.scalp_trail_step_points = 2.0
    s.scalp_trail_tight_arm = 8.0
    s.scalp_trail_tight_points = 3.0
    s.scalp_micro_giveback_points = 3.0
    s.scalp_micro_lock_min_best_points = 4.0
    s.scalp_min_hold_before_micro_lock_seconds = 90
    s.runner_micro_giveback_points = 4.0
    s.runner_min_best_points = 5.0
    s.runner_trail_keep_ratio = 0.38
    s.emergency_stop_enabled = False
    s.bullish_hold_enabled = False
    s.psychology_hold_enabled = False
    s.chart_confidence_hold_enabled = True
    s.chart_confidence_hold_min_confidence = 62.0
    s.chart_confidence_hold_min_target_pct = 0.85
    s.chart_confidence_hold_max_seconds = 600
    s.chart_confidence_hold_stop_mult = 1.0
    s.chart_confidence_half_tp_lock_pct = 0.5
    s.chart_confidence_half_tp_giveback_ratio = 0.4
    s.high_confidence_min_score = 72.0
    s.high_confidence_hold_enabled = True
    s.high_confidence_max_hold_multiplier = 1.8
    s.high_confidence_micro_min_best_points = 6.0
    s.high_confidence_min_hold_before_micro_seconds = 180
    s.high_confidence_micro_giveback_points = 4.5
    s.high_confidence_trail_keep_ratio = 0.55
    s.all_day_min_chart_confidence = 62.0
    s.scalp_no_progress_seconds = 150
    s.scalp_no_progress_aligned_seconds = 420
    s.scalp_no_progress_skip_when_aligned = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _sensex_77500_trade(*, hold_s: float = 49.0) -> PaperTrade:
    return PaperTrade(
        id="cabd72df",
        symbol="SENSEX",
        side=Side.CALL,
        strike=77500.0,
        entryPremium=278.95,
        currentPremium=272.95,
        lots=32,
        strategyType=StrategyType.SCALP,
        openedAt=datetime.now(IST) - timedelta(seconds=hold_s),
        bestPnlPoints=0.0,
        entryContext={
            "selectionMode": "scalp",
            "selectionScore": 109.91,
            "entryChartConfidence": 88.4,
            "chartConfidence": 88.4,
            "exitPlan": {
                "stopPoints": 6.0,
                "targetPoints": 45.0,
                "chartConfidence": 88.4,
            },
        },
    )


@patch("app.engines.psychology_hold.get_settings")
@patch("app.engines.bullish_hold.get_settings")
@patch("app.engines.confidence_hold.get_settings")
@patch("app.engines.simple_profit.get_settings")
def test_never_green_grace_defers_77500_style_dip(mock_sp, mock_ch, mock_bh, mock_psy):
    s = _settings()
    mock_sp.return_value = s
    mock_ch.return_value = s
    mock_bh.return_value = s
    mock_psy.return_value = s

    trade = _sensex_77500_trade(hold_s=49.0)
    reason, pnl = evaluate_exit(
        trade,
        272.95,
        OptimizedProfile(
            targetPoints=45.0, stopPoints=6.0, microTargetPoints=4.0,
            maxHoldSeconds=480, sessionLabel="morning",
        ),
        lot_multiplier=20,
    )
    assert reason is None, f"should defer never-green dip, got {reason}"
    assert pnl < 0


@patch("app.engines.psychology_hold.get_settings")
@patch("app.engines.bullish_hold.get_settings")
@patch("app.engines.confidence_hold.get_settings")
@patch("app.engines.simple_profit.get_settings")
def test_never_green_hard_floor_still_stops(mock_sp, mock_ch, mock_bh, mock_psy):
    s = _settings()
    mock_sp.return_value = s
    mock_ch.return_value = s
    mock_bh.return_value = s
    mock_psy.return_value = s

    trade = _sensex_77500_trade(hold_s=49.0)
    # −16pt vs 2.5×6=15 hard floor → kill
    reason, pnl = evaluate_exit(
        trade,
        278.95 - 16.0,
        OptimizedProfile(
            targetPoints=45.0, stopPoints=6.0, microTargetPoints=4.0,
            maxHoldSeconds=480, sessionLabel="morning",
        ),
        lot_multiplier=20,
    )
    assert reason == "simple_stop_loss"
    assert pnl < 0


@patch("app.engines.session_mode_feedback.get_settings")
def test_fleeting_best_on_red_scalp_does_not_unlock_size(mock_settings):
    """Jul29: 24100 CE best+1.5 then −₹72 must not unlock 32-lot SENSEX."""
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="062a83be",
            symbol="NIFTY",
            side=Side.CALL,
            strike=24100.0,
            entryPremium=210.85,
            currentPremium=211.85,
            lots=6,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.SCALP,
            pnlInr=-71.78,
            bestPnlPoints=1.5,
            entryContext={"selectionMode": "scalp"},
        )
    ]
    assert session_has_green_mode(state, "scalp") is False
    assert cap_lots_until_first_green(32, state, mode="scalp") == 6


@patch("app.engines.capital_allocator.lot_multiplier", return_value=20)
@patch("app.engines.capital_allocator.get_capital_snapshot")
@patch("app.engines.capital_allocator.get_settings")
def test_size_tune_preserves_natural_stop_floor(mock_settings, mock_cap, _mult):
    s = _settings()
    mock_settings.return_value = s
    cap = MagicMock()
    cap.perTradeCapitalInr = 190_000.0
    cap.availableMarginInr = 200_000.0
    mock_cap.return_value = cap

    plan = {
        "stopPoints": 27.9,  # 10% of ₹279
        "targetPoints": 45.0,
        "microTargetPoints": 4.0,
        "trailArmPoints": 3.5,
        "trailStepPoints": 2.0,
        "reasoning": ["Scalp SL from premium 278.9 x 10% = 27.9pt"],
    }
    tuned = tune_exit_plan_for_position(plan, lots=32, premium=278.95, symbol="SENSEX")
    # Budget cap alone ≈ 6pt; preserve 45% of 27.9 ≈ 12.6
    assert tuned["stopPoints"] >= 12.0
    assert tuned["stopPoints"] < 27.9
