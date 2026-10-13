"""Hard stops that ignore min-hold (Oct 13 NIFTY 22300 PE: ₹68.25 → ₹15, stop ₹56)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_profit import evaluate_explosion_exit, hard_loss_stop_reason
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")
SIDES = [Side.CALL, Side.PUT]


def _settings(**overrides) -> Settings:
    base = {
        "october_frozen_profile_enabled": True,
        "live_paper_parity_enabled": True,
        "live_best_trades_only_enabled": False,
        "worst_day_blocks_live": False,
        "executed_entry_sl_only_loss_exits": True,
        "never_green_hard_stop_enabled": True,
        "catastrophic_loss_stop_pct": 30.0,
    }
    base.update(overrides)
    return Settings(**base)


@contextmanager
def _use(s: Settings):
    with patch("app.config.get_settings", lambda: s), patch(
        "app.engines.explosion_profit.get_settings", lambda: s
    ), patch("app.engines.moment_stage_trail.get_settings", lambda: s):
        yield


def _oct13(side: Side, *, seconds: int, best: float = 0.15, current: float = 55.0) -> PaperTrade:
    entry = 68.25
    return PaperTrade(
        id=f"d85ca3fa-{side.value}",
        symbol="NIFTY",
        side=side,
        strike=22300.0,
        entryPremium=entry,
        currentPremium=current,
        lots=11,
        openedAt=datetime.now(IST) - timedelta(seconds=seconds),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        entryContext={
            "explosionTier": "ELITE",
            "vBaseFtvRunner": True,
            "momentStageLadder": True,
            "fastBullishLocalBase": True,
            "exitPlan": {
                "stopPoints": 12.29,
                "naturalStopPoints": 11.76,
                "adaptiveStop": True,
                "trailArmPoints": 12.83,
                "targetPoints": 34.45,
            },
        },
    )


@pytest.mark.parametrize("side", SIDES)
def test_oct13_legacy_min_hold_kept_never_green_leg_open_ce_pe(side):
    """Reproduces the miss: flag off, 60s in, ₹13 through the stop → no exit."""
    s = _settings(never_green_hard_stop_enabled=False, catastrophic_loss_stop_pct=0.0)
    trade = _oct13(side, seconds=60, current=55.0)
    with _use(s):
        reason, _ = evaluate_explosion_exit(trade, 55.0, "ELITE", 65, live_velocity_3s=-4.0)
    assert reason is None


@pytest.mark.parametrize("side", SIDES)
def test_oct13_never_green_hard_stop_fires_through_min_hold_ce_pe(side):
    s = _settings()
    trade = _oct13(side, seconds=40, current=55.9)
    with _use(s):
        reason, pnl_inr = evaluate_explosion_exit(trade, 55.9, "ELITE", 65, live_velocity_3s=-4.0)
    assert reason == "explosion_never_green_hard_stop"
    assert pnl_inr == pytest.approx((55.9 - 68.25) * 11 * 65, rel=0.01)
    assert pnl_inr > -9_000


@pytest.mark.parametrize("side", SIDES)
def test_inside_stop_still_holds_ce_pe(side):
    s = _settings()
    trade = _oct13(side, seconds=40, current=60.0)
    with _use(s):
        reason, _ = evaluate_explosion_exit(trade, 60.0, "ELITE", 65, live_velocity_3s=-1.0)
    assert reason is None


@pytest.mark.parametrize("side", SIDES)
def test_first_seconds_noise_not_cut_ce_pe(side):
    s = _settings()
    trade = _oct13(side, seconds=2, current=55.0)
    reason = hard_loss_stop_reason(
        trade, best=0.15, pnl_pts=-13.25, hold_seconds=2, stop_points=12.29, settings=s,
    )
    assert reason is None


@pytest.mark.parametrize("side", SIDES)
def test_green_leg_left_to_normal_stops_ce_pe(side):
    """A leg that printed real green (+8pt) is not a never-green failure."""
    s = _settings()
    trade = _oct13(side, seconds=60, best=8.0, current=55.0)
    reason = hard_loss_stop_reason(
        trade, best=8.0, pnl_pts=-13.25, hold_seconds=60, stop_points=12.29, settings=s,
    )
    assert reason is None


@pytest.mark.parametrize("side", SIDES)
def test_catastrophic_stop_cuts_any_leg_ce_pe(side):
    s = _settings()
    trade = _oct13(side, seconds=60, best=8.0, current=45.0)
    with _use(s):
        reason, _ = evaluate_explosion_exit(trade, 45.0, "ELITE", 65, live_velocity_3s=-4.0)
    assert reason == "explosion_catastrophic_loss_stop"


@pytest.mark.parametrize("side", SIDES)
def test_defaults_off_ce_pe(side):
    s = Settings()
    assert s.never_green_hard_stop_enabled is False
    assert s.catastrophic_loss_stop_pct == 0.0
    trade = _oct13(side, seconds=60, current=45.0)
    assert hard_loss_stop_reason(
        trade, best=0.15, pnl_pts=-23.25, hold_seconds=60, stop_points=12.29, settings=s,
    ) is None
