"""Sep03 NIFTY 23850 PE — post-small-win FOMO cap + armed-base expiry + barely-green exits."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.explosion_entry_guards import (
    _trap_soft_cap_must_honor,
    cap_fake_explosion_trap_lots,
    trap_post_small_win_active,
)
from app.engines.explosion_profit import (
    _armed_base_thesis_expired,
    evaluate_explosion_exit,
    explosion_exit_params_from_plan,
)
from app.engines.modest_peak_mode import apply_modest_peak_entry_stamp
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    defaults = {
        "fake_explosion_trap_honor_post_win_cap": True,
        "fake_explosion_trap_honor_fomo_cap": True,
        "fake_explosion_trap_honor_soft_cap_on_chop": True,
        "index_confirmed_ftv_bypasses_fake_trap_lot_cap": True,
        "explosion_armed_base_expiry_exit_enabled": True,
        "explosion_armed_base_expiry_grace_seconds": 30.0,
        "explosion_armed_base_expiry_max_best_points": 8.0,
        "explosion_barely_green_stop_enabled": True,
        "explosion_barely_green_max_best_points": 3.0,
        "explosion_barely_green_min_loss_points": 1.5,
        "explosion_barely_green_min_hold_seconds": 180,
        "explosion_never_green_min_green_points": 0.5,
        "explosion_failed_launch_exit_enabled": False,
        "explosion_stop_min_hold_seconds": 0,
        "explosion_trail_arm_points": 8.0,
        "emergency_stop_enabled": False,
        "explosion_no_progress_enabled": False,
        "adaptive_exits_enabled": False,
        "runner_min_best_points": 20.0,
        "runner_micro_giveback_points": 3.0,
        "explosion_trail_keep_ratio": 0.5,
        "explosion_elite_max_hold_seconds": 1800,
        "ict_max_profit_max_hold_seconds": 1200,
        "explosion_thesis_hold_enabled": False,
        "modest_peak_mode_enabled": True,
    }
    for k, v in {**defaults, **overrides}.items():
        setattr(s, k, v)
    return s


def _trade(**ctx) -> PaperTrade:
    opened = datetime.now(IST) - timedelta(minutes=30)
    entry_ctx = {
        "exitPlan": {"stopPoints": 12.94, "trailArmPoints": 8.29},
        "armedBaseCapture": True,
        "ictArmedBaseLaunch": True,
        **ctx,
    }
    return PaperTrade(
        id="test",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850.0,
        entryPremium=71.9,
        currentPremium=65.0,
        lots=8,
        pnlInr=-500.0,
        pnlPoints=-2.0,
        openedAt=opened,
        status="OPEN",
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=1.6,
        maxLtp=73.5,
        entryContext=entry_ctx,
    )


def test_post_small_win_trap_cap_honored_despite_index_ftv_bypass():
    meta = {
        "fakeExplosionTrap": True,
        "action": "cut_size",
        "lotCap": 8,
        "postSmallWin": True,
        "psychologyEscalate": "FOMO",
        "conflictFlags": ["elite_hot", "post_small_win"],
        "indexConfirmedFtv": True,
        "localBaseStructure": True,
    }
    assert trap_post_small_win_active(meta) is True
    assert _trap_soft_cap_must_honor(meta) is True
    assert cap_fake_explosion_trap_lots(38, meta, bypass_soft_cap=True) == 8


def test_modest_peak_stamped_on_post_small_win_fomo():
    ctx = {
        "fakeExplosionTrap": True,
        "postSmallWin": True,
        "psychologyLabel": "FOMO",
        "conflictFlags": ["elite_hot", "post_small_win"],
        "maxProfitCapture": True,
        "projectedMaxTp": 290.8,
        "stageSize": 45.0,
        "exitPlan": {"exitBias": "LET_RUNNERS", "reasoning": []},
    }
    with patch("app.engines.modest_peak_mode.get_settings", return_value=_settings()):
        ok = apply_modest_peak_entry_stamp(
            ctx,
            edge=MagicMock(reasons=[]),
            tier="EXPLODING",
            afternoon_capture=True,
            ict_flat_vertical=True,
            mega_rip=False,
            first_lift_runner=False,
            velocity_3s=2.6,
            lift_readiness_reason="fast_bullish_local_base_ready",
            entry_premium=71.9,
            settings=_settings(),
        )
    assert ok is True
    assert ctx.get("modestPeakReason") == "post_small_win_fomo"
    assert ctx.get("modestPeakMode") is True
    assert float(ctx.get("projectedMaxTp") or 999) <= 60.0


@patch("app.engines.explosion_profit.get_settings")
def test_armed_base_expiry_exits_stale_thesis(mock_settings):
    mock_settings.return_value = _settings()
    expired = (datetime.now(IST) - timedelta(minutes=5)).isoformat()
    trade = _trade(armedBaseExpiresAt=expired)
    plan = explosion_exit_params_from_plan(
        MagicMock(
            stopPoints=12.94,
            targetPoints=26.0,
            trailArmPoints=8.29,
            trailKeepRatio=0.5,
            microTargetPoints=3.0,
        ),
        "EXPLODING",
    )
    reason, _ = evaluate_explosion_exit(
        trade,
        current_premium=65.0,
        event_tier="EXPLODING",
        lot_multiplier=65,
        params=plan,
    )
    assert reason == "explosion_armed_base_expired"


@patch("app.engines.explosion_profit.get_settings")
def test_barely_green_stop_cuts_sep03_shape(mock_settings):
    mock_settings.return_value = _settings()
    trade = _trade()
    trade.bestPnlPoints = 1.6
    trade.openedAt = datetime.now(IST) - timedelta(minutes=10)
    plan = explosion_exit_params_from_plan(
        MagicMock(
            stopPoints=12.94,
            targetPoints=26.0,
            trailArmPoints=8.29,
            trailKeepRatio=0.5,
            microTargetPoints=3.0,
        ),
        "EXPLODING",
    )
    reason, _ = evaluate_explosion_exit(
        trade,
        current_premium=68.0,
        event_tier="EXPLODING",
        lot_multiplier=65,
        params=plan,
    )
    assert reason == "explosion_barely_green_stop"


def test_armed_base_not_expired_before_ttl():
    future = (datetime.now(IST) + timedelta(minutes=10)).isoformat()
    trade = _trade(armedBaseExpiresAt=future)
    assert _armed_base_thesis_expired(trade, grace_seconds=30.0) is False
