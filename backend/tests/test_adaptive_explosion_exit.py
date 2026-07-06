"""Adaptive SL on explosion trades — wider stops on strong momentum."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.engines.adaptive_exits import AdaptiveExitPlan, evaluate_adaptive_explosion_exit
from app.engines.explosion_profit import (
    default_explosion_exit_params,
    evaluate_explosion_exit,
    explosion_exit_params_from_plan,
)
from app.models.schemas import PaperTrade, Side, StrategyType


def _trade(entry: float = 100.0) -> PaperTrade:
    return PaperTrade(
        id="e1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24000,
        lots=40,
        entryPremium=entry,
        currentPremium=entry,
        openedAt=datetime.now(timezone.utc),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=0.0,
    )


def test_wider_adaptive_stop_delays_explosion_stop_loss():
    default = default_explosion_exit_params("EXPLODING")
    wide = explosion_exit_params_from_plan(
        AdaptiveExitPlan(
            stopPoints=6.0,
            targetPoints=14.0,
            trailArmPoints=5.0,
            trailKeepRatio=0.65,
            microTargetPoints=3.0,
        ),
        "EXPLODING",
    )
    trade = _trade()

    with patch("app.engines.explosion_profit.get_settings") as mock_settings:
        settings = MagicMock()
        settings.emergency_stop_enabled = False
        settings.explosion_stop_min_hold_seconds = 0
        settings.explosion_trail_tight_arm = 12.0
        settings.explosion_trail_tight_points = 3.0
        settings.explosion_trail_step_points = 2.0
        settings.runner_trail_keep_ratio = 0.45
        settings.runner_min_best_points = 6.0
        settings.runner_micro_giveback_points = 2.5
        settings.explosion_trail_keep_ratio = 0.65
        settings.explosion_trail_arm_points = 4.0
        settings.explosion_initial_stop_points = 4.0
        settings.explosion_no_progress_seconds = 90
        mock_settings.return_value = settings

        default_reason, _ = evaluate_explosion_exit(trade, 95.5, "EXPLODING", 65)
        adaptive_reason, _ = evaluate_explosion_exit(
            trade, 95.5, "EXPLODING", 65, params=wide,
        )

    assert default_reason == "explosion_stop_loss"
    assert adaptive_reason is None
    assert wide.adaptive_stop is True


@patch("app.engines.adaptive_exits.get_settings")
def test_adaptive_explosion_exit_uses_plan_trail(mock_settings):
    settings = MagicMock()
    settings.adaptive_exits_enabled = True
    mock_settings.return_value = settings

    trade = _trade()
    trade.bestPnlPoints = 10.0
    trade.entryContext = {"explosionTrailFloorPts": 6.5}
    plan = AdaptiveExitPlan(
        stopPoints=5.0,
        targetPoints=14.0,
        trailArmPoints=4.0,
        trailKeepRatio=0.7,
        microTargetPoints=3.0,
    )

    with patch("app.engines.explosion_profit.get_settings") as exp_settings:
        s = MagicMock()
        s.emergency_stop_enabled = False
        s.explosion_stop_min_hold_seconds = 0
        s.explosion_trail_tight_arm = 12.0
        s.explosion_trail_tight_points = 3.0
        s.explosion_trail_step_points = 2.0
        s.runner_trail_keep_ratio = 0.45
        s.runner_min_best_points = 6.0
        s.runner_micro_giveback_points = 2.5
        s.explosion_trail_keep_ratio = 0.65
        s.explosion_trail_arm_points = 4.0
        s.explosion_initial_stop_points = 4.0
        exp_settings.return_value = s

        reason, pnl = evaluate_adaptive_explosion_exit(
            trade, 105.5, plan, "EXPLODING", 65, current_velocity_3s=0.0,
        )

    assert reason == "explosion_trail_sl"
    assert pnl > 0


@patch("app.engines.adaptive_exits.get_settings")
def test_adaptive_stop_fires_at_plan_stop_even_while_expanding(mock_settings):
    """Stop must fire at plan SL before no_progress — even if velocity still hot."""
    settings = MagicMock()
    settings.explosion_stop_min_hold_seconds = 0
    mock_settings.return_value = settings

    trade = _trade(entry=140.0)
    trade.entryContext = {"velocity3s": 4.0}
    plan = AdaptiveExitPlan(
        stopPoints=8.0,
        targetPoints=14.0,
        trailArmPoints=5.0,
        trailKeepRatio=0.65,
        microTargetPoints=3.0,
    )

    with patch("app.engines.explosion_profit.get_settings") as exp_settings:
        s = MagicMock()
        s.emergency_stop_enabled = False
        s.explosion_stop_min_hold_seconds = 0
        s.explosion_trail_tight_arm = 12.0
        s.explosion_trail_tight_points = 3.0
        s.explosion_trail_step_points = 2.0
        s.runner_trail_keep_ratio = 0.45
        s.runner_min_best_points = 6.0
        s.runner_micro_giveback_points = 2.5
        s.explosion_trail_keep_ratio = 0.65
        s.explosion_trail_arm_points = 4.0
        s.explosion_initial_stop_points = 4.0
        s.explosion_no_progress_enabled = True
        s.explosion_no_progress_seconds = 90
        s.explosion_no_progress_aligned_seconds = 420
        s.explosion_no_progress_skip_when_aligned = True
        exp_settings.return_value = s

        reason, _ = evaluate_adaptive_explosion_exit(
            trade, 132.0, plan, "EXPLODING", 20, current_velocity_3s=3.5,
        )

    assert reason == "adaptive_stop_loss"


@patch("app.engines.adaptive_exits.get_settings")
def test_adaptive_stop_fires_when_momentum_fades(mock_settings):
    settings = MagicMock()
    settings.explosion_stop_min_hold_seconds = 0
    mock_settings.return_value = settings

    trade = _trade(entry=140.0)
    trade.entryContext = {"velocity3s": 4.0}
    plan = AdaptiveExitPlan(
        stopPoints=8.0,
        targetPoints=14.0,
        trailArmPoints=5.0,
        trailKeepRatio=0.65,
        microTargetPoints=3.0,
    )

    with patch("app.engines.explosion_profit.get_settings") as exp_settings:
        s = MagicMock()
        s.emergency_stop_enabled = False
        s.explosion_stop_min_hold_seconds = 0
        s.explosion_trail_tight_arm = 12.0
        s.explosion_trail_tight_points = 3.0
        s.explosion_trail_step_points = 2.0
        s.runner_trail_keep_ratio = 0.45
        s.runner_min_best_points = 6.0
        s.runner_micro_giveback_points = 2.5
        s.explosion_trail_keep_ratio = 0.65
        s.explosion_trail_arm_points = 4.0
        s.explosion_initial_stop_points = 4.0
        s.explosion_no_progress_seconds = 90
        exp_settings.return_value = s

        reason, pnl = evaluate_adaptive_explosion_exit(
            trade, 130.0, plan, "EXPLODING", 20, current_velocity_3s=0.5,
        )

    assert reason == "adaptive_stop_loss"
    assert pnl < 0
