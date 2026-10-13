"""Breakeven shakeout hold (Oct 13 NIFTY 22250 CE: peak +17.75pt, booked +0.9pt on a flat-index dip)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines import index_tick_helpers as ith
from app.engines.explosion_profit import breakeven_shakeout_hold, evaluate_explosion_exit
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")
SIDES = [Side.CALL, Side.PUT]
SPOT_ENTRY = 22512.55
ENTRY = 264.25


def _settings(**overrides) -> Settings:
    base = {
        "october_frozen_profile_enabled": True,
        "live_paper_parity_enabled": True,
        "executed_entry_sl_only_loss_exits": True,
        "never_green_hard_stop_enabled": True,
        "catastrophic_loss_stop_pct": 30.0,
        "breakeven_shakeout_hold_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)


@contextmanager
def _use(s: Settings, *, spot: float):
    prev = ith._session_extremes.get("NIFTY")
    ith._session_extremes["NIFTY"] = {
        "date": datetime.now(IST).date().isoformat(),
        "open": SPOT_ENTRY,
        "hi": SPOT_ENTRY + 60,
        "lo": SPOT_ENTRY - 60,
        "last": spot,
    }
    try:
        with patch("app.config.get_settings", lambda: s), patch(
            "app.engines.explosion_profit.get_settings", lambda: s
        ), patch("app.engines.moment_stage_trail.get_settings", lambda: s):
            yield
    finally:
        if prev is None:
            ith._session_extremes.pop("NIFTY", None)
        else:
            ith._session_extremes["NIFTY"] = prev


def _favourable(side: Side, pct: float) -> float:
    """Index spot moved ``pct`` % in the trade's favour (negative = against)."""
    sign = 1.0 if side == Side.CALL else -1.0
    return SPOT_ENTRY * (1.0 + sign * pct / 100.0)


def _oct13(side: Side, *, current: float, best: float = 17.75) -> PaperTrade:
    return PaperTrade(
        id=f"9cb77c3c-{side.value}",
        symbol="NIFTY",
        side=side,
        strike=22250.0,
        entryPremium=ENTRY,
        currentPremium=current,
        lots=2,
        openedAt=datetime.now(IST) - timedelta(seconds=737),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=ENTRY + best,
        entryContext={
            "explosionTier": "EXPLODING",
            "rankGrade": "A",
            "vBaseFtvRunner": True,
            "firstLiftCapture": True,
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "stageSize": 75.0,
            "stageGivebackRatio": 0.5,
            "stageLateGivebackRatio": 1.0,
            "stageLateProgress": 0.7,
            "projectedMaxTp": 800.0,
            "spotAtEntry": SPOT_ENTRY,
            "exitPlan": {
                "stopPoints": 40.0,
                "naturalStopPoints": 40.0,
                "targetPoints": 52.13,
                "trailArmPoints": 16.34,
                "trailKeepRatio": 0.577,
                "trailStepPoints": 2.0,
                "microTargetPoints": 7.37,
                "adaptiveStop": True,
            },
        },
    )


def _exit(trade: PaperTrade, s: Settings, *, spot: float):
    with _use(s, spot=spot):
        return evaluate_explosion_exit(
            trade, trade.currentPremium, "EXPLODING", 65, live_velocity_3s=0.0
        )


@pytest.mark.parametrize("side", SIDES)
def test_legacy_books_breakeven_on_flat_index_dip(side):
    trade = _oct13(side, current=ENTRY + 0.9)
    reason, _ = _exit(trade, _settings(breakeven_shakeout_hold_enabled=False), spot=_favourable(side, -0.015))
    assert reason == "explosion_stage_trail"


@pytest.mark.parametrize("side", SIDES)
def test_holds_cushion_while_index_holds_entry(side):
    trade = _oct13(side, current=ENTRY + 0.9)
    reason, _ = _exit(trade, _settings(), spot=_favourable(side, -0.015))
    assert reason is None
    meta = trade.entryContext["breakevenShakeoutHold"]
    assert meta["spotAtEntry"] == SPOT_ENTRY
    assert meta["maxLossPts"] == pytest.approx(ENTRY * 0.04, abs=0.01)


@pytest.mark.parametrize("side", SIDES)
def test_holds_small_red_dip_while_index_holds_entry(side):
    trade = _oct13(side, current=ENTRY - 2.25)
    reason, _ = _exit(trade, _settings(), spot=_favourable(side, 0.02))
    assert reason is None


@pytest.mark.parametrize("side", SIDES)
def test_exits_when_index_breaks_entry_against_side(side):
    trade = _oct13(side, current=ENTRY - 2.25)
    reason, _ = _exit(trade, _settings(), spot=_favourable(side, -0.08))
    assert reason == "explosion_stage_trail"
    assert "breakevenShakeoutHold" not in trade.entryContext


@pytest.mark.parametrize("side", SIDES)
def test_exits_when_loss_reaches_cap(side):
    trade = _oct13(side, current=ENTRY - 11.25)
    reason, _ = _exit(trade, _settings(), spot=_favourable(side, 0.0))
    assert reason == "explosion_stage_trail"


@pytest.mark.parametrize("side", SIDES)
def test_no_hold_without_live_index_tick(side):
    trade = _oct13(side, current=ENTRY + 0.9)
    s = _settings()
    with patch("app.engines.index_tick_helpers.index_session_extremes", lambda _sym: {}):
        assert breakeven_shakeout_hold(trade, pnl_pts=0.9, stage_floor=1.0, settings=s) is False


@pytest.mark.parametrize("side", SIDES)
def test_no_hold_above_bare_cushion(side):
    """A real stage / peak-keep floor is a profit lock — never deferred here."""
    trade = _oct13(side, current=ENTRY + 0.9)
    s = _settings()
    with _use(s, spot=_favourable(side, 0.1)):
        assert breakeven_shakeout_hold(trade, pnl_pts=0.9, stage_floor=1.0, settings=s) is True
        assert breakeven_shakeout_hold(trade, pnl_pts=5.0, stage_floor=6.0, settings=s) is False
        assert breakeven_shakeout_hold(trade, pnl_pts=0.9, stage_floor=None, settings=s) is False


def test_flag_off_by_default_and_on_in_frozen_overlay():
    from pathlib import Path

    assert Settings().breakeven_shakeout_hold_enabled is False
    overlay = Path(__file__).resolve().parents[2] / "deploy" / "env.october-frozen.overlay"
    assert "BREAKEVEN_SHAKEOUT_HOLD_ENABLED=true" in overlay.read_text()
