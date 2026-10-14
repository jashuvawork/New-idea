"""Peak-keep %-floor point arm scales with entry premium (Oct 12 NIFTY 22300 PE @ ₹58.5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.moment_stage_trail import ftv_runner_pct_floor
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides) -> Settings:
    base = {
        "october_frozen_profile_enabled": True,
        "live_paper_parity_enabled": True,
        "live_best_trades_only_enabled": False,
        "worst_day_blocks_live": False,
    }
    base.update(overrides)
    return Settings(**base)


def _runner(side: Side, strike: float, entry: float, best: float, *, minutes: int = 17) -> PaperTrade:
    return PaperTrade(
        id=f"oct12-{side.value}-{strike}",
        symbol="NIFTY",
        side=side,
        strike=strike,
        entryPremium=entry,
        currentPremium=entry + best,
        lots=11,
        openedAt=datetime.now(IST) - timedelta(minutes=minutes),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        entryContext={
            "maxProfitCapture": True,
            "vBaseFtvRunner": True,
            "momentStageLadder": True,
            "projectedMaxTp": 258.1,
            "stageSize": 45.0,
            "stageGivebackRatio": 0.5,
            "stageLateGivebackRatio": 1.0,
            "stageLateProgress": 0.7,
            "momentType": "squeeze_release",
        },
    )


@pytest.mark.parametrize("side,strike", [(Side.PUT, 22300.0), (Side.CALL, 22400.0)])
def test_cheap_premium_modest_peak_arms_pct_keep_ce_pe(side, strike):
    s = _settings()
    trade = _runner(side, strike, 58.5, 10.2)
    floor = ftv_runner_pct_floor(trade, 10.2, settings=s)
    assert floor == pytest.approx(10.2 * 0.75, rel=0.01)


@pytest.mark.parametrize("side,strike", [(Side.PUT, 22300.0), (Side.CALL, 22400.0)])
def test_cheap_premium_below_scaled_arm_stays_unarmed_ce_pe(side, strike):
    s = _settings()
    trade = _runner(side, strike, 58.5, 7.5)
    assert ftv_runner_pct_floor(trade, 7.5, settings=s) is None


@pytest.mark.parametrize("side,strike", [(Side.PUT, 22300.0), (Side.CALL, 22400.0)])
def test_scaled_arm_disabled_restores_20pt_arm_ce_pe(side, strike):
    s = _settings(ftv_runner_pct_trail_arm_min_best_pct_of_entry=0.0)
    trade = _runner(side, strike, 58.5, 10.2)
    assert ftv_runner_pct_floor(trade, 10.2, settings=s) is None


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_deep_itm_small_pct_peak_still_unarmed_ce_pe(side):
    """Oct 7 SENSEX 72600 CE shape: +20pt at ~5% must not arm (min gain 8%)."""
    s = _settings()
    trade = _runner(side, 72600.0, 418.82, 20.48)
    assert ftv_runner_pct_floor(trade, 20.48, settings=s) is None


@pytest.mark.parametrize("side,strike", [(Side.PUT, 22300.0), (Side.CALL, 22400.0)])
def test_oct12_replay_books_peak_keep_not_ride_to_scratch_ce_pe(side, strike):
    s = _settings()
    trade = _runner(side, strike, 58.5, 10.2)
    with patch("app.config.get_settings", lambda: s), patch(
        "app.engines.explosion_profit.get_settings", lambda: s
    ), patch("app.engines.moment_stage_trail.get_settings", lambda: s):
        reason_hold, _ = evaluate_explosion_exit(
            trade, 67.0, "ELITE", 65, live_velocity_3s=-0.5,
        )
        reason, pnl_inr = evaluate_explosion_exit(
            trade, 66.0, "ELITE", 65, live_velocity_3s=-0.5,
        )
    assert reason_hold is None
    assert reason == "explosion_peak_keep_trail"
    assert pnl_inr == pytest.approx(7.5 * 65 * 11, rel=0.01)
