"""Deep-ITM runner pullback hold (Oct 13 NIFTY 22250 CE: best +40.8pt, 305→295 dip, ran to 495)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines import explosion_profit as ep
from app.engines import index_tick_helpers as ith
from app.engines.explosion_profit import deep_itm_runner_pullback_hold, evaluate_explosion_exit
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")
SIDES = [Side.CALL, Side.PUT]
SPOT_ENTRY = 22512.55
ENTRY = 264.25
BEST = 40.8
LOCK = "explosion_peak_velocity_reversal_keep"


def _settings(**overrides) -> Settings:
    base = {
        "october_frozen_profile_enabled": True,
        "live_paper_parity_enabled": True,
        "breakeven_shakeout_hold_enabled": True,
        "deep_itm_runner_pullback_hold_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)


@contextmanager
def _spot(spot: float):
    prev = ith._session_extremes.get("NIFTY")
    ith._session_extremes["NIFTY"] = {
        "date": datetime.now(IST).date().isoformat(),
        "open": SPOT_ENTRY,
        "hi": SPOT_ENTRY + 80,
        "lo": SPOT_ENTRY - 80,
        "last": spot,
    }
    try:
        yield
    finally:
        if prev is None:
            ith._session_extremes.pop("NIFTY", None)
        else:
            ith._session_extremes["NIFTY"] = prev


def _favourable(side: Side, pct: float) -> float:
    sign = 1.0 if side == Side.CALL else -1.0
    return SPOT_ENTRY * (1.0 + sign * pct / 100.0)


def _trade(side: Side, *, entry: float = ENTRY, best: float = BEST, pnl: float = 30.55) -> PaperTrade:
    return PaperTrade(
        id=f"9cb77c3c-{side.value}",
        symbol="NIFTY",
        side=side,
        strike=22250.0,
        entryPremium=entry,
        currentPremium=entry + pnl,
        lots=2,
        openedAt=datetime.now(IST) - timedelta(minutes=80),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        entryContext={"explosionTier": "EXPLODING", "rankGrade": "A", "spotAtEntry": SPOT_ENTRY},
    )


def _hold(trade: PaperTrade, s: Settings, *, spot: float, reason: str = LOCK, pnl: float = 30.55,
          best: float = BEST) -> bool:
    with _spot(spot):
        return deep_itm_runner_pullback_hold(trade, reason=reason, best=best, pnl_pts=pnl, settings=s)


@pytest.mark.parametrize("side", SIDES)
def test_holds_shallow_pullback_while_index_holds_entry(side):
    trade = _trade(side)
    assert _hold(trade, _settings(), spot=_favourable(side, 0.08)) is True
    meta = trade.entryContext["runnerPullbackHold"]
    assert meta["deferredExit"] == LOCK
    assert meta["pullbackPct"] == pytest.approx((BEST - 30.55) / (ENTRY + BEST) * 100, abs=0.01)


@pytest.mark.parametrize("side", SIDES)
def test_exits_when_index_breaks_entry_against_side(side):
    trade = _trade(side)
    assert _hold(trade, _settings(), spot=_favourable(side, -0.08)) is False
    assert "runnerPullbackHold" not in trade.entryContext


@pytest.mark.parametrize("side", SIDES)
def test_exits_when_pullback_exceeds_max_pct(side):
    # peak 305.05 → 279.0 is an 8.5% premium pullback (pnl +14.75 still ≥ 35% of best)
    assert _hold(_trade(side, pnl=14.75), _settings(), spot=_favourable(side, 0.05), pnl=14.75) is False


@pytest.mark.parametrize("side", SIDES)
def test_exits_when_keep_ratio_lost(side):
    s = _settings(deep_itm_runner_pullback_hold_max_pullback_pct=20.0)
    assert _hold(_trade(side, pnl=12.0), s, spot=_favourable(side, 0.05), pnl=12.0) is False


@pytest.mark.parametrize("side", SIDES)
def test_never_defers_red_or_cheap_or_exempt(side):
    s = _settings()
    spot = _favourable(side, 0.05)
    assert _hold(_trade(side, pnl=-1.0), s, spot=spot, pnl=-1.0) is False
    assert _hold(_trade(side, entry=60.0, best=12.0, pnl=10.0), s, spot=spot, pnl=10.0, best=12.0) is False
    assert _hold(_trade(side), s, spot=spot, reason="explosion_target_hit") is False
    assert _hold(_trade(side), s, spot=spot, reason="explosion_emergency_stop") is False


@pytest.mark.parametrize("side", SIDES)
def test_no_hold_below_min_best_or_without_index_tick(side):
    s = _settings()
    assert _hold(_trade(side, best=8.0, pnl=7.0), s, spot=_favourable(side, 0.05), pnl=7.0, best=8.0) is False
    trade = _trade(side)
    with patch("app.engines.index_tick_helpers.index_session_extremes", lambda _sym: {}):
        assert deep_itm_runner_pullback_hold(trade, reason=LOCK, best=BEST, pnl_pts=30.55, settings=s) is False


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("enabled,expected", [(False, LOCK), (True, None)])
def test_evaluate_explosion_exit_defers_green_lock(side, enabled, expected):
    s = _settings(deep_itm_runner_pullback_hold_enabled=enabled)
    trade = _trade(side)
    with _spot(_favourable(side, 0.08)), patch.object(ep, "get_settings", lambda: s), patch(
        "app.engines.moment_stage_trail.get_settings", lambda: s
    ), patch.object(ep, "_evaluate_explosion_exit_core", lambda *a, **k: (LOCK, 3972.0)):
        reason, pnl = evaluate_explosion_exit(trade, ENTRY + 30.55, "EXPLODING", 65)
    assert reason == expected
    assert pnl == 3972.0


def test_flag_off_by_default_and_on_in_frozen_overlay():
    from pathlib import Path

    assert Settings().deep_itm_runner_pullback_hold_enabled is False
    overlay = Path(__file__).resolve().parents[2] / "deploy" / "env.october-frozen.overlay"
    assert "DEEP_ITM_RUNNER_PULLBACK_HOLD_ENABLED=true" in overlay.read_text()
