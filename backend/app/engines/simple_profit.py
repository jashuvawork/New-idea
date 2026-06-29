"""Simple Profit Mode — ultra-profile scalp: best setups, hold for certain profit."""

from datetime import datetime
from typing import Optional

from app.config import get_settings
from app.engines.premium_filter import premium_in_band, premium_reject_reason
from app.engines.session_timing import in_midday_chop_window
from app.models.schemas import (
    Breadth,
    OptimizedProfile,
    PaperTrade,
    Side,
    SuggestedTrade,
)
from app.services.upstox import get_market_phase


def get_session_targets() -> OptimizedProfile:
    """Session-adaptive targets — hold longer for profit certainty."""
    settings = get_settings()
    phase = get_market_phase()
    micro = settings.enhanced_micro_target_points

    if phase == "PREMARKET":
        return OptimizedProfile(
            targetPoints=7.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=240, sessionLabel="premarket",
        )

    now = datetime.now()
    hour, minute = now.hour, now.minute
    t = hour * 60 + minute

    if 9 * 60 + 15 <= t < 10 * 60:
        return OptimizedProfile(
            targetPoints=7.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=240, sessionLabel="open_drive",
        )
    if 11 * 60 + 30 <= t < 13 * 60:
        return OptimizedProfile(
            targetPoints=6.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=210, sessionLabel="midday_chop",
        )
    if 14 * 60 + 30 <= t < 15 * 60 + 15:
        return OptimizedProfile(
            targetPoints=6.5, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=240, sessionLabel="closing_momentum",
        )
    return OptimizedProfile(
        targetPoints=6.5, stopPoints=3.0, microTargetPoints=micro,
        maxHoldSeconds=240, sessionLabel="normal",
    )


def check_entry_gate(
    trade: SuggestedTrade,
    breadth: Breadth,
    tqs: float,
    velocity_pct: float,
    calibration_blocked: bool,
    momentum_surge: bool = False,
    alignment_override: bool = False,
) -> tuple[bool, str]:
    """Ultra-profile gates — best scalp only."""
    settings = get_settings()

    if calibration_blocked:
        return False, "daily_calibration_block"

    if not premium_in_band(trade.lastPremium):
        return False, premium_reject_reason(trade.lastPremium)

    min_score = (
        settings.sure_shot_scalp_min_score
        if settings.sure_shot_mode_enabled
        else (settings.aggressive_min_tqs if settings.aggressive_lot_sizing else settings.enhanced_tqs_entry)
    )
    trade_score = max(trade.tqs, trade.confidence or 0)

    if settings.sure_shot_mode_enabled and settings.midday_chop_block_scalps and in_midday_chop_window():
        if not (breadth.aligned and trade_score >= min_score + 5):
            return False, "midday_chop_wait"

    if velocity_pct < settings.enhanced_velocity_threshold:
        return False, f"velocity_below_{settings.enhanced_velocity_threshold}pct"

    if trade_score < min_score:
        return False, f"score_below_{min_score}"

    side_bias = "BULLISH" if trade.side == Side.CALL else "BEARISH"

    if settings.sure_shot_mode_enabled:
        if alignment_override or (momentum_surge and trade_score >= min_score + 10):
            return True, "passed"
        if not breadth.aligned:
            return False, "breadth_not_aligned"
        if breadth.bias not in (side_bias, "NEUTRAL"):
            return False, "breadth_opposes_side"
        return True, "passed"

    effective_vel = velocity_pct
    if effective_vel < settings.enhanced_velocity_threshold and trade_score >= min_score:
        effective_vel = settings.enhanced_velocity_threshold

    if effective_vel < settings.enhanced_velocity_threshold:
        return False, f"velocity_below_{settings.enhanced_velocity_threshold}pct"

    if breadth.bias != side_bias and not alignment_override:
        if not momentum_surge and trade_score < min_score + 8:
            return False, "breadth_misalignment"

    if not (momentum_surge or alignment_override or breadth.aligned or trade_score >= min_score + 5):
        return False, "no_momentum_or_alignment"

    return True, "passed"


def compute_lot_size(tqs: float, symbol: str = "NIFTY", premium: float = 100.0) -> int:
    from app.engines.capital_allocator import compute_lots
    from app.models.schemas import StrategyType

    profile = get_session_targets()
    return compute_lots(symbol, premium, profile.stopPoints, tqs=tqs, strategy_type=StrategyType.SCALP)


def evaluate_exit(
    trade: PaperTrade,
    current_premium: float,
    profile: OptimizedProfile,
    lot_multiplier: int = 25,
) -> tuple[Optional[str], float]:
    """
    Hold winners for certain profit; point stop before INR emergency (66K path).
    """
    settings = get_settings()
    pnl_pts = current_premium - trade.entryPremium
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    hold_seconds = (datetime.utcnow() - trade.openedAt.replace(tzinfo=None)).total_seconds()

    best = max(trade.bestPnlPoints, pnl_pts)
    min_hold = settings.scalp_stop_min_hold_seconds

    # Point stop before flat INR emergency — Jun 25 winning pattern
    if hold_seconds >= min_hold and pnl_pts <= -profile.stopPoints:
        return "simple_stop_loss", pnl_inr

    if pnl_inr <= -settings.emergency_stop_inr:
        return "simple_emergency_inr_stop", pnl_inr

    if pnl_pts >= profile.targetPoints:
        return "simple_profit_target_hit", pnl_inr

    # Micro lock only after meaningful giveback — let winners run
    if pnl_pts >= profile.microTargetPoints:
        if best - pnl_pts >= 2.0:
            return "simple_micro_profit_lock", pnl_pts * trade.lots * lot_multiplier

    if best >= 3.5 and pnl_pts < best * 0.60:
        return "simple_trail_profit_lock", pnl_pts * trade.lots * lot_multiplier

    # No scratch while green — hold for profit
    if hold_seconds >= settings.scalp_no_progress_seconds:
        if best > 0 and pnl_pts > 0:
            return "simple_time_profit_lock", pnl_inr
        if best <= 0:
            return "simple_no_progress_scratch", pnl_inr

    if hold_seconds >= profile.maxHoldSeconds:
        if pnl_pts > 0:
            return "simple_time_profit_lock", pnl_inr
        return "simple_time_stop", pnl_inr

    return None, pnl_inr
