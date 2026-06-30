"""Simple Profit Mode — enhanced quick scalp entry/exit rules."""

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.chop_day_guards import in_momentum_rally_window, is_momentum_surge, neutral_breadth_blocks_entry
from app.engines.premium_filter import premium_in_band, premium_reject_reason
from app.engines.session_timing import in_midday_chop_window
from app.models.schemas import (
    Breadth,
    OptimizedProfile,
    PaperTrade,
    Side,
    SuggestedTrade,
)

IST = ZoneInfo("Asia/Kolkata")


def _hold_seconds(trade: PaperTrade) -> float:
    opened = trade.openedAt
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=IST)
    return (datetime.now(IST) - opened.astimezone(IST)).total_seconds()
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
            targetPoints=7.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=180, sessionLabel="open_drive",
        )
    if in_momentum_rally_window() and 11 * 60 <= t < 13 * 60 + 45:
        return OptimizedProfile(
            targetPoints=8.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=300, sessionLabel="momentum_rally",
        )
    if 11 * 60 + 30 <= t < 13 * 60:
        return OptimizedProfile(
            targetPoints=5.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=150, sessionLabel="midday_chop",
        )
    if 14 * 60 + 30 <= t < 15 * 60 + 15:
        return OptimizedProfile(
            targetPoints=6.5, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=180, sessionLabel="closing_momentum",
        )
    return OptimizedProfile(
        targetPoints=6.0, stopPoints=3.0, microTargetPoints=micro,
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

    blocked, nb_reason = neutral_breadth_blocks_entry(
        breadth.bias, trade_score, velocity_pct, explosion=False,
    )
    if blocked and not (momentum_surge or is_momentum_surge(velocity_pct)):
        return False, nb_reason

    if settings.midday_chop_block_scalps and in_midday_chop_window():
        if not (breadth.aligned or momentum_surge or is_momentum_surge(velocity_pct)):
            if trade_score < settings.neutral_breadth_min_score:
                return False, "midday_chop_wait"

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
    hold_seconds = _hold_seconds(trade)

    # Track best
    best = max(trade.bestPnlPoints, pnl_pts)
    min_hold = settings.scalp_stop_min_hold_seconds
    micro_giveback = (
        settings.runner_micro_giveback_points
        if best >= settings.runner_min_best_points
        else 1.25
    )
    trail_keep = (
        settings.runner_trail_keep_ratio
        if best >= settings.runner_min_best_points
        else 0.55
    )

    # Point stop only — no flat INR emergency cap
    if hold_seconds >= min_hold and pnl_pts <= -profile.stopPoints:
        return "simple_stop_loss", pnl_inr

    if settings.emergency_stop_enabled and pnl_inr <= -settings.emergency_stop_inr:
        return "simple_emergency_inr_stop", pnl_inr

    if pnl_pts >= profile.targetPoints:
        return "simple_profit_target_hit", pnl_inr

    if pnl_pts >= profile.microTargetPoints:
        if best - pnl_pts >= micro_giveback:
            return "simple_micro_profit_lock", pnl_pts * trade.lots * lot_multiplier

    if best >= 3.0 and pnl_pts < best * trail_keep:
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
