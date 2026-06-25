"""Explosion profit mode — ride premium explosions, don't cut winners early."""

from typing import Optional

from app.config import get_settings
from app.engines.explosion_detector import ExplosionEvent
from app.models.schemas import Breadth, PaperTrade, Side, SuggestedTrade


def check_explosion_entry(
    event: ExplosionEvent,
    trade: SuggestedTrade,
    breadth: Breadth,
    calibration_blocked: bool,
) -> tuple[bool, str]:
    """Fast entry on explosion — minimal gates, speed is everything."""
    if calibration_blocked:
        return False, "calibration_block"

    if event.tier not in ("EXPLODING", "ELITE"):
        return False, f"tier_{event.tier}_not_tradeable"

    if event.velocity_3s < 2.0 and event.velocity_9s < 3.0:
        return False, "velocity_too_low"

    # ELITE/EXPLODING: skip breadth — chart shows explosions happen against chop
    if event.tier == "ELITE":
        return True, "elite_explosion"

    min_score = get_settings().aggressive_min_explosion_score
    if event.tier == "EXPLODING" and event.explosion_score >= min_score:
        return True, "explosion_confirmed"

    # BUILDING with strong velocity — enter early
    if event.velocity_3s >= 3.0 and event.volume_surge >= 1.5:
        return True, "early_explosion"

    return False, "not_confirmed"


def compute_explosion_lots(event: ExplosionEvent, tqs: float) -> int:
    settings = get_settings()
    if event.tier == "ELITE":
        return settings.simple_max_lots
    if event.tier == "EXPLODING" and event.explosion_score >= 70:
        return settings.simple_target_lots
    return settings.simple_min_lots


def evaluate_explosion_exit(
    trade: PaperTrade,
    current_premium: float,
    event_tier: str = "EXPLODING",
    lot_multiplier: int = 25,
) -> tuple[Optional[str], float]:
    """
    Exit rules tuned for explosion rides like +40pt NIFTY CE moves.
    Let winners run — trail loosely, cut losers fast.
    """
    settings = get_settings()
    pnl_pts = current_premium - trade.entryPremium
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    best = max(trade.bestPnlPoints, pnl_pts)

    from datetime import datetime
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    hold = (datetime.now(IST) - trade.openedAt.replace(tzinfo=IST) if trade.openedAt.tzinfo is None
            else datetime.now(IST) - trade.openedAt.astimezone(IST)).total_seconds()

    # Emergency stop
    if pnl_inr <= -settings.emergency_stop_inr:
        return "explosion_emergency_stop", pnl_inr

    # Fast cut: 4pt stop after 15s (explosions reverse hard)
    if hold >= 15 and pnl_pts <= -4.0:
        return "explosion_stop_loss", pnl_inr

    # Elite runners: target 25pt, trail from 8pt
    if event_tier == "ELITE" or best >= 15:
        if pnl_pts >= 25:
            return "explosion_target_hit", pnl_inr
        if best >= 8 and pnl_pts < best * 0.60:
            return "explosion_trail_lock", pnl_inr
        if hold >= 300:
            return "explosion_time_profit" if pnl_pts > 0 else "explosion_time_stop", pnl_inr
        return None, pnl_inr

    # Standard explosion: target 12pt, trail from 5pt
    if pnl_pts >= 12:
        return "explosion_target_hit", pnl_inr

    # Momentum trail — keep 65% of best after 5pt arm
    if best >= 5 and pnl_pts < best * 0.65:
        return "explosion_trail_lock", pnl_inr

    # Micro lock only if never built momentum (avoid cutting rockets)
    if best < 3 and pnl_pts >= 3 and best - pnl_pts >= 1.5:
        return "explosion_micro_lock", pnl_inr

    # No progress: 60s flat
    if hold >= 60 and best <= 0.5:
        return "explosion_no_progress", pnl_inr

    # Max hold 4 min for explosion trades
    if hold >= 240:
        return "explosion_time_profit" if pnl_pts > 0 else "explosion_time_stop", pnl_inr

    return None, pnl_inr
