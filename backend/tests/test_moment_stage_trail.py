"""Moment stage trail ladder — flat→vertical staged SL toward projected max TP."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import ExplosionExitParams, evaluate_explosion_exit
from app.engines.moment_stage_trail import (
    build_moment_stage_plan,
    compute_projected_max_tp,
    compute_stage_size,
    stage_trail_floor_pts,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.moment_stage_trail_enabled = True
    s.moment_stage_count = 8
    s.moment_stage_min_size = 5.0
    s.moment_stage_max_size = 55.0
    s.moment_stage_min_projected_tp = 40.0
    s.moment_stage_max_projected_tp = 500.0
    s.moment_stage_max_tp_frac_of_premium = 8.0
    s.moment_stage_base_extension_mult = 3.0
    s.moment_stage_mega_extension_mult = 4.0
    s.moment_stage_heat_velocity_3s = 3.0
    s.moment_stage_heat_volume_surge = 1.8
    s.moment_stage_giveback_ratio = 0.50
    s.moment_stage_late_giveback_ratio = 1.0
    s.moment_stage_late_progress = 0.70
    s.moment_stage_min_remain_points = 1.0
    s.moment_stage_extend_trigger_frac = 0.92
    s.ict_max_profit_target_points = 180.0
    s.ict_max_profit_skip_hard_target = True
    s.ict_max_profit_trail_keep_ratio = 0.42
    s.explosion_peak_fade_lock_enabled = False
    s.explosion_peak_capture_enabled = False
    s.explosion_faded_rip_no_green_exit_enabled = False
    s.explosion_stop_min_hold_seconds = 0
    s.emergency_stop_enabled = False
    s.explosion_trail_arm_points = 4.0
    s.explosion_trail_keep_ratio = 0.65
    s.explosion_trail_step_points = 3.5
    s.explosion_trail_tight_arm = 999.0
    s.explosion_trail_tight_points = 0.0
    s.explosion_target_standard = 12.0
    s.explosion_no_progress_enabled = False
    s.runner_min_best_points = 25.0
    s.runner_trail_keep_ratio = 0.55
    s.runner_micro_giveback_points = 4.0
    s.high_conviction_trail_keep_ratio = 0.30
    s.high_conviction_defer_profit_lock = True
    s.chart_confidence_defer_tp_min = 90.0
    s.chart_confidence_half_tp_giveback_ratio = 0.40
    s.bullish_hold_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _trade(
    *,
    entry: float = 200.0,
    best: float = 250.0,
    current: float = 450.0,
    projected: float = 440.0,
    stage: float = 50.0,
) -> PaperTrade:
    ctx = {
        "selectionMode": "explosion",
        "explosionTier": "ELITE",
        "ictFlatThenVertical": True,
        "momentType": "flat_then_vertical",
        "momentStageLadder": True,
        "projectedMaxTp": projected,
        "stageSize": stage,
        "stageGivebackRatio": 0.50,
        "stageLateGivebackRatio": 1.0,
        "stageLateProgress": 0.70,
        "maxProfitCapture": True,
        "localBaseBasePremium": 200.0,
        "exitPlan": {
            "stopPoints": 20.0,
            "targetPoints": 25.0,
            "trailArmPoints": 8.0,
            "trailKeepRatio": 0.42,
            "microTargetPoints": 9.0,
            "momentStageLadder": True,
            "projectedMaxTp": projected,
            "stageSize": stage,
            "stageGivebackRatio": 0.50,
            "stageLateGivebackRatio": 1.0,
            "stageLateProgress": 0.70,
        },
    }
    return PaperTrade(
        id="sensex-pe-stage",
        symbol="SENSEX",
        side=Side.PUT,
        strike=77200.0,
        entryPremium=entry,
        currentPremium=current,
        lots=2,
        openedAt=datetime.now(IST) - timedelta(minutes=20),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        pnlPoints=current - entry,
        entryContext=ctx,
    )


def _params() -> ExplosionExitParams:
    return ExplosionExitParams(
        stop_points=20.0,
        target_points=25.0,
        trail_arm_points=8.0,
        trail_keep_ratio=0.42,
        micro_target_points=9.0,
        adaptive_stop=True,
    )


@patch("app.engines.moment_stage_trail.get_settings")
def test_sensex_picture_projects_large_max_tp(mock_s):
    """Flat~200 entry, already +100 from base, fib/heat → large projected ceiling."""
    mock_s.return_value = _settings()
    projected = compute_projected_max_tp(
        entry_premium=300.0,
        base_premium=200.0,
        exit_plan={"targetPoints2": 180.0},
        velocity_3s=8.0,
        volume_surge=2.5,
        session_move_pct=90.0,
        premium_fvg=True,
        flat_then_vertical=True,
        mega_rip=False,
        max_profit=True,
    )
    assert projected >= 200.0
    stage = compute_stage_size(440.0, _settings())
    assert 45.0 <= stage <= 55.0


@patch("app.engines.moment_stage_trail.get_settings")
def test_stage_250_trails_at_225(mock_s):
    mock_s.return_value = _settings()
    trade = _trade(best=250.0, current=450.0)
    floor = stage_trail_floor_pts(trade, 250.0, settings=_settings())
    assert floor == 225.0


@patch("app.engines.moment_stage_trail.get_settings")
def test_stage_400_trails_at_350(mock_s):
    """Late progress (≥70% of 440) widens giveback to a full stage → 400−50=350."""
    mock_s.return_value = _settings()
    trade = _trade(best=400.0, current=600.0)
    floor = stage_trail_floor_pts(trade, 400.0, settings=_settings())
    assert floor == 350.0


@patch("app.engines.moment_stage_trail.get_settings")
def test_hold_above_stage_floor_toward_max(mock_s):
    """At +400 live +380 — above 350 floor — keep holding for 440."""
    mock_s.return_value = _settings()
    trade = _trade(best=400.0, current=580.0)  # +380
    floor = stage_trail_floor_pts(trade, 400.0, settings=_settings())
    assert floor == 350.0
    assert (580.0 - 200.0) > floor


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_evaluate_exit_books_stage_trail_pullback(mock_ms, mock_s, _hc, _mp):
    """Hit +400 then pull back to +340 → explosion_stage_trail."""
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _trade(entry=200.0, best=400.0, current=540.0)  # +340
    reason, pnl = evaluate_explosion_exit(
        trade, 540.0, "ELITE", 10, params=_params(), live_velocity_3s=0.4,
    )
    assert reason == "explosion_stage_trail"
    assert pnl > 0


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_evaluate_exit_holds_while_above_floor(mock_ms, mock_s, _hc, _mp):
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _trade(entry=200.0, best=400.0, current=580.0)  # +380 > 350
    reason, _pnl = evaluate_explosion_exit(
        trade, 580.0, "ELITE", 10, params=_params(), live_velocity_3s=2.0,
    )
    assert reason != "explosion_stage_trail"
    # Still below projected 440 — should not hard-TP yet.
    assert reason != "explosion_target_hit"


@patch("app.engines.moment_stage_trail.get_settings")
def test_build_plan_for_flat_then_vertical(mock_s):
    mock_s.return_value = _settings()
    plan = build_moment_stage_plan(
        entry_premium=250.0,
        base_premium=200.0,
        exit_plan={"targetPoints2": 120.0},
        velocity_3s=5.0,
        volume_surge=2.0,
        flat_then_vertical=True,
        max_profit=True,
    )
    assert plan is not None
    assert plan["momentStageLadder"] is True
    assert plan["projectedMaxTp"] >= 40.0
    assert plan["stageSize"] >= 5.0
