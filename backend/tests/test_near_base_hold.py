"""Near-base top rips hold for the max move — don't soft-lock a small early peak.

Aug5 SENSEX 78400 PE: entered ~11% off the local base (base rip ahead) but peak-fade
booked it at a tiny +profit. A top ELITE/EXPLODING entered near the base should hold for
a bigger peak before the soft profit-lock; the breakeven lock still protects downside.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import (
    _near_base_top_runner,
    peak_fade_profit_lock_reason,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _trade(rel, tier="ELITE", *, best=11.0, psych=None):
    ctx = {"localBaseBaseRelPct": rel, "explosionTier": tier}
    if psych:
        ctx["psychologyLabel"] = psych
    return PaperTrade(
        id="t", symbol="SENSEX", side=Side.PUT, strike=78400.0,
        entryPremium=356.0, currentPremium=363.5, lots=1,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=120),
        bestPnlPoints=best, entryContext=ctx,
    )


def test_near_base_top_runner_detected():
    assert _near_base_top_runner(_trade(11.0, "ELITE")) is True
    assert _near_base_top_runner(_trade(40.0, "ELITE")) is False  # mid-leg
    assert _near_base_top_runner(_trade(11.0, "BUILDING")) is False  # not top tier
    assert _near_base_top_runner(_trade(11.0, "ELITE", psych="CAUTION")) is False  # protective
    # OVERCONFIDENCE is common on strong ICT winners — must still hold.
    assert _near_base_top_runner(_trade(14.5, "EXPLODING", psych="OVERCONFIDENCE")) is True


def test_watch_first_lift_is_a_near_base_top_runner():
    trade = _trade(15.0, "WATCH")
    trade.entryContext["ictFirstLift"] = True
    trade.entryContext["firstLiftCapture"] = True
    assert _near_base_top_runner(trade) is True


def test_near_base_holds_small_peak():
    """11% off base, peaked +11 now +7.5 → hold (no soft lock)."""
    reason = peak_fade_profit_lock_reason(_trade(11.0), best=11.0, pnl_pts=7.5)
    assert reason is None


def test_mid_leg_still_books_on_fade():
    """40% off base (mid-leg), same fade → books (capture/fade lock fires)."""
    reason = peak_fade_profit_lock_reason(_trade(40.0), best=11.0, pnl_pts=7.5)
    assert reason in ("explosion_peak_capture", "explosion_peak_fade_profit_lock")


def test_near_base_still_books_big_peak_fade():
    """Once a near-base runner prints a big peak (≥28) and gives it back, it books."""
    reason = peak_fade_profit_lock_reason(_trade(11.0, best=32.0), best=32.0, pnl_pts=8.0)
    assert reason is not None


def test_near_base_breakeven_still_protected():
    """Downside protection intact: near-base runner faded to breakeven still books BE."""
    reason = peak_fade_profit_lock_reason(_trade(11.0, best=11.0), best=11.0, pnl_pts=0.0)
    assert reason == "explosion_peak_fade_breakeven"
