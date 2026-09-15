"""SL-only loss exits — no chop/live/failed-launch scratch on best-trade entries."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.chop_live_guards import chop_live_early_fail_exit_reason
from app.engines.explosion_profit import (
    _apply_elite_respected_early_exit,
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
