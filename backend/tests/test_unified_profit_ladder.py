"""Unified profit ladder: 75% peak-keep and N×/k× in one ratcheting floor.

The 8% breakeven lock is off by default. Turning
``unified_profit_ladder_breakeven_enabled`` back on restores the entry+2% tier.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_profit import (
    evaluate_explosion_exit,
    unified_profit_ladder_exit_reason,
)
from app.engines.moment_stage_trail import profit_ladder_floor
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")
SIDES = [Side.CALL, Side.PUT]


def _settings(**overrides) -> Settings:
    base = {
        "unified_profit_ladder_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)


@contextmanager
def _use(s: Settings):
    with patch("app.config.get_settings", lambda: s), patch(
        "app.engines.explosion_profit.get_settings", lambda: s
    ), patch("app.engines.moment_stage_trail.get_settings", lambda: s):
        yield


def _trade(
    side: Side,
    entry: float,
    best: float,
    *,
    symbol: str = "NIFTY",
    strike: float = 22300.0,
    seconds: int = 17 * 60,
    ctx: dict | None = None,
) -> PaperTrade:
    return PaperTrade(
        id=f"ladder-{side.value}-{strike}",
        symbol=symbol,
        side=side,
        strike=strike,
        entryPremium=entry,
        currentPremium=entry + best,
        lots=11,
        openedAt=datetime.now(IST) - timedelta(seconds=seconds),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        entryContext=dict(ctx or {"explosionTier": "ELITE"}),
    )


def _oct12_runner(side: Side, **kw) -> PaperTrade:
    return _trade(
        side,
        58.5,
        10.2,
        ctx={
            "maxProfitCapture": True,
            "vBaseFtvRunner": True,
            "momentStageLadder": True,
            "projectedMaxTp": 258.1,
            "stageSize": 45.0,
            "explosionTier": "ELITE",
        },
        **kw,
    )


@pytest.mark.parametrize("side", SIDES)
def test_enabled_by_default_ce_pe(side):
    s = Settings()
    assert s.unified_profit_ladder_enabled is True
    assert s.unified_profit_ladder_breakeven_enabled is False
    assert s.unified_profit_ladder_min_hold_seconds == 180.0
    assert s.unified_profit_ladder_min_seconds_after_peak == 180.0
    floor, layer = profit_ladder_floor(_oct12_runner(side), 10.2, settings=s)
    assert layer == "peak_keep"
    assert floor == pytest.approx(7.65)


@pytest.mark.parametrize("side", SIDES)
def test_flag_off_leaves_exit_to_legacy_trail_ce_pe(side):
    s = _settings(unified_profit_ladder_enabled=False)
    assert profit_ladder_floor(_oct12_runner(side), 10.2, settings=s) is None


@pytest.mark.parametrize("side", SIDES)
def test_oct12_cheap_premium_books_peak_keep_ce_pe(side):
    """22300 PE @ ₹58.5 peaked +10.2pt (+17%) then rode back to +₹2k."""
    s = _settings()
    trade = _oct12_runner(side)
    with _use(s):
        hold, _ = evaluate_explosion_exit(trade, 66.5, "ELITE", 65, live_velocity_3s=-0.5)
        reason, pnl_inr = evaluate_explosion_exit(trade, 66.0, "ELITE", 65, live_velocity_3s=-0.5)
    assert hold is None
    assert reason == "explosion_profit_ladder_peak_keep"
    assert pnl_inr == pytest.approx(7.5 * 65 * 11, rel=0.01)
    assert trade.entryContext["profitLadder"]["floorPts"] == pytest.approx(7.65)


@pytest.mark.parametrize("side", SIDES)
def test_min_hold_blocks_early_peak_keep_ce_pe(side):
    s = _settings()
    trade = _oct12_runner(side, seconds=30)
    with _use(s):
        from app.engines.explosion_profit import unified_profit_ladder_exit_reason

        reason = unified_profit_ladder_exit_reason(
            trade, best=10.2, pnl_pts=7.0, hold_seconds=30, live_velocity_3s=-0.5,
        )
    assert reason is None


@pytest.mark.parametrize("side", SIDES)
def test_fresh_peak_holds_three_minutes_ce_pe(side):
    """A high that printed under 3 minutes ago is still a hold, CALL and PUT."""
    s = _settings()
    trade = _oct12_runner(side, seconds=17 * 60)
    trade.maxLtpAt = datetime.now(IST) - timedelta(seconds=40)
    with _use(s):
        early = unified_profit_ladder_exit_reason(
            trade, best=10.2, pnl_pts=7.0, hold_seconds=17 * 60, live_velocity_3s=-0.5,
        )
        trade.maxLtpAt = datetime.now(IST) - timedelta(seconds=200)
        aged = unified_profit_ladder_exit_reason(
            trade, best=10.2, pnl_pts=7.0, hold_seconds=17 * 60, live_velocity_3s=-0.5,
        )
    assert early is None
    assert aged == "explosion_profit_ladder_peak_keep"


@pytest.mark.parametrize("side", SIDES)
def test_oct7_deep_itm_small_pct_does_not_arm_ce_pe(side):
    """SENSEX 72600 CE @ ₹418.82 +20.48pt (~5%) must not scratch."""
    s = _settings()
    trade = _trade(side, 418.82, 20.48, symbol="SENSEX", strike=72600.0)
    assert profit_ladder_floor(trade, 20.48, settings=s) is None
    with _use(s):
        reason, _ = evaluate_explosion_exit(trade, 425.0, "ELITE", 20, live_velocity_3s=-0.5)
    assert reason is None or not str(reason).startswith("explosion_profit_ladder")


@pytest.mark.parametrize("side", SIDES)
def test_breakeven_lock_off_by_default_ce_pe(side):
    """A +10% peak does not lock entry+2%. Peak-keep and N× still arm above it."""
    s = Settings()
    trade = _trade(side, 100.0, 10.0)
    assert profit_ladder_floor(trade, 10.0, settings=s) is None
    with _use(s):
        reason, _ = evaluate_explosion_exit(trade, 101.5, "ELITE", 65, live_velocity_3s=-0.5)
    assert reason is None or not str(reason).startswith("explosion_profit_ladder")


@pytest.mark.parametrize("side", SIDES)
def test_oct16_sub_fifteen_pct_peaks_stay_open_ce_pe(side):
    """Oct 16 23050 CALL +13% and 14:28 23150 CALL +12.3% do not arm the ladder."""
    s = _settings()
    deep = _trade(side, 127.5, 16.6, strike=23050.0)
    deep.maxLtp = 144.1
    late = _trade(side, 54.83, 6.77, strike=23150.0)
    late.maxLtp = 61.60
    assert profit_ladder_floor(deep, 16.6, settings=s) is None
    assert profit_ladder_floor(late, 6.77, settings=s) is None


@pytest.mark.parametrize("side", SIDES)
def test_breakeven_tier_locks_two_pct_when_enabled_ce_pe(side):
    s = _settings(unified_profit_ladder_breakeven_enabled=True)
    trade = _trade(side, 100.0, 10.0)
    floor, layer = profit_ladder_floor(trade, 10.0, settings=s)
    assert (floor, layer) == (pytest.approx(2.0), "breakeven")
    with _use(s):
        hold, _ = evaluate_explosion_exit(trade, 103.0, "ELITE", 65, live_velocity_3s=-0.5)
        reason, _ = evaluate_explosion_exit(trade, 101.5, "ELITE", 65, live_velocity_3s=-0.5)
    assert hold is None or not str(hold).startswith("explosion_profit_ladder")
    assert reason == "explosion_profit_ladder_breakeven"


@pytest.mark.parametrize("side", SIDES)
def test_sep03_modest_peak_keep_floor_ce_pe(side):
    """Sep03 23900 PE @ ₹79.65 peaked +16.4pt (+20.6%)."""
    s = _settings()
    trade = _trade(side, 79.65, 16.4, strike=23900.0)
    floor, layer = profit_ladder_floor(trade, 16.4, settings=s)
    assert layer == "peak_keep"
    assert floor == pytest.approx(12.3)


def _nx(side: Side) -> PaperTrade:
    """Oct 1 NIFTY 22450 PE: ₹109.65 → max ₹223.65 (2.04×); CE mirror same shape."""
    trade = _trade(
        side,
        109.65,
        114.0,
        strike=22450.0,
        ctx={"explosionTier": "BUILDING", "maxProfitCapture": True},
    )
    trade.maxLtp = 223.65
    return trade


@pytest.mark.parametrize("side", SIDES)
def test_nx_floor_sits_under_peak_by_min_giveback_ce_pe(side):
    s = _settings()
    floor, layer = profit_ladder_floor(_nx(side), 114.0, settings=s)
    assert layer == "multiple"
    assert floor == pytest.approx(223.65 * 0.95 - 109.65, abs=0.02)


@pytest.mark.parametrize("side", SIDES)
def test_nx_books_on_floor_break_without_legacy_rollover_ce_pe(side):
    s = _settings()
    trade = _nx(side)
    with _use(s):
        from app.engines.explosion_profit import unified_profit_ladder_exit_reason

        def _at(ltp: float, v3: float) -> str | None:
            return unified_profit_ladder_exit_reason(
                trade, best=114.0, pnl_pts=ltp - 109.65, hold_seconds=0, live_velocity_3s=v3,
            )

        hold = _at(220.0, -3.0)
        reason = _at(212.0, -0.5)
    assert hold is None
    assert reason == "explosion_profit_ladder_multiple"


@pytest.mark.parametrize("side", SIDES)
def test_nx_fast_fade_books_without_70_or_200_absolutes_ce_pe(side):
    """Cheap ₹40 premium at 2.5×: legacy N× needed entry ≥ ₹70 and LTP ≥ ₹200."""
    s = _settings()
    trade = _trade(side, 40.0, 60.0)
    with _use(s):
        reason, _ = evaluate_explosion_exit(trade, 94.0, "ELITE", 65, live_velocity_3s=-3.0)
    assert reason == "explosion_profit_ladder_multiple_fast_fade"


@pytest.mark.parametrize("side", SIDES)
def test_hot_velocity_defers_without_lowering_floor_ce_pe(side):
    s = _settings()
    trade = _oct12_runner(side)
    with _use(s):
        hot, _ = evaluate_explosion_exit(trade, 66.0, "ELITE", 65, live_velocity_3s=3.0)
    assert hot is None or not str(hot).startswith("explosion_profit_ladder")
    assert trade.entryContext["profitLadder"]["floorPts"] == pytest.approx(7.65)


@pytest.mark.parametrize("side", SIDES)
def test_mega_runner_keeps_75pct_of_k_multiple_ce_pe(side):
    s = _settings()
    trade = _trade(side, 50.0, 300.0)
    floor, layer = profit_ladder_floor(trade, 300.0, settings=s)
    assert (floor, layer) == (pytest.approx(225.0), "multiple")
    with _use(s):
        hold, _ = evaluate_explosion_exit(trade, 280.0, "ELITE", 65, live_velocity_3s=-0.5)
        reason, _ = evaluate_explosion_exit(trade, 274.0, "ELITE", 65, live_velocity_3s=-0.5)
    assert hold is None or not str(hold).startswith("explosion_profit_ladder")
    assert reason == "explosion_profit_ladder_multiple"


@pytest.mark.parametrize("side", SIDES)
def test_floor_only_ratchets_up_ce_pe(side):
    s = _settings()
    trade = _oct12_runner(side)
    first, _ = profit_ladder_floor(trade, 10.2, settings=s)
    later, _ = profit_ladder_floor(trade, 9.0, settings=s)
    assert later == first


@pytest.mark.parametrize("side", SIDES)
def test_losing_trade_left_to_loss_side_exits_ce_pe(side):
    s = _settings()
    trade = _oct12_runner(side)
    with _use(s):
        from app.engines.explosion_profit import unified_profit_ladder_exit_reason

        reason = unified_profit_ladder_exit_reason(
            trade, best=10.2, pnl_pts=-1.0, hold_seconds=600, live_velocity_3s=-3.0,
        )
    assert reason is None


@pytest.mark.parametrize("side", SIDES)
def test_oct16_23150_shape_books_seventy_five_pct_ce_pe(side):
    """Oct 16 NIFTY 23150 CALL: 71.10 → 91.00 (+19.9) sold 82.70 on the old trail.

    Ladder floor is 75% of +19.9 = +14.92, premium 86.02, on both sides.
    """
    s = _settings()
    trade = _trade(side, 71.1, 19.9, strike=23150.0, seconds=600)
    trade.maxLtp = 91.0
    trade.lots = 19
    floor, layer = profit_ladder_floor(trade, 19.9, settings=s)
    assert layer == "peak_keep"
    assert floor == pytest.approx(14.92)
    with _use(s):
        hold, _ = evaluate_explosion_exit(trade, 86.10, "EXPLODING", 65, live_velocity_3s=-0.5)
        reason, pnl_inr = evaluate_explosion_exit(trade, 86.02, "EXPLODING", 65, live_velocity_3s=-0.5)
    assert hold is None or not str(hold).startswith("explosion_profit_ladder")
    assert reason == "explosion_profit_ladder_peak_keep"
    assert pnl_inr == pytest.approx(14.92 * 65 * 19, rel=0.01)
