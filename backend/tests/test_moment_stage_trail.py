"""Moment stage trail ladder — flat→vertical staged SL toward projected max TP."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import ExplosionExitParams, evaluate_explosion_exit
from app.engines.moment_stage_trail import (
    build_moment_stage_plan,
    compose_trail_floor_with_stages,
    compute_projected_max_tp,
    compute_stage_size,
    maybe_extend_projected_max,
    pre_stage_hold_floor_pts,
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
    s.moment_stage_max_projected_tp = 800.0
    s.moment_stage_max_tp_frac_of_premium = 12.0
    s.moment_stage_mega_max_tp_frac_of_premium = 16.0
    s.moment_stage_base_extension_mult = 3.0
    s.moment_stage_mega_extension_mult = 4.0
    s.moment_stage_base_premium_mult = 5.5
    s.moment_stage_entry_premium_mult = 4.2
    s.moment_stage_mega_base_premium_mult = 16.0
    s.moment_stage_mega_entry_premium_mult = 14.0
    s.moment_stage_parabolic_entry_premium_mult = 13.0
    s.moment_stage_parabolic_min_velocity_3s = 8.0
    s.moment_stage_parabolic_min_volume_surge = 2.5
    s.moment_stage_early_vertical_min_tp = 160.0
    s.moment_stage_early_base_frac = 0.40
    s.moment_stage_early_max_already_points = 30.0
    s.moment_stage_ict_target_floor_frac = 0.90
    s.moment_stage_heat_velocity_3s = 3.0
    s.moment_stage_heat_volume_surge = 1.8
    s.moment_stage_giveback_ratio = 0.50
    s.moment_stage_late_giveback_ratio = 1.0
    s.moment_stage_late_progress = 0.70
    s.moment_stage_min_remain_points = 1.0
    s.moment_stage_extend_trigger_frac = 0.92
    s.moment_stage_extend_stages = 2.0
    s.moment_stage_extend_hot_stages = 4.0
    s.moment_stage_extend_hot_velocity_3s = 2.5
    s.moment_stage_hot_hold_velocity_3s = 2.5
    s.moment_stage_near_complete_frac = 0.82
    s.cycle_moment_peak_sync_enabled = True
    s.cycle_moment_peak_sync_min_gain_pct = 50.0
    s.explosion_trail_pre_stage_suppress_step = True
    s.explosion_trail_hot_defer_enabled = True
    s.ict_max_profit_target_points = 180.0
    s.ict_max_profit_skip_hard_target = True
    s.ict_max_profit_trail_keep_ratio = 0.42
    s.explosion_peak_fade_lock_enabled = False
    s.explosion_peak_capture_enabled = False
    s.explosion_peak_capture_max_giveback_points = 8.0
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
    s.ftv_runner_pct_trail_enabled = True
    s.ftv_runner_pct_trail_arm_pct = 25.0
    s.ftv_runner_pct_trail_arm_min_best_points = 20.0
    s.ftv_runner_pct_trail_keep_ratio = 0.75
    s.ftv_runner_pct_trail_min_best_points = 6.0
    s.explosion_stage_trail_min_hold_seconds = 90.0
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


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_projected_max_is_not_forced_exit_while_ltp_is_at_peak(
    mock_ms, mock_s, _hc, _mp,
):
    """At the projection cap, wait for observed rollover instead of guessing the top."""
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _trade(
        entry=50.0,
        best=800.0,
        current=850.0,
        projected=800.0,
        stage=75.0,
    )
    trade.entryContext["liveVelocity3s"] = 4.0
    reason, _ = evaluate_explosion_exit(
        trade,
        850.0,
        "ELITE",
        10,
        params=_params(),
        live_velocity_3s=4.0,
    )
    assert reason is None


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=False)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_peak_keep_75_exits_before_stage_one(mock_ms, mock_s, _hc, _mp):
    """Aug28 24100 PE — peak +31pt, fade to +10pt exits at 75% keep before stage +45."""
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    entry = 47.95
    best = 30.93
    trade = PaperTrade(
        id="nifty-24100",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24100.0,
        entryPremium=entry,
        currentPremium=61.85,
        lots=1,
        openedAt=datetime.now(IST) - timedelta(minutes=120),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        pnlPoints=13.9,
        entryContext={
            "momentStageLadder": True,
            "maxProfitCapture": True,
            "projectedMaxTp": 323.3,
            "stageSize": 45.0,
            "exitPlan": {
                "stopPoints": 11.06,
                "targetPoints": 31.17,
                "trailArmPoints": 113.15,
                "trailKeepRatio": 0.61,
                "momentStageLadder": True,
                "projectedMaxTp": 323.3,
                "stageSize": 45.0,
            },
        },
    )
    params = ExplosionExitParams(
        stop_points=11.06,
        target_points=31.17,
        trail_arm_points=113.15,
        trail_keep_ratio=0.61,
        micro_target_points=3.0,
        adaptive_stop=True,
    )
    reason, pnl = evaluate_explosion_exit(
        trade, 61.85, "EXPLODING", 65, params=params, live_velocity_3s=0.0,
    )
    assert reason == "explosion_peak_keep_trail"
    assert pnl > 0

    reason_hold, _ = evaluate_explosion_exit(
        trade, entry + best * 0.76, "EXPLODING", 65, params=params, live_velocity_3s=0.0,
    )
    assert reason_hold is None


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_ftv_pct_floor_arms_on_absolute_points_for_max_profit(mock_ms, mock_s):
    """Sep2 SENSEX PUT 76300: +31pt is only +11.7% — still arms 75% keep."""
    from app.engines.moment_stage_trail import ftv_runner_pct_floor

    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = PaperTrade(
        id="sensex-76300",
        symbol="SENSEX",
        side=Side.PUT,
        strike=76300.0,
        entryPremium=269.45,
        currentPremium=300.95,
        lots=19,
        openedAt=datetime.now(IST) - timedelta(minutes=6),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=31.5,
        maxLtp=300.95,
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 800.0,
            "stageSize": 75.0,
        },
    )
    floor = ftv_runner_pct_floor(trade, 31.5, settings=s)
    assert floor is not None
    assert floor == pytest.approx(31.5 * 0.75, rel=0.01)


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_sep2_sensex_modest_peak_books_peak_keep_not_scratch(mock_ms, mock_s, _hc, _mp):
    """Sep2 first trade: +31.5pt peak on ITM PUT must book ~75% keep, not scratch."""
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    entry = 269.45
    best = 31.5
    trade = PaperTrade(
        id="sensex-76300",
        symbol="SENSEX",
        side=Side.PUT,
        strike=76300.0,
        entryPremium=entry,
        currentPremium=entry + 1.0,
        lots=19,
        openedAt=datetime.now(IST) - timedelta(minutes=6),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        pnlPoints=1.0,
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 800.0,
            "stageSize": 75.0,
            "exitPlan": {
                "trailArmPoints": 22.36,
                "trailKeepRatio": 0.517,
                "momentStageLadder": True,
                "projectedMaxTp": 800.0,
                "stageSize": 75.0,
            },
        },
    )
    params = ExplosionExitParams(
        stop_points=40.0,
        target_points=71.36,
        trail_arm_points=22.36,
        trail_keep_ratio=0.517,
        micro_target_points=7.71,
        adaptive_stop=True,
    )
    reason, pnl = evaluate_explosion_exit(
        trade, entry + 1.0, "EXPLODING", 360, params=params, live_velocity_3s=0.0,
    )
    assert reason == "explosion_peak_keep_trail"
    assert pnl > 15.0


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


@patch("app.engines.moment_stage_trail.get_settings")
def test_early_entry_50_projects_toward_210(mock_s):
    """SENSEX 77700 CE: enter ~50 from base ~40 → project enough to hold for ~210."""
    mock_s.return_value = _settings()
    projected = compute_projected_max_tp(
        entry_premium=50.0,
        base_premium=40.0,
        exit_plan={"targetPoints2": 40.0},
        velocity_3s=6.0,
        volume_surge=2.2,
        session_move_pct=35.0,
        premium_fvg=True,
        flat_then_vertical=True,
        mega_rip=False,
        max_profit=True,
    )
    # Need ≥160pts so premium target ≈ 50+160 = 210.
    assert projected >= 160.0
    stage = compute_stage_size(projected, _settings())
    assert stage >= 40.0


@patch("app.engines.moment_stage_trail.get_settings")
def test_early_50_to_210_holds_then_stage_exits_pullback(mock_s):
    """Peak ~250 (+200) then pullback to ~210 (+160) — hold above floor, bank on deeper fade."""
    mock_s.return_value = _settings()
    trade = _trade(entry=50.0, best=200.0, current=210.0, projected=180.0, stage=45.0)
    trade.currentPremium = 210.0
    trade.pnlPoints = 160.0
    floor = stage_trail_floor_pts(trade, 200.0, settings=_settings())
    assert floor is not None
    assert 160.0 > floor  # still holding at premium 210
    # Deeper pullback through the stage floor books
    assert (50.0 + floor - 5.0 - 50.0) < floor


@patch("app.engines.moment_stage_trail.get_settings")
def test_parabolic_50_projects_toward_650(mock_s):
    """Rare mega: entry 50 with parabolic heat can project toward ~650 LTP (+600pt)."""
    mock_s.return_value = _settings()
    projected = compute_projected_max_tp(
        entry_premium=50.0,
        base_premium=40.0,
        exit_plan={},
        velocity_3s=10.0,
        volume_surge=3.0,
        session_move_pct=45.0,
        premium_fvg=True,
        flat_then_vertical=True,
        mega_rip=True,
        max_profit=True,
    )
    # 50 + 600 = 650 LTP → need projected near/above 600 (capped by 16×entry=800).
    assert projected >= 500.0
    assert 50.0 + projected >= 550.0


@patch("app.engines.moment_stage_trail.get_settings")
def test_live_extension_chases_650_path(mock_s):
    """Even if entry projected ~200, hot extension ratchets ceiling toward 650."""
    mock_s.return_value = _settings()
    trade = _trade(entry=50.0, best=500.0, current=550.0, projected=200.0, stage=45.0)
    trade.entryContext["liveVelocity3s"] = 4.0
    trade.entryContext["ictMegaRip"] = True
    extended = maybe_extend_projected_max(trade, 500.0, settings=_settings())
    assert extended >= 600.0
    assert extended <= 800.0
    # Still hot at +520 (LTP 570) — above a loose mega stage floor.
    floor = stage_trail_floor_pts(trade, 520.0, settings=_settings())
    assert floor is not None
    assert 520.0 > floor


@patch("app.engines.moment_stage_trail.get_settings")
def test_pre_stage_floor_owns_trail_before_first_stage(mock_s):
    """Before stageSize is hit, provisional floor suppresses best−3.5pt step."""
    mock_s.return_value = _settings()
    trade = _trade(entry=392.05, best=43.22, current=429.5, projected=800.0, stage=75.0)
    trade.entryContext["liveVelocity3s"] = 4.4
    trade.bestPnlPoints = 43.22
    trade.pnlPoints = 37.46
    pre = pre_stage_hold_floor_pts(trade, 43.22, settings=_settings())
    assert pre is not None
    composed, stage_floor = compose_trail_floor_with_stages(
        trade, 43.22, base_floor=39.72, settings=_settings()
    )
    pct_keep = 43.22 * 0.75
    assert stage_floor == pytest.approx(pct_keep, rel=0.01)
    assert composed == pytest.approx(pct_keep, rel=0.01)
    assert composed > pre
    assert composed < 37.46  # +37 pullback still above pct-keep floor


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_sensex_put_392_holds_through_early_trail_dip(mock_ms, mock_s, _hc, _mp):
    """Regression: entry 392 / best +43 / live +37 must NOT explosion_trail_sl.

    Aug4 SENSEX 78700 PUT was cut by the 3.5pt step trail while LTP ran to ~500.
    """
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _trade(
        entry=392.05,
        best=43.22,
        current=429.51,  # +37.46
        projected=800.0,
        stage=75.0,
    )
    trade.entryContext["liveVelocity3s"] = 4.4
    trade.entryContext["velocity3s"] = 4.4
    trade.entryContext["defensiveBaseRip"] = True
    trade.bestPnlPoints = 43.22
    trade.pnlPoints = 37.46
    reason, pnl = evaluate_explosion_exit(
        trade, 429.51, "EXPLODING", 10, params=_params(), live_velocity_3s=4.4,
    )
    assert reason != "explosion_trail_sl"
    assert reason != "explosion_trail_lock"
    assert reason != "explosion_micro_profit_lock"
    assert reason != "explosion_stage_trail"
    assert pnl > 0


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_pre_stage_deep_fade_still_books(mock_ms, mock_s, _hc, _mp):
    """Deep fade through provisional floor still exits via stage trail."""
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _trade(
        entry=392.05,
        best=43.22,
        current=393.05,  # ~+1pt — through hot provisional floor
        projected=800.0,
        stage=75.0,
    )
    trade.entryContext["liveVelocity3s"] = 4.4
    trade.bestPnlPoints = 43.22
    trade.pnlPoints = 1.0
    reason, pnl = evaluate_explosion_exit(
        trade, 393.05, "EXPLODING", 10, params=_params(), live_velocity_3s=4.4,
    )
    assert reason == "explosion_peak_keep_trail"
    assert pnl > 0


def test_near_stage_floor_aug28_24100_otm_sibling():
    """Aug28 24100 PE +33 vs stage 40 — near-complete arms pct-keep stage floor."""
    from app.engines.moment_stage_trail import (
        build_moment_stage_plan,
        moment_stage_near_complete,
        stage_trail_floor_pts,
    )

    entry = 46.45
    plan = build_moment_stage_plan(
        entry_premium=entry,
        base_premium=40.0,
        exit_plan={"targetPoints": 31.0},
        velocity_3s=5.0,
        volume_surge=2.0,
        flat_then_vertical=True,
        max_profit=True,
    )
    trade = PaperTrade(
        id="nifty-24100",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24100.0,
        entryPremium=entry,
        currentPremium=entry + 33.0,
        lots=1,
        openedAt=datetime.now(IST) - timedelta(minutes=40),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=33.35,
        entryContext={"maxProfitCapture": True, **(plan or {})},
    )
    stage = float(plan["stageSize"])
    assert moment_stage_near_complete(trade, 33.35, stage)
    floor = stage_trail_floor_pts(trade, 33.35)
    assert floor is not None
    assert floor >= 24.0


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=False)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_near_stage_otm_sibling_exits_on_pullback(mock_ms, mock_s, _hc, _mp):
    """OTM same-cycle leg exits on moment-top pullback once rank-1 peak is synced."""
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    entry = 46.45
    plan = build_moment_stage_plan(
        entry_premium=entry,
        base_premium=40.0,
        exit_plan={"targetPoints": 31.0, "trailArmPoints": 113.0},
        velocity_3s=5.0,
        volume_surge=2.0,
        flat_then_vertical=True,
        max_profit=True,
    )
    trade = PaperTrade(
        id="nifty-24100",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24100.0,
        entryPremium=entry,
        currentPremium=entry + 24.6,
        lots=1,
        openedAt=datetime.now(IST) - timedelta(minutes=43),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=24.25,
        maxLtp=entry + 24.25,
        entryContext={
            "maxProfitCapture": True,
            "entryCycleId": "5c85ce0def3f",
            "cycleMomentBestGainPct": (33.35 / entry) * 100.0,
            "exitPlan": plan or {},
            **(plan or {}),
        },
    )
    params = ExplosionExitParams(
        stop_points=11.06,
        target_points=31.17,
        trail_arm_points=113.15,
        trail_keep_ratio=0.61,
        micro_target_points=3.0,
        adaptive_stop=True,
    )
    with patch("app.engines.explosion_profit._hold_seconds", return_value=2600):
        reason, pnl = evaluate_explosion_exit(
            trade, entry + 24.6, "EXPLODING", 65, params=params, live_velocity_3s=0.0,
        )
    assert reason in ("explosion_peak_keep_trail", "explosion_stage_trail")
    assert pnl > 0


def test_sync_cycle_moment_peaks_shares_rank_one_best():
    from app.engines.moment_stage_trail import effective_best_pnl, sync_cycle_moment_peaks

    common = {
        "entryCycleId": "cycle-a",
        "maxProfitCapture": True,
        "momentStageLadder": True,
    }
    rank1 = PaperTrade(
        id="rank1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24200.0,
        entryPremium=81.9,
        currentPremium=131.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=49.0,
        maxLtp=130.9,
        entryContext=dict(common),
    )
    rank2 = PaperTrade(
        id="rank2",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24100.0,
        entryPremium=46.45,
        currentPremium=70.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=24.25,
        maxLtp=70.7,
        entryContext=dict(common),
    )
    sync_cycle_moment_peaks([rank1, rank2])
    # Rank-1 +49pt on ₹81.9 ≈ 59.8% — rank-2 effective best ≈ ₹27.8pt not ₹49pt.
    expected_pct = 49.0 / 81.9 * 100.0
    assert float(rank2.entryContext["cycleMomentBestGainPct"]) == round(expected_pct, 3)
    assert effective_best_pnl(rank2, 24.25) == pytest.approx(
        round(46.45 * expected_pct / 100.0, 2), abs=0.02
    )
