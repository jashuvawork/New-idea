"""SL-only loss exits — no chop/live/failed-launch scratch on best-trade entries."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.chop_live_guards import chop_live_early_fail_exit_reason
from app.engines.explosion_profit import (
    _apply_elite_respected_early_exit,
    _defer_adaptive_stop,
    _executed_entry_min_hold_before_loss,
    _is_chop_second_tier_trade,
    _should_skip_elite_runner_early_exits,
    evaluate_explosion_exit,
    sl_only_loss_exits_enabled,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _chop_elite_trade(**ctx_overrides):
    ctx = {
        "chopLiveGuard": True,
        "eliteAssessment": {"eliteScore": 95.5, "grade": "A", "setup": "V"},
        "fakeExplosionTrap": True,
        "conflictFlags": ["chop_regime", "elite_hot"],
    }
    ctx.update(ctx_overrides)
    return PaperTrade(
        id="sep15",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23500.0,
        entryPremium=242.42,
        currentPremium=238.15,
        lots=11,
        openedAt=datetime(2026, 9, 15, 13, 42, 21, tzinfo=IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext=ctx,
    )


def test_sl_only_default_enabled():
    s = Settings()
    assert sl_only_loss_exits_enabled(s) is True
    assert s.chop_live_early_fail_exit_enabled is False
    assert s.live_early_fail_exit_enabled is False


def test_sl_only_blocks_scratch_exit_reasons():
    trade = _chop_elite_trade()
    s = Settings()
    assert s.executed_entry_sl_only_loss_exits is True
    for reason in ("chop_live_early_fail", "live_early_fail", "explosion_failed_launch"):
        assert _apply_elite_respected_early_exit(trade, reason, settings=s) is None


@patch("app.engines.chop_live_guards.get_settings")
def test_chop_early_fail_direct_still_works_when_explicitly_enabled(mock_get_settings):
    s = Settings()
    s.executed_entry_sl_only_loss_exits = False
    s.chop_live_early_fail_exit_enabled = True
    mock_get_settings.return_value = s
    trade = _chop_elite_trade(eliteAssessment={})
    reason = chop_live_early_fail_exit_reason(
        trade,
        hold_seconds=77,
        best_points=0.0,
        pnl_points=-4.3,
        live_velocity_3s=-0.5,
    )
    assert reason == "chop_live_early_fail"


def _sep21_chop_put_trade(**ctx_overrides):
    ctx = {
        "chopLiveGuard": True,
        "explosionTier": "EXPLODING",
        "eliteAssessment": {
            "eliteScore": 92.9,
            "grade": "A",
            "setup": "V",
            "mustTake": False,
        },
        "exitPlan": {"stopPoints": 11.9, "adaptiveStop": True},
    }
    ctx.update(ctx_overrides)
    return PaperTrade(
        id="sep21-23350-pe",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23350.0,
        entryPremium=62.10,
        currentPremium=52.0,
        lots=44,
        openedAt=datetime(2026, 9, 21, 10, 30, 0, tzinfo=IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext=ctx,
        bestPnlPoints=3.9,
    )


def test_sep21_chop_second_tier_not_elite_runner():
    s = Settings()
    trade = _sep21_chop_put_trade()
    assert _is_chop_second_tier_trade(trade, settings=s) is True
    assert _should_skip_elite_runner_early_exits(trade, settings=s) is False
    assert _executed_entry_min_hold_before_loss(trade, settings=s) == 120


def test_sep21_chop_second_tier_exits_near_structural_sl():
    s = Settings()
    trade = _sep21_chop_put_trade()
    with patch("app.engines.explosion_profit._hold_seconds", return_value=180):
        with patch("app.engines.explosion_profit.get_settings", return_value=s):
            reason, pnl = evaluate_explosion_exit(
                trade,
                51.90,
                "EXPLODING",
                lot_multiplier=65,
                live_velocity_3s=-0.2,
            )
    assert reason == "chop_second_tier_stop_loss"
    assert pnl < 0


def test_sep15_elite_requires_min_hold_before_loss():
    s = Settings()
    trade = _chop_elite_trade(
        eliteAssessment={"eliteScore": 95.5, "grade": "A", "setup": "V"},
        explosionTier="ELITE",
        alert={"fastVerticalBurst": True},
    )
    assert _executed_entry_min_hold_before_loss(trade, settings=s) == 600
    assert _defer_adaptive_stop(
        trade,
        best=0.0,
        hold=77,
        settings=s,
        pnl_pts=-4.3,
        stop_floor=24.0,
    ) is True
    assert _defer_adaptive_stop(
        trade,
        best=0.0,
        hold=650,
        settings=s,
        pnl_pts=-30.0,
        stop_floor=24.0,
    ) is False
