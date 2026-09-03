"""Tests for modest peak mode — Sep03 NIFTY chop pop exit + entry classifier."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.edge_engine import EdgeScore
from app.engines.explosion_profit import ExplosionExitParams, evaluate_explosion_exit
from app.engines.modest_peak_mode import (
    apply_modest_peak_entry_stamp,
    classify_modest_peak_entry,
    cap_modest_peak_stage_plan,
)
from app.engines.moment_stage_trail import ftv_runner_pct_floor, pre_stage_hold_floor_pts
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides) -> Settings:
    base = Settings()
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _sep03_edge() -> EdgeScore:
    return EdgeScore(
        total=83.6,
        timing=25.0,
        momentum=4.0,
        chart=34.3,
        ml=10.0,
        session=10.3,
        lot_scale=0.91,
        reasons=[
            "afternoon_capture_window",
            "midday_chop",
            "breadth_aligned",
            "insufficient_session_trades",
        ],
    )


def _sep03_trade(*, pnl_pts: float, current_premium: float | None = None) -> PaperTrade:
    entry = 79.65
    best = 16.4
    current = current_premium if current_premium is not None else entry + pnl_pts
    return PaperTrade(
        id="37905074",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23900.0,
        entryPremium=entry,
        currentPremium=current,
        lots=34,
        openedAt=datetime.now(IST) - timedelta(minutes=70),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        pnlPoints=pnl_pts,
        entryContext={
            "maxProfitCapture": True,
            "modestPeakMode": True,
            "modestPeakReason": "afternoon_chop_capture",
            "momentStageLadder": True,
            "projectedMaxTp": 60.0,
            "stageSize": 30.0,
            "exitPlan": {
                "momentStageLadder": True,
                "modestPeakMode": True,
                "projectedMaxTp": 60.0,
                "stageSize": 30.0,
                "trailArmPoints": 7.84,
                "trailKeepRatio": 0.578,
                "exitBias": "PROTECT",
            },
        },
    )


def test_classify_modest_peak_sep03_afternoon_chop():
    use, reason = classify_modest_peak_entry(
        edge=_sep03_edge(),
        tier="ELITE",
        afternoon_capture=True,
        ict_flat_vertical=False,
        mega_rip=False,
        first_lift_runner=False,
        velocity_3s=1.2,
        lift_readiness_reason="building_coil_pad",
        max_profit_capture=True,
    )
    assert use is True
    assert reason == "afternoon_chop_capture"


def test_classify_skips_mega_rip():
    use, _ = classify_modest_peak_entry(
        edge=_sep03_edge(),
        tier="ELITE",
        afternoon_capture=True,
        ict_flat_vertical=False,
        mega_rip=True,
        first_lift_runner=False,
        velocity_3s=1.2,
        lift_readiness_reason="building_coil_pad",
        max_profit_capture=True,
    )
    assert use is False


def test_cap_modest_peak_stage_plan():
    s = _settings()
    capped = cap_modest_peak_stage_plan(
        {"projectedMaxTp": 307.6, "stageSize": 45.0},
        79.65,
        settings=s,
    )
    assert capped["projectedMaxTp"] <= 60.0
    assert capped["stageSize"] <= 30.0


def test_apply_modest_peak_entry_stamp_tightens_let_runners():
    ctx: dict = {
        "maxProfitCapture": True,
        "projectedMaxTp": 307.6,
        "stageSize": 45.0,
        "exitPlan": {"exitBias": "LET_RUNNERS", "reasoning": []},
    }
    ok = apply_modest_peak_entry_stamp(
        ctx,
        edge=_sep03_edge(),
        tier="ELITE",
        afternoon_capture=True,
        ict_flat_vertical=False,
        mega_rip=False,
        first_lift_runner=False,
        velocity_3s=1.0,
        lift_readiness_reason="building_coil_pad",
        entry_premium=79.65,
    )
    assert ok is True
    assert ctx["modestPeakMode"] is True
    assert ctx["exitPlan"]["exitBias"] == "PROTECT"
    assert ctx["projectedMaxTp"] <= 60.0


@patch("app.engines.moment_stage_trail.get_settings")
def test_ftv_pct_floor_arms_modest_peak_at_15pct(mock_s):
    s = _settings()
    mock_s.return_value = s
    trade = _sep03_trade(pnl_pts=10.0)
    floor = ftv_runner_pct_floor(trade, 16.4, settings=s)
    assert floor is not None
    assert floor == round(16.4 * 0.75, 2)


@patch("app.engines.moment_stage_trail.get_settings")
def test_pre_stage_suppressed_for_modest_peak(mock_s):
    s = _settings()
    mock_s.return_value = s
    trade = _sep03_trade(pnl_pts=10.0)
    floor = pre_stage_hold_floor_pts(trade, 16.4, settings=s)
    assert floor is None


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=False)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=False)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_sep03_modest_peak_exits_on_fade(mock_ms, mock_s, _hc, _mp):
    """Sep03 NIFTY: peak +16.4pt, fade to +4pt books via 75% peak-keep."""
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _sep03_trade(pnl_pts=4.23, current_premium=83.88)
    params = ExplosionExitParams(
        stop_points=14.34,
        target_points=27.77,
        trail_arm_points=7.84,
        trail_keep_ratio=0.578,
        micro_target_points=100.0,
        adaptive_stop=True,
    )
    reason, pnl = evaluate_explosion_exit(
        trade, 83.88, "ELITE", 4200, params=params, live_velocity_3s=0.0,
    )
    assert reason == "explosion_peak_keep_trail"
    assert pnl > 3.0

    # Still above 75% of peak — hold
    trade_hold = _sep03_trade(pnl_pts=13.0, current_premium=92.65)
    reason_hold, _ = evaluate_explosion_exit(
        trade_hold, 92.65, "ELITE", 4200, params=params, live_velocity_3s=0.0,
    )
    assert reason_hold is None


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=False)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=False)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_without_modest_peak_sep03_would_not_arm_pct_floor(mock_ms, mock_s, _hc, _mp):
    """Without modestPeakMode, +16.4pt / 20.6% gain fails both arm paths."""
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _sep03_trade(pnl_pts=4.23)
    trade.entryContext.pop("modestPeakMode", None)
    trade.entryContext["exitPlan"] = dict(trade.entryContext["exitPlan"])
    trade.entryContext["exitPlan"].pop("modestPeakMode", None)
    floor = ftv_runner_pct_floor(trade, 16.4, settings=s)
    assert floor is None
