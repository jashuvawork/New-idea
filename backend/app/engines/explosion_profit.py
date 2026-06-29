"""Explosion profit mode — ride premium explosions with trailing SL/TP while winning."""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.capital_allocator import compute_lots
from app.engines.explosion_detector import ExplosionEvent
from app.engines.session_timing import in_open_caution_window, min_explosion_score_now
from app.models.schemas import Breadth, PaperTrade, Side, StrategyType, SuggestedTrade

IST = ZoneInfo("Asia/Kolkata")

# symbol -> (last stop timestamp, cooldown seconds)
_explosion_stop_at: dict[str, tuple[datetime, int]] = {}


def record_explosion_stop(symbol: str, cooldown_seconds: Optional[int] = None) -> None:
    settings = get_settings()
    secs = cooldown_seconds if cooldown_seconds is not None else settings.explosion_reentry_cooldown_seconds
    _explosion_stop_at[symbol.upper()] = (datetime.now(IST), secs)


def explosion_in_cooldown(symbol: str) -> bool:
    entry = _explosion_stop_at.get(symbol.upper())
    if not entry:
        return False
    ts, cooldown = entry
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    elapsed = (datetime.now(IST) - ts.astimezone(IST)).total_seconds()
    return elapsed < cooldown


def cooldown_remaining_seconds(symbol: str) -> int:
    entry = _explosion_stop_at.get(symbol.upper())
    if not entry:
        return 0
    ts, cooldown = entry
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    elapsed = (datetime.now(IST) - ts.astimezone(IST)).total_seconds()
    return max(0, int(cooldown - elapsed))


def check_explosion_entry(
    event: ExplosionEvent,
    trade: SuggestedTrade,
    breadth: Breadth,
    calibration_blocked: bool,
) -> tuple[bool, str]:
    """Fast entry on explosion — minimal gates, speed is everything."""
    settings = get_settings()
    if calibration_blocked:
        return False, "calibration_block"

    if explosion_in_cooldown(event.symbol):
        return False, f"explosion_cooldown_{cooldown_remaining_seconds(event.symbol)}s"

    if event.tier not in ("EXPLODING", "ELITE"):
        return False, f"tier_{event.tier}_not_tradeable"

    if event.velocity_3s < settings.explosion_min_velocity_3s and event.velocity_9s < settings.explosion_min_velocity_9s:
        return False, "velocity_too_low"

    if event.tier == "ELITE":
        return True, "elite_explosion"

    min_score = min_explosion_score_now()
    if in_open_caution_window() and event.tier != "ELITE" and event.explosion_score < min_score + 5:
        return False, "open_caution_wait_for_elite"
    if event.tier == "EXPLODING" and event.explosion_score >= min_score:
        return True, "explosion_confirmed"

    if event.velocity_3s >= settings.explosion_early_velocity_3s and event.volume_surge >= settings.explosion_early_volume_surge:
        return True, "early_explosion"

    return False, "not_confirmed"


def compute_explosion_lots(event: ExplosionEvent, tqs: float, premium: float) -> int:
    """Size explosion trades at 85% capital max — same as compute_lots."""
    return compute_lots(
        event.symbol,
        premium,
        stop_points=get_settings().explosion_initial_stop_points,
        tqs=tqs,
        strategy_type=StrategyType.EXPLOSIVE,
        confidence=event.explosion_score,
        tier=event.tier,
    )


def _hold_seconds(trade: PaperTrade) -> float:
    opened = trade.openedAt
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=IST)
    return (datetime.now(IST) - opened.astimezone(IST)).total_seconds()


def _target_points(event_tier: str) -> float:
    settings = get_settings()
    if event_tier == "ELITE":
        return settings.explosion_target_elite
    return settings.explosion_target_standard


def _trail_floor_pts(trade: PaperTrade, best: float, settings) -> Optional[float]:
    """Trailing floor in PnL points — arms only after minimum profit."""
    if best < settings.explosion_trail_arm_points:
        return None

    ratio_floor = best * settings.explosion_trail_keep_ratio
    step_floor = best - settings.explosion_trail_step_points
    floor_pts = max(ratio_floor, step_floor)

    if best >= settings.explosion_trail_tight_arm:
        tight_floor = best - settings.explosion_trail_tight_points
        floor_pts = max(floor_pts, tight_floor)

    ctx = trade.entryContext or {}
    prev = ctx.get("explosionTrailFloorPts")
    if prev is not None:
        floor_pts = max(floor_pts, float(prev))
    ctx["explosionTrailFloorPts"] = round(floor_pts, 2)
    ctx["explosionBestPts"] = round(best, 2)
    trade.entryContext = ctx
    return floor_pts


def evaluate_explosion_exit(
    trade: PaperTrade,
    current_premium: float,
    event_tier: str = "EXPLODING",
    lot_multiplier: int = 25,
) -> tuple[Optional[str], float]:
    """
    Explosion exits: hard SL when losing, trailing SL + TP while winning.
    Lets runners extend; locks profit as peak builds.
    """
    settings = get_settings()
    pnl_pts = current_premium - trade.entryPremium
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    best = max(trade.bestPnlPoints, pnl_pts)
    hold = _hold_seconds(trade)
    target = _target_points(event_tier)

    if pnl_inr <= -settings.emergency_stop_inr:
        return "explosion_emergency_stop", pnl_inr

    trail_floor = _trail_floor_pts(trade, best, settings)

    # Take profit at target while winning
    if pnl_pts >= target:
        return "explosion_target_hit", pnl_inr

    # Trailing stop while in profit (armed after trail_arm_points)
    if trail_floor is not None and pnl_pts <= trail_floor and best >= settings.explosion_trail_arm_points:
        return "explosion_trail_sl", pnl_inr

    # Legacy trail lock label when ratio breach without stored floor
    if trail_floor is not None and pnl_pts < best * settings.explosion_trail_keep_ratio and best >= 8:
        return "explosion_trail_lock", pnl_inr

    # Initial hard stop before trail arms
    if trail_floor is None and hold >= 15 and pnl_pts <= -settings.explosion_initial_stop_points:
        return "explosion_stop_loss", pnl_inr

    # No progress only when never reached trail arm
    if hold >= 90 and best < settings.explosion_trail_arm_points:
        return "explosion_no_progress", pnl_inr

    # Time cap — take profit if green, else stop
    max_hold = 300 if event_tier == "ELITE" or best >= 15 else 240
    if hold >= max_hold:
        return ("explosion_time_profit" if pnl_pts > 0 else "explosion_time_stop"), pnl_inr

    return None, pnl_inr
