"""Simple Profit Mode — enhanced quick scalp entry/exit rules."""

from datetime import datetime, timedelta
from typing import Optional

from app.config import get_settings
from app.engines.premium_filter import premium_in_band, premium_reject_reason
from app.engines.risk_stops import effective_emergency_stop_inr
from app.models.schemas import (
    Breadth,
    OptimizedProfile,
    PaperTrade,
    Side,
    SuggestedTrade,
)
from app.services.upstox import get_market_phase


def get_session_targets() -> OptimizedProfile:
    """Session-adaptive targets — enhanced with tighter micro locks."""
    settings = get_settings()
    phase = get_market_phase()
    micro = settings.enhanced_micro_target_points

    if phase == "PREMARKET":
        return OptimizedProfile(
            targetPoints=7.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=180, sessionLabel="premarket",
        )

    now = datetime.now()
    hour, minute = now.hour, now.minute
    t = hour * 60 + minute

    # IST session windows (approximate)
    if 9 * 60 + 15 <= t < 10 * 60:
        return OptimizedProfile(
            targetPoints=7.0, stopPoints=settings.scalp_stop_points, microTargetPoints=micro,
            maxHoldSeconds=180, sessionLabel="open_drive",
        )
    if 11 * 60 + 30 <= t < 13 * 60:
        return OptimizedProfile(
            targetPoints=5.0, stopPoints=settings.scalp_stop_points, microTargetPoints=micro,
            maxHoldSeconds=150, sessionLabel="midday_chop",
        )
    if 14 * 60 + 30 <= t < 15 * 60 + 15:
        return OptimizedProfile(
            targetPoints=6.5, stopPoints=settings.scalp_stop_points, microTargetPoints=micro,
            maxHoldSeconds=180, sessionLabel="closing_momentum",
        )
    return OptimizedProfile(
        targetPoints=6.0, stopPoints=settings.scalp_stop_points, microTargetPoints=micro,
        maxHoldSeconds=180, sessionLabel="normal",
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
    """All gates must pass for simple profit entry."""
    settings = get_settings()

    if calibration_blocked:
        return False, "daily_calibration_block"

    if not premium_in_band(trade.lastPremium):
        return False, premium_reject_reason(trade.lastPremium)

    min_score = settings.aggressive_min_tqs if settings.aggressive_lot_sizing else settings.enhanced_tqs_entry
    trade_score = max(trade.tqs, trade.confidence or 0)

    # Strategy signals may lack runner velocity — use confidence as fallback
    effective_vel = velocity_pct
    if effective_vel < settings.enhanced_velocity_threshold and trade_score >= min_score:
        effective_vel = settings.enhanced_velocity_threshold

    if effective_vel < settings.enhanced_velocity_threshold:
        return False, f"velocity_below_{settings.enhanced_velocity_threshold}pct"

    if trade_score < min_score:
        return False, f"score_below_{min_score}"

    # Breadth: relaxed when trade score is strong
    side_bias = "BULLISH" if trade.side == Side.CALL else "BEARISH"
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
    Evaluate exit rules for open paper trade.
    Returns (exit_reason, pnl_inr) or (None, current_pnl).
    """
    settings = get_settings()
    pnl_pts = current_premium - trade.entryPremium
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    hold_seconds = (datetime.utcnow() - trade.openedAt.replace(tzinfo=None)).total_seconds()

    # Track best
    best = max(trade.bestPnlPoints, pnl_pts)

    stop_inr = effective_emergency_stop_inr(trade.lots, lot_multiplier, profile.stopPoints)
    if pnl_inr <= -stop_inr:
        return "simple_emergency_inr_stop", pnl_inr

    # Min hold before stop loss
    if hold_seconds >= settings.scalp_stop_min_hold_seconds and pnl_pts <= -profile.stopPoints:
        return "simple_stop_loss", pnl_inr

    # Session profit target
    if pnl_pts >= profile.targetPoints:
        return "simple_profit_target_hit", pnl_inr

    # Micro profit lock (enhanced: 2.5pt default)
    if pnl_pts >= profile.microTargetPoints:
        if best - pnl_pts >= 1.25:
            return "simple_micro_profit_lock", pnl_pts * trade.lots * lot_multiplier
        # Still in profit zone above micro — allow trail

    # Trail profit lock: retain 55% of best gain after 2.5pt arm
    if best >= 2.5 and pnl_pts < best * 0.55:
        return "simple_trail_profit_lock", pnl_pts * trade.lots * lot_multiplier

    # No-progress scratch: 90s never green
    if hold_seconds >= 90 and best <= 0:
        return "simple_no_progress_scratch", pnl_inr

    # Time-based exits at max hold
    if hold_seconds >= profile.maxHoldSeconds:
        if pnl_pts > 0:
            return "simple_time_profit_lock", pnl_inr
        return "simple_time_stop", pnl_inr

    return None, pnl_inr
