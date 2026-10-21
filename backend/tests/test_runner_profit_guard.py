"""Runner profit guard — a run that printed real green never rides back to the stop.

Oct 21 SENSEX 73400 PE: entry 340.33, peak 388.00 (+47.67pt, +14.0%), then a fast
bleed through every 75% line to the −40pt adaptive stop (−₹21k on 26 lots). The TP
rung ladder now owns runners past +28pt; the 73300 PE (+21pt peak) replays to the
stop without this guard.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.explosion_profit import (
    evaluate_explosion_exit,
    runner_profit_guard_exit_reason,
    runner_profit_guard_floor,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")

SIDES = [Side.CALL, Side.PUT]


def _runner(
    side: Side,
    *,
    entry: float = 340.33,
    best: float = 47.67,
    pnl: float = 20.0,
    below_for: float | None = None,
):
    ctx = {
        "maxProfitCapture": True,
        "momentStageLadder": True,
        "projectedMaxTp": 800.0,
        "stageSize": 75.0,
        "velocity3s": 6.0,
        "exitPlan": {
            "projectedMaxTp": 800.0,
            "stageSize": 75.0,
            "stopPoints": 40.0,
            "trailArmPoints": 24.25,
            "adaptiveStop": True,
        },
    }
    if below_for is not None:
        ctx["runnerGuardBelowSince"] = (
            datetime.now(IST) - timedelta(seconds=below_for)
        ).isoformat()
    return PaperTrade(
        id=f"guard-{side.value}",
        symbol="SENSEX",
        side=side,
        strike=73400.0,
        entryPremium=entry,
        currentPremium=entry + pnl,
        lots=26,
        openedAt=datetime.now(IST) - timedelta(seconds=900),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        entryContext=ctx,
    )


def _guard(trade: PaperTrade, s: Settings, *, v3: float):
    with patch("app.engines.explosion_profit.get_settings", return_value=s):
        return runner_profit_guard_exit_reason(
            trade, pnl_pts=trade.currentPremium - trade.entryPremium, live_velocity_3s=v3,
        )


def _tier2_floor(s: Settings) -> float:
    return 47.67 * s.runner_profit_guard_tier2_keep_ratio


@pytest.mark.parametrize("side", SIDES)
def test_floor_tiers_mirror_for_call_and_put(side):
    s = Settings()
    cases = [
        (340.33, 47.67, 47.67 * s.runner_profit_guard_tier2_keep_ratio),
        (300.0, 20.0, 20.0 * s.runner_profit_guard_tier1_keep_ratio),
        (300.0, 90.0, 90.0 * s.runner_profit_guard_tier3_keep_ratio),
        (300.0, 200.0, 200.0 * s.runner_profit_guard_tier4_keep_ratio),
    ]
    for entry, best, expected in cases:
        trade = _runner(side, entry=entry, best=best, pnl=0.0)
        assert runner_profit_guard_floor(trade, settings=s) == pytest.approx(expected)


@pytest.mark.parametrize("side", SIDES)
def test_tier1_floor_is_pure_share_of_peak(side):
    s = Settings()
    trade = _runner(side, entry=300.0, best=16.0, pnl=0.0)
    assert runner_profit_guard_floor(trade, settings=s) == pytest.approx(16.0 * 0.20)


@pytest.mark.parametrize("side", SIDES)
def test_unarmed_below_tier1_and_cheap_premium_noise(side):
    s = Settings()
    assert runner_profit_guard_floor(_runner(side, entry=340.0, best=10.0), settings=s) is None
    assert runner_profit_guard_floor(_runner(side, entry=62.1, best=3.9), settings=s) is None


@pytest.mark.parametrize("side", SIDES)
def test_oct21_73300_fade_books_green_before_adaptive_stop(side):
    """Real Settings, full exit stack: 73300 PE (+21pt peak) sits below the TP rung
    ladder's +28pt arm, so the guard is the only layer between it and the −40pt stop.
    """
    s = Settings()
    entry, best = 308.57, 21.08
    assert best < s.tp_rung_ladder_min_best_to_arm_exits
    floor = best * s.runner_profit_guard_tier1_keep_ratio
    pnl = floor - 1.0
    trade = _runner(
        side, entry=entry, best=best, pnl=pnl,
        below_for=s.runner_profit_guard_confirm_seconds + 5,
    )
    with patch("app.engines.explosion_profit.get_settings", return_value=s), patch(
        "app.engines.moment_stage_trail.get_settings", return_value=s
    ), patch("app.engines.tp_rung_ladder.get_settings", return_value=s), patch(
        "app.engines.explosion_profit._hold_seconds", return_value=900
    ), patch(
        "app.engines.explosion_profit._seconds_since_peak",
        return_value=s.unified_profit_ladder_fall_min_seconds_after_peak - 10,
    ):
        reason, pnl_inr = evaluate_explosion_exit(
            trade, trade.currentPremium, "EXPLODING", 20, live_velocity_3s=-1.5,
        )
    assert reason == "explosion_runner_profit_guard"
    assert pnl_inr == pytest.approx(pnl * 26 * 20)
    assert pnl_inr > 0


@pytest.mark.parametrize("side", SIDES)
def test_first_dip_under_floor_holds_and_stamps(side):
    s = Settings()
    trade = _runner(side, pnl=_tier2_floor(s) - 1.0)
    assert _guard(trade, s, v3=-1.0) is None
    assert trade.entryContext.get("runnerGuardBelowSince")


@pytest.mark.parametrize("side", SIDES)
def test_dip_that_persists_past_confirm_sells(side):
    s = Settings()
    trade = _runner(
        side, pnl=_tier2_floor(s) - 1.0, below_for=s.runner_profit_guard_confirm_seconds + 1
    )
    assert _guard(trade, s, v3=-0.5) == "explosion_runner_profit_guard"


@pytest.mark.parametrize("side", SIDES)
def test_recovery_above_floor_clears_dip_clock(side):
    s = Settings()
    trade = _runner(side, pnl=_tier2_floor(s) + 3.0, below_for=120)
    assert _guard(trade, s, v3=-0.5) is None
    assert "runnerGuardBelowSince" not in trade.entryContext


@pytest.mark.parametrize("side", SIDES)
def test_near_breakeven_and_red_prints_wait_for_confirm(side):
    s = Settings()
    for pnl in (2.0, -5.0):
        assert _guard(_runner(side, pnl=pnl), s, v3=-0.5) is None
        held = _runner(side, pnl=pnl, below_for=s.runner_profit_guard_confirm_seconds + 1)
        assert _guard(held, s, v3=-0.5) == "explosion_runner_profit_guard"


@pytest.mark.parametrize("side", SIDES)
def test_holds_above_floor_and_on_rising_print(side):
    s = Settings()
    assert _guard(_runner(side, pnl=30.0), s, v3=-1.0) is None
    assert _guard(_runner(side, pnl=-5.0, below_for=120), s, v3=0.8) is None


@pytest.mark.parametrize("side", SIDES)
def test_flat_print_sells_without_entry_velocity_fallback(side):
    s = Settings()
    trade = _runner(side, pnl=_tier2_floor(s) - 1.0, below_for=120)
    assert trade.entryContext["velocity3s"] > 0
    assert _guard(trade, s, v3=0.0) == "explosion_runner_profit_guard"


@pytest.mark.parametrize("side", SIDES)
def test_disabled_flag_is_inert(side):
    s = Settings(runner_profit_guard_enabled=False)
    assert _guard(_runner(side, pnl=-5.0), s, v3=-1.0) is None
