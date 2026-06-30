"""Tests for psychology setup hold."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.engines.psychology_hold import (
    apply_psychology_hold_profile,
    psychology_exit_tuning,
    psychology_setup_active,
)
from app.models.schemas import OptimizedProfile, PaperTrade, Side

IST = ZoneInfo("Asia/Kolkata")


def _trade(psychology: str = "FEAR", score: float = 70.0) -> PaperTrade:
    return PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24000,
        entryPremium=55,
        currentPremium=58,
        lots=20,
        pnlInr=1000,
        openedAt=datetime.now(IST),
        status="OPEN",
        entryContext={
            "psychology": psychology,
            "selectionScore": score,
        },
    )


def test_psychology_setup_active_on_fear():
    assert psychology_setup_active(_trade("FEAR", 70)) is True
    assert psychology_setup_active(_trade("GREED", 70)) is False
    assert psychology_setup_active(_trade("FEAR", 50)) is False


def test_psychology_hold_extends_profile():
    base = OptimizedProfile(
        targetPoints=8, stopPoints=3, microTargetPoints=4,
        maxHoldSeconds=300, sessionLabel="normal",
    )
    out = apply_psychology_hold_profile(_trade(), base)
    assert out.maxHoldSeconds > base.maxHoldSeconds
    assert "psy_hold" in out.sessionLabel


def test_psychology_exit_tuning():
    tuning = psychology_exit_tuning(_trade())
    assert tuning is not None
    assert tuning.trail_keep_ratio >= 0.5
