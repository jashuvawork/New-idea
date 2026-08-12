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


@patch("app.engines.explosion_profit.evaluate_explosion_exit", return_value=(None, 0.0))
@patch("app.engines.adaptive_exits.get_settings")
def test_adaptive_trail_does_not_cut_stage_ladder_hc_runner(_mock_settings, _mock_exp):
    """Aug12 NIFTY 24350 PE: best ~₹135 (+36.7) then adaptive_trail_sl at ~₹120.

    Explosion/stage path held; fallback must not book via stamped keep 0.56.
    """
    trade = _trade(entry=98.32)
    trade.bestPnlPoints = 36.74
    trade.entryContext = {
        "highConviction": True,
        "maxProfitCapture": True,
        "momentStageLadder": True,
        "momentType": "flat_then_vertical",
        "ictFlatThenVertical": True,
        "stageSize": 75.0,
        "projectedMaxTp": 800.0,
        "psychologyExitBias": "LET_RUNNERS",
        "chartConfidence": 89.2,
        "breadth": {"bias": "BEARISH", "aligned": True},
        "exitPlan": {
            "trailKeepRatio": 0.561,
            "momentStageLadder": True,
            "projectedMaxTp": 800.0,
            "stageSize": 75.0,
        },
    }
    plan = AdaptiveExitPlan(
        stopPoints=23.54,
        targetPoints=48.21,
        trailArmPoints=13.53,
        trailKeepRatio=0.561,
        microTargetPoints=3.0,
        exitBias="LET_RUNNERS",
    )

    with patch("app.engines.bullish_hold.get_settings") as bh, patch(
        "app.engines.confidence_hold.get_settings"
    ) as conf, patch(
        "app.engines.ict_breakout_monitor.ict_trail_arm_multiplier", return_value=1.0,
    ):
        s = MagicMock()
        s.bullish_hold_enabled = True
        s.extreme_explosion_hold_min_best_points = 8.0
        s.high_conviction_trail_keep_ratio = 0.30
        s.runner_min_best_points = 6.0
        s.chart_confidence_hold_enabled = True
        s.chart_confidence_hold_min_confidence = 55.0
        s.high_confidence_min_score = 90.0
        bh.return_value = s
        conf.return_value = s
        _mock_settings.return_value = s

        # +20.2pt is below plan keep 0.56×36.74≈20.6 — old bug exited adaptive_trail_sl.
        reason, _ = evaluate_adaptive_explosion_exit(
            trade, 118.5, plan, "ELITE", 65, current_velocity_3s=1.0,
        )

    assert reason is None


@patch("app.engines.explosion_profit.evaluate_explosion_exit", return_value=(None, 0.0))
@patch("app.engines.adaptive_exits.get_settings")
def test_adaptive_trail_uses_hc_keep_when_no_stage_ladder(_mock_settings, _mock_exp):
    """High-conviction without stage ladder uses wider HC keep (0.30), not 0.56."""
    trade = _trade(entry=98.32)
    trade.bestPnlPoints = 36.74
    trade.entryContext = {
        "highConviction": True,
        "chartConfidence": 89.2,
        "breadth": {"bias": "BEARISH", "aligned": True},
        "selectionScore": 100.0,
    }
    plan = AdaptiveExitPlan(
        stopPoints=23.54,
        targetPoints=48.21,
        trailArmPoints=13.53,
        trailKeepRatio=0.561,
        microTargetPoints=3.0,
    )

    with patch("app.engines.bullish_hold.get_settings") as bh, patch(
        "app.engines.confidence_hold.should_defer_profit_lock", return_value=False,
    ), patch(
        "app.engines.confidence_hold.is_confidence_runner_hold", return_value=False,
    ), patch(
        "app.engines.ict_breakout_monitor.ict_trail_arm_multiplier", return_value=1.0,
    ):
        s = MagicMock()
        s.bullish_hold_enabled = True
        s.extreme_explosion_hold_min_best_points = 8.0
        s.high_conviction_trail_keep_ratio = 0.30
        s.runner_min_best_points = 6.0
        bh.return_value = s
        _mock_settings.return_value = s

        # Still above HC floor 0.30×36.74≈11.0 → hold
        reason_hold, _ = evaluate_adaptive_explosion_exit(
            trade, 118.5, plan, "ELITE", 65, current_velocity_3s=1.0,
        )
        # Below HC floor → adaptive trail may fire
        reason_cut, _ = evaluate_adaptive_explosion_exit(
            trade, 108.0, plan, "ELITE", 65, current_velocity_3s=0.5,
        )

    assert reason_hold is None
    assert reason_cut == "adaptive_trail_sl"
