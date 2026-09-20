"""CE at-base best trade — structural SL hold, no early scratch exits."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.best_trade_policy import stamp_call_at_base_exit_hold
from app.engines.explosion_profit import (
    _defer_adaptive_stop,
    _executed_entry_min_hold_before_loss,
    _should_skip_elite_runner_early_exits,
    _skip_explosion_time_profit,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _ce_base_trade(**ctx_overrides):
    ctx = {
        "callAtBaseBestTrade": True,
        "eliteRunnerExitBundle": True,
        "vBaseFtvRunner": True,
        "maxProfitCapture": True,
        "localBaseBaseRelPct": 12.0,
        "explosionTier": "ELITE",
        "eliteAssessment": {"eliteScore": 92.0, "grade": "A", "setup": "V"},
    }
    ctx.update(ctx_overrides)
    return PaperTrade(
        id="ce-base",
        symbol="NIFTY",
        side=Side.CALL,
        strike=23250.0,
        entryPremium=125.0,
        currentPremium=118.0,
        lots=10,
        openedAt=datetime(2026, 9, 17, 10, 15, 0, tzinfo=IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext=ctx,
    )


def test_stamp_call_at_base_exit_hold_builds_runner_bundle():
    ctx: dict = {"localBaseBaseRelPct": 10.0, "explosionTier": "ELITE"}
    ok = stamp_call_at_base_exit_hold(
        ctx,
        assessment={"eliteScore": 91.0, "grade": "A", "setup": "V", "localBasePct": 10.0},
        base_rel_pct=10.0,
        entry_premium=125.0,
        base_premium=110.0,
        tier="ELITE",
        first_lift=True,
        base_context_reason="call_premium_local_base_trough_turn",
    )
    assert ok is True
    assert ctx["callAtBaseBestTrade"] is True
    assert ctx["callPremiumLocalBase"] is True
    assert ctx["eliteRunnerExitBundle"] is True
    assert ctx["maxProfitCapture"] is True
    assert float(ctx.get("projectedMaxTp") or 0) > 0


def test_ce_base_min_hold_before_loss():
    s = Settings()
    trade = _ce_base_trade()
    assert _executed_entry_min_hold_before_loss(trade, settings=s) == 600


def test_ce_base_defers_adaptive_stop_during_min_hold():
    s = Settings()
    trade = _ce_base_trade()
    assert _defer_adaptive_stop(
        trade,
        best=0.0,
        hold=120,
        settings=s,
        pnl_pts=-8.0,
        stop_floor=18.0,
    ) is True
    assert _defer_adaptive_stop(
        trade,
        best=0.0,
        hold=650,
        settings=s,
        pnl_pts=-25.0,
        stop_floor=18.0,
    ) is False


def test_ce_base_skips_failed_launch_early_exits():
    trade = _ce_base_trade()
    assert _should_skip_elite_runner_early_exits(trade) is True


def test_ce_base_skips_time_profit_until_target():
    trade = _ce_base_trade(exitPlan={"entryTargetPoints": 40.0, "targetPoints": 40.0})
    assert _skip_explosion_time_profit(
        trade,
        best=5.0,
        target=40.0,
        event_tier="ELITE",
        settings=Settings(),
    ) is True
