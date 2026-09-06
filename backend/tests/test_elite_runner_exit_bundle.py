"""Tests for elite runner exit bundle — auto-stamp + failed_launch relax + modest-peak skip."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.elite_runner_exit_bundle import (
    apply_elite_runner_exit_bundle,
    clear_modest_peak_for_runner,
    elite_runner_failed_launch_relax,
    qualifies_elite_near_base_runner,
    refresh_runner_exit_plans,
)
from app.engines.explosion_profit import (
    _elite_failed_launch_runner,
    _failed_launch_thresholds,
    _should_skip_elite_runner_early_exits,
    _skip_explosion_time_stop_for_runner,
)
from app.engines.modest_peak_mode import apply_modest_peak_entry_stamp
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides) -> Settings:
    base = Settings()
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _assessment(**overrides) -> dict:
    base = {
        "eliteScore": 92.0,
        "grade": "A",
        "setup": "V",
        "localBasePct": 8.0,
        "timing": "GOOD",
    }
    base.update(overrides)
    return base


def test_qualifies_elite_near_base_v_setup():
    ok, reason = qualifies_elite_near_base_runner(
        {"localBaseBaseRelPct": 10.0},
        assessment=_assessment(),
    )
    assert ok is True
    assert "elite_assessment_v" in reason


def test_rejects_shallow_local_above_cap():
    ok, _ = qualifies_elite_near_base_runner(
        {"localBaseBaseRelPct": 22.0},
        assessment=_assessment(localBasePct=22.0),
    )
    assert ok is False


def test_apply_stamps_runner_flags():
    ctx: dict = {"localBaseBaseRelPct": 12.0}
    ok = apply_elite_runner_exit_bundle(
        ctx,
        assessment=_assessment(setup="FTV"),
        base_rel_pct=12.0,
        ict_flat_vertical=True,
    )
    assert ok is True
    assert ctx["maxProfitCapture"] is True
    assert ctx["vBaseFtvRunner"] is True
    assert ctx["eliteRunnerExitBundle"] is True


def test_clear_modest_peak_for_runner():
    ctx = {
        "vBaseFtvRunner": True,
        "modestPeakMode": True,
        "modestPeakReason": "midday_chop",
        "exitPlan": {"modestPeakMode": True, "exitBias": "PROTECT"},
    }
    clear_modest_peak_for_runner(ctx)
    assert "modestPeakMode" not in ctx
    assert "modestPeakMode" not in ctx["exitPlan"]


def test_refresh_runner_exit_plans_rebuilds_stage():
    ctx = {
        "eliteRunnerExitBundle": True,
        "modestPeakMode": True,
        "projectedMaxTp": 60.0,
        "stageSize": 30.0,
        "exitPlan": {"modestPeakMode": True, "targetPoints": 50.0},
        "ictFlatThenVertical": True,
    }
    refresh_runner_exit_plans(
        ctx,
        entry_premium=22.0,
        base_premium=20.0,
        flat_then_vertical=True,
        velocity_3s=5.0,
        volume_surge=2.0,
        settings=_settings(),
    )
    assert "modestPeakMode" not in ctx
    assert float(ctx.get("projectedMaxTp") or 0) > 60.0


def test_elite_runner_failed_launch_relax_with_first_lift():
    trade = PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        entryPremium=22.0,
        currentPremium=21.0,
        lots=10,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={
            "eliteRunnerExitBundle": True,
            "vBaseFtvRunner": True,
            "maxProfitCapture": True,
            "localBaseBaseRelPct": 10.0,
            "ictFirstLift": True,
            "velocity3s": 0.5,
        },
    )
    assert elite_runner_failed_launch_relax(trade) is True
    assert _elite_failed_launch_runner(trade) is True
    _, max_hold, max_best, _, _ = _failed_launch_thresholds(trade)
    assert max_hold >= 90
    assert max_best >= 3.0


def test_modest_peak_skipped_when_runner_stamped():
    ctx: dict = {
        "vBaseFtvRunner": True,
        "maxProfitCapture": True,
        "exitPlan": {"exitBias": "LET_RUNNERS", "reasoning": []},
    }
    from app.engines.edge_engine import EdgeScore

    edge = EdgeScore(
        total=85.0,
        timing=20.0,
        momentum=10.0,
        chart=30.0,
        ml=10.0,
        session=10.0,
        reasons=["midday_chop", "afternoon_capture_window"],
    )
    ok = apply_modest_peak_entry_stamp(
        ctx,
        edge=edge,
        tier="ELITE",
        afternoon_capture=True,
        ict_flat_vertical=False,
        mega_rip=False,
        first_lift_runner=False,
        velocity_3s=1.0,
        lift_readiness_reason="building_coil_pad",
        entry_premium=79.65,
    )
    assert ok is False
    assert "modestPeakMode" not in ctx


def test_skip_failed_launch_for_elite_assessment():
    trade = PaperTrade(
        id="t4",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        entryPremium=22.0,
        currentPremium=21.0,
        lots=10,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={
            "eliteAssessment": {"eliteScore": 92.0, "grade": "A", "setup": "V"},
            "localBaseBaseRelPct": 10.0,
        },
    )
    assert _should_skip_elite_runner_early_exits(trade) is True


def test_skip_failed_launch_for_bundle_runner():
    trade = PaperTrade(
        id="t2",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        entryPremium=22.0,
        currentPremium=21.0,
        lots=10,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={
            "eliteRunnerExitBundle": True,
            "vBaseFtvRunner": True,
            "maxProfitCapture": True,
            "localBaseBaseRelPct": 10.0,
            "ictFirstLift": True,
        },
    )
    assert _should_skip_elite_runner_early_exits(trade) is True


def test_skip_time_stop_for_slow_runner():
    trade = PaperTrade(
        id="t3",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        entryPremium=22.0,
        currentPremium=21.5,
        lots=10,
        openedAt=datetime.now(IST) - timedelta(minutes=5),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={
            "eliteRunnerExitBundle": True,
            "vBaseFtvRunner": True,
            "localBaseBaseRelPct": 8.0,
        },
    )
    assert _skip_explosion_time_stop_for_runner(trade, best=0.5, hold=300) is True
    assert _skip_explosion_time_stop_for_runner(trade, best=10.0, hold=300) is False
