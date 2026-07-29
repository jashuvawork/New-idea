"""Jul29 NIFTY 24100 CE — hold winners; don't trail-scratch at +1.45 vs 58pt TP."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.chart_exit_levels import (
    _stamp_entry_baselines,
    compute_live_chart_trail_tuning,
)
from app.engines.simple_profit import evaluate_exit
from app.models.schemas import (
    Breadth,
    MarketPhase,
    OptimizedProfile,
    PaperTrade,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.high_conf_trail_arm_min_target_frac = 0.22
    s.scalp_trail_defer_until_target_frac = 0.20
    s.scalp_trail_defer_min_chart_confidence = 55.0
    s.scalp_stop_min_points = 2.5
    s.scalp_stop_min_hold_seconds = 30
    s.scalp_trail_arm_points = 3.0
    s.scalp_trail_keep_ratio = 0.60
    s.scalp_trail_step_points = 2.0
    s.scalp_trail_tight_arm = 8.0
    s.scalp_trail_tight_points = 3.0
    s.scalp_micro_giveback_points = 3.0
    s.scalp_micro_lock_min_best_points = 4.5
    s.scalp_min_hold_before_micro_lock_seconds = 90
    s.scalp_no_progress_seconds = 150
    s.scalp_no_progress_aligned_seconds = 420
    s.scalp_no_progress_skip_when_aligned = True
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
    s.scalp_never_green_grace_enabled = False
    s.chart_exit_max_target_points = 80.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _nifty_win_trade(*, best: float = 1.45, pnl_pts: float = 0.21) -> PaperTrade:
    entry = 212.6
    return PaperTrade(
        id="1560d28f",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24100.0,
        entryPremium=entry,
        currentPremium=entry + pnl_pts,
        lots=6,
        strategyType=StrategyType.SCALP,
        openedAt=datetime.now(IST) - timedelta(seconds=196),
        bestPnlPoints=best,
        entryContext={
            "selectionMode": "scalp",
            "selectionScore": 115.28,
            "entryChartConfidence": 91.2,
            "chartConfidence": 91.2,
            "exitPlan": {
                "stopPoints": 6.0,
                "targetPoints": 74.66,
                "entryTargetPoints": 58.46,
                "targetPoints2": 80.0,
                "trailArmPoints": 1.35,  # buggy live-crushed arm
                "entryTrailArmPoints": 26.13,  # size-tuned baseline
                "trailKeepRatio": 0.48,
                "entryTrailKeepRatio": 0.60,
                "trailStepPoints": 2.0,
                "microTargetPoints": 6.85,
                "chartConfidence": 91.2,
                "chartConfidenceLive": 91.2,
            },
        },
    )


def test_stamp_freezes_entry_trail_arm():
    plan = _stamp_entry_baselines({
        "stopPoints": 6.0,
        "targetPoints": 58.0,
        "trailArmPoints": 26.0,
        "trailKeepRatio": 0.55,
    })
    assert plan["entryTrailArmPoints"] == 26.0
    assert plan["entryTrailKeepRatio"] == 0.55
    # Second stamp must not overwrite
    plan["trailArmPoints"] = 1.35
    plan2 = _stamp_entry_baselines(plan)
    assert plan2["entryTrailArmPoints"] == 26.0


@patch("app.engines.chart_exit_levels.get_settings")
def test_live_high_conf_raises_trail_arm_from_entry_baseline(mock_settings):
    mock_settings.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24210.0,
        atmStrike=24200.0,
        tradeQualityScore=55.0,
        breadth=Breadth(bias="BULLISH", score=70, aligned=True),
        spotChart=SpotChart(direction="BULLISH", trendStrength=80.0, momentum5Pct=0.15),
    )
    plan = {
        "entryStopPoints": 6.0,
        "entryTargetPoints": 58.46,
        "entryTargetPoints2": 80.0,
        "entryTrailArmPoints": 26.13,
        "entryTrailKeepRatio": 0.55,
        "stopPoints": 6.0,
        "targetPoints": 58.46,
        "trailArmPoints": 1.35,  # last live value — must NOT be the baseline
        "trailKeepRatio": 0.48,
    }
    tuning = compute_live_chart_trail_tuning(
        plan, snap, Side.CALL,
        entry_confidence=91.0,
        live_confidence=91.0,
        entry_premium=212.6,
    )
    # 22% of 58.46 ≈ 12.9; must not stay at 1.35
    assert tuning.trailArmPoints >= 12.0
    assert "high_conf_let_run" in tuning.sources


@patch("app.engines.psychology_hold.get_settings")
@patch("app.engines.bullish_hold.get_settings")
@patch("app.engines.confidence_hold.get_settings")
@patch("app.engines.simple_profit.get_settings")
def test_scratch_trail_deferred_until_target_frac(mock_sp, mock_ch, mock_bh, mock_psy):
    s = _settings()
    mock_sp.return_value = s
    mock_ch.return_value = s
    mock_bh.return_value = s
    mock_psy.return_value = s

    trade = _nifty_win_trade(best=1.45, pnl_pts=0.21)
    # Seed a trail floor as if arm=1.35 already fired
    trade.entryContext["scalpTrailFloorPts"] = 0.7
    trade.entryContext["scalpTrailBestPts"] = 1.45

    reason, _pnl = evaluate_exit(
        trade,
        212.6 + 0.21,
        OptimizedProfile(
            targetPoints=74.66, stopPoints=6.0, microTargetPoints=6.85,
            maxHoldSeconds=480, sessionLabel="morning",
        ),
        lot_multiplier=65,
        trail_arm=1.35,
        trail_keep=0.48,
    )
    assert reason != "scalp_trail_sl", f"must hold winner toward TP, got {reason}"


@patch("app.engines.psychology_hold.get_settings")
@patch("app.engines.bullish_hold.get_settings")
@patch("app.engines.confidence_hold.get_settings")
@patch("app.engines.simple_profit.get_settings")
def test_trail_allowed_after_meaningful_progress(mock_sp, mock_ch, mock_bh, mock_psy):
    s = _settings()
    mock_sp.return_value = s
    mock_ch.return_value = s
    mock_bh.return_value = s
    mock_psy.return_value = s

    # best 15pt > 20% of 58.46 ≈ 11.7 → trail may fire
    trade = _nifty_win_trade(best=15.0, pnl_pts=7.0)
    trade.entryContext["scalpTrailFloorPts"] = 7.2
    trade.entryContext["scalpTrailBestPts"] = 15.0
    reason, pnl = evaluate_exit(
        trade,
        212.6 + 7.0,
        OptimizedProfile(
            targetPoints=74.66, stopPoints=6.0, microTargetPoints=6.85,
            maxHoldSeconds=480, sessionLabel="morning",
        ),
        lot_multiplier=65,
        trail_arm=12.0,
        trail_keep=0.48,
    )
    assert reason == "scalp_trail_sl"
    assert pnl > 0
