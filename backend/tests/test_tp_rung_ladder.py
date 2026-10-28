"""TP rung ladder — multi-level TP with between-rung fade exits."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.tp_rung_ladder import (
    build_tp_rung_points,
    sync_tp_rung_state,
    tp_rung_exit_reason,
    tp_rung_mega_leg,
    trade_uses_tp_rung_ladder,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def test_build_tp_rungs_includes_micro_and_stages():
    s = Settings()
    rungs = build_tp_rung_points(
        projected_max_tp=200.0,
        stage_size=40.0,
        exit_plan={"microTargetPoints": 12.0, "targetPoints": 28.0},
        settings=s,
    )
    assert 12.0 in rungs
    assert 28.0 in rungs
    assert 40.0 in rungs
    assert 80.0 in rungs


def test_near_best_hold_defers_between_fade_on_small_pullback():
    """While LTP hugs the peak, do not bank on a 2pt dip with mild negative v3."""
    s = Settings()
    trade = PaperTrade(
        id="near-best",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24000.0,
        entryPremium=100.0,
        currentPremium=138.0,
        lots=1,
        openedAt=datetime.now(IST) - timedelta(minutes=5),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=40.0,
        maxLtp=140.0,
        maxLtpAt=datetime.now(IST) - timedelta(seconds=30),
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "eliteRunnerExitBundle": True,
            "projectedMaxTp": 500.0,
            "stageSize": 36.0,
            "tpRungLadder": True,
            "tpRungsPts": [28.0, 36.0, 72.0, 120.0],
            "exitPlan": {"targetPoints": 28.0, "stageSize": 36.0, "projectedMaxTp": 500.0},
        },
    )
    sync_tp_rung_state(trade, 40.0, settings=s)
    reason = tp_rung_exit_reason(
        trade,
        best=40.0,
        pnl_pts=38.0,
        hold_seconds=120.0,
        live_velocity_3s=-0.5,
        settings=s,
    )
    assert reason is None


def test_user_example_100_entry_28_36_fade_at_33():
    """Entry 100: rungs +28/+36, best +33 fading → exit between rungs."""
    s = Settings()
    trade = PaperTrade(
        id="ex",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24000.0,
        entryPremium=100.0,
        currentPremium=120.0,
        lots=1,
        openedAt=datetime.now(IST) - timedelta(minutes=5),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=33.0,
        maxLtp=133.0,
        maxLtpAt=datetime.now(IST) - timedelta(seconds=90),
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 500.0,
            "stageSize": 36.0,
            "tpRungLadder": True,
            "tpRungsPts": [28.0, 36.0, 72.0, 120.0],
            "exitPlan": {"targetPoints": 28.0, "stageSize": 36.0, "projectedMaxTp": 500.0},
        },
    )
    sync_tp_rung_state(trade, 33.0, settings=s)
    reason = tp_rung_exit_reason(
        trade,
        best=33.0,
        pnl_pts=20.0,
        hold_seconds=120.0,
        live_velocity_3s=-1.0,
        settings=s,
    )
    assert reason == "explosion_tp_rung_between_fade"


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
def test_oct21_73400_between_rung_fade(_mp):
    import app.engines.explosion_profit as ep

    s = Settings()
    entry = 340.33
    trade = PaperTrade(
        id="73400",
        symbol="SENSEX",
        side=Side.PUT,
        strike=73400.0,
        entryPremium=entry,
        currentPremium=entry + 31.0,
        lots=26,
        openedAt=datetime.now(IST) - timedelta(minutes=8),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=47.67,
        maxLtp=entry + 47.67,
        maxLtpAt=datetime.now(IST) - timedelta(seconds=90),
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 800.0,
            "stageSize": 75.0,
            "tpRungLadder": True,
            "tpRungsPts": [28.0, 36.0, 75.0, 150.0, 225.0, 300.0, 375.0, 450.0, 525.0, 600.0, 675.0, 750.0, 800.0],
            "exitPlan": {"projectedMaxTp": 800.0, "stageSize": 75.0, "microTargetPoints": 27.0},
        },
    )
    assert trade_uses_tp_rung_ladder(trade, settings=s)
    with patch.object(ep, "_hold_seconds", return_value=400):
        reason, pnl_inr = evaluate_explosion_exit(
            trade, trade.currentPremium, "EXPLODING", 20, live_velocity_3s=-2.0,
        )
    assert reason in ("explosion_tp_rung_between_fade", "explosion_tp_rung_floor")
    assert pnl_inr > 0


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
def test_oct21_73400_red_after_mega_peak(_mp):
    import app.engines.explosion_profit as ep

    s = Settings()
    entry = 340.33
    trade = PaperTrade(
        id="73400-red",
        symbol="SENSEX",
        side=Side.PUT,
        strike=73400.0,
        entryPremium=entry,
        currentPremium=entry - 18.0,
        lots=26,
        openedAt=datetime.now(IST) - timedelta(minutes=8),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=47.67,
        maxLtp=entry + 47.67,
        maxLtpAt=datetime.now(IST) - timedelta(seconds=120),
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 800.0,
            "stageSize": 75.0,
            "tpRungLadder": True,
            "tpRungsPts": [28.0, 75.0, 150.0],
            "exitPlan": {"projectedMaxTp": 800.0, "stageSize": 75.0},
        },
    )
    with patch.object(ep, "_hold_seconds", return_value=400):
        reason, _ = evaluate_explosion_exit(
            trade, trade.currentPremium, "EXPLODING", 20, live_velocity_3s=-1.0,
        )
    assert reason == "explosion_tp_rung_red_giveback"


def test_mega_leg_skips_between_fade_when_best_above_55():
    """Oct 22 73200 PE shape: mega peak — no early between-rung fade."""
    s = Settings()
    entry = 198.17
    trade = PaperTrade(
        id="73200",
        symbol="SENSEX",
        side=Side.PUT,
        strike=73200.0,
        entryPremium=entry,
        currentPremium=entry + 50.0,
        lots=22,
        openedAt=datetime.now(IST) - timedelta(minutes=7),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=76.23,
        maxLtp=entry + 76.23,
        maxLtpAt=datetime.now(IST) - timedelta(seconds=120),
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 500.0,
            "stageSize": 75.0,
            "tpRungLadder": True,
            "tpRungsPts": [28.0, 36.0, 75.0, 150.0, 225.0, 300.0, 375.0, 450.0, 500.0],
            "exitPlan": {"projectedMaxTp": 500.0, "stageSize": 75.0},
        },
    )
    assert tp_rung_mega_leg(trade, settings=s)
    sync_tp_rung_state(trade, 76.23, settings=s)
    reason = tp_rung_exit_reason(
        trade,
        best=76.23,
        pnl_pts=50.0,
        hold_seconds=400.0,
        live_velocity_3s=-1.5,
        settings=s,
    )
    assert reason != "explosion_tp_rung_between_fade"


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
def test_mega_73200_prefers_unified_ladder_over_early_rung_fade(_mp):
    import app.engines.explosion_profit as ep

    s = Settings()
    entry = 198.17
    trade = PaperTrade(
        id="73200-exit",
        symbol="SENSEX",
        side=Side.PUT,
        strike=73200.0,
        entryPremium=entry,
        currentPremium=entry + 54.0,
        lots=22,
        openedAt=datetime.now(IST) - timedelta(minutes=7),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=76.23,
        maxLtp=entry + 76.23,
        maxLtpAt=datetime.now(IST) - timedelta(seconds=120),
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 500.0,
            "stageSize": 75.0,
            "tpRungLadder": True,
            "tpRungsPts": [28.0, 75.0, 150.0, 225.0, 500.0],
            "exitPlan": {"projectedMaxTp": 500.0, "stageSize": 75.0},
        },
    )
    with patch.object(ep, "_hold_seconds", return_value=400):
        reason, pnl_inr = evaluate_explosion_exit(
            trade, trade.currentPremium, "ELITE", 20, live_velocity_3s=-2.0,
        )
    assert reason != "explosion_tp_rung_between_fade"
    assert pnl_inr > 0
    assert reason in (
        "explosion_profit_ladder_peak_keep",
        "explosion_tp_rung_floor",
        "explosion_tp_rung_floor_hole",
        "explosion_stage_runner_hole_take",
    )


def test_sub_28_best_does_not_arm_tp_rung_exit():
    """22700-shaped early peak: defer sub-28 best — TP rung owner stays quiet."""
    s = Settings()
    trade = PaperTrade(
        id="22700",
        symbol="NIFTY",
        side=Side.PUT,
        strike=22700.0,
        entryPremium=140.02,
        currentPremium=150.38,
        lots=19,
        openedAt=datetime.now(IST) - timedelta(minutes=9),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=21.48,
        maxLtp=161.5,
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 703.8,
            "stageSize": 75.0,
            "tpRungLadder": True,
            "tpRungsPts": [12.0, 28.0, 75.0],
        },
    )
    assert trade_uses_tp_rung_ladder(trade, settings=s)
    reason = tp_rung_exit_reason(
        trade,
        best=21.48,
        pnl_pts=10.36,
        hold_seconds=540.0,
        live_velocity_3s=-0.5,
        settings=s,
    )
    assert reason is None
