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
    SpotChart,
    SuggestedTrade,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _hold_seconds(trade: PaperTrade) -> float:
    opened = trade.openedAt
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=IST)
    return (datetime.now(IST) - opened.astimezone(IST)).total_seconds()


from app.services.upstox import get_market_phase


def get_session_targets() -> OptimizedProfile:
    """Session-adaptive targets — longer holds to let winners reach 2.5+ PF."""
    settings = get_settings()
    phase = get_market_phase()
    micro = settings.enhanced_micro_target_points

    if phase == "PREMARKET":
        return OptimizedProfile(
            targetPoints=8.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=300, sessionLabel="premarket",
        )

    now = datetime.now()
    hour, minute = now.hour, now.minute
    t = hour * 60 + minute

    # IST session windows (approximate)
    if 9 * 60 + 15 <= t < 10 * 60:
        return OptimizedProfile(
            targetPoints=8.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=420, sessionLabel="open_drive",
        )
    if in_momentum_rally_window() and 11 * 60 <= t < 13 * 60 + 45:
        return OptimizedProfile(
            targetPoints=10.0, stopPoints=3.5, microTargetPoints=micro,
            maxHoldSeconds=480, sessionLabel="momentum_rally",
        )
    if 11 * 60 + 30 <= t < 13 * 60:
        return OptimizedProfile(
            targetPoints=7.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=240, sessionLabel="midday_chop",
        )
    if 14 * 60 + 30 <= t < 15 * 60 + 15:
        return OptimizedProfile(
            targetPoints=8.0, stopPoints=3.0, microTargetPoints=micro,
            maxHoldSeconds=300, sessionLabel="closing_momentum",
        )
    return OptimizedProfile(
        targetPoints=8.0, stopPoints=3.0, microTargetPoints=micro,
        maxHoldSeconds=300, sessionLabel="normal",
    )


def _hold_profile_for_trade(trade: PaperTrade, profile: OptimizedProfile) -> OptimizedProfile:
    """Extend hold + target when direction matches session breadth or entry confidence."""
    from app.engines.bullish_hold import direction_aligned_with_breadth
    from app.engines.confidence_hold import apply_confidence_hold_profile
    from app.engines.psychology_hold import apply_psychology_hold_profile

    settings = get_settings()
    if direction_aligned_with_breadth(trade):
        mult = settings.bullish_hold_max_hold_multiplier
        profile = OptimizedProfile(
            targetPoints=round(profile.targetPoints * 1.15, 2),
            stopPoints=profile.stopPoints,
            microTargetPoints=profile.microTargetPoints,
            maxHoldSeconds=int(profile.maxHoldSeconds * mult),
            sessionLabel=profile.sessionLabel,
        )
    profile = apply_confidence_hold_profile(trade, profile)
    return apply_psychology_hold_profile(trade, profile)


def check_entry_gate(
    trade: SuggestedTrade,
    breadth: Breadth,
    tqs: float,
    velocity_pct: float,
    calibration_blocked: bool,
    momentum_surge: bool = False,
    alignment_override: bool = False,
    chart: Optional["SpotChart"] = None,
    snap: Optional[SymbolSnapshot] = None,
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

    if snap is not None:
        from app.engines.expiry_day_guards import is_symbol_expiry_day

        if is_symbol_expiry_day(snap):
            label = str((snap.psychology or {}).get("label", "NEUTRAL")).upper()
            if label in ("CAUTION", "FEAR"):
                return False, f"expiry_psychology_block_{label.lower()}"
            if float(snap.tradeQualityScore or 0) < settings.expiry_scalp_min_symbol_tqs:
                return False, f"expiry_scalp_tqs_below_{settings.expiry_scalp_min_symbol_tqs:.0f}"

    blocked, nb_reason = neutral_breadth_blocks_entry(
        breadth.bias, trade_score, velocity_pct, explosion=False,
    )
    if blocked and not (momentum_surge or is_momentum_surge(velocity_pct)):
        return False, nb_reason

    if settings.midday_chop_block_scalps and in_midday_chop_window():
        if not (breadth.aligned or momentum_surge or is_momentum_surge(velocity_pct)):
            if trade_score < settings.neutral_breadth_min_score:
                return False, "midday_chop_wait"

    # Counter-trend — BULLISH = CE only, BEARISH = PE only, no CE↔PE switch
    from app.engines.directional_lock import check_directional_side_lock_simple

    blocked_dir, dir_reason = check_directional_side_lock_simple(
        trade.symbol, trade.side, breadth.bias, chart,
    )
    if blocked_dir:
        return False, dir_reason

    side_bias = "BULLISH" if trade.side == Side.CALL else "BEARISH"
    if breadth.bias not in (side_bias, "NEUTRAL") and not alignment_override:
        counter_floor = settings.counter_breadth_min_score
        from app.engines.morning_premium_capture import premium_led_entry_allowed

        if snap is not None and premium_led_entry_allowed(trade.side, snap):
            counter_floor = min(counter_floor, settings.premium_led_counter_breadth_min_score)
        if not momentum_surge and trade_score < counter_floor:
            return False, "breadth_counter_trend"

    from app.engines.spot_direction import chart_blocks_side, is_hard_chart_block

    blocked, chart_reason = chart_blocks_side(
        trade.side, chart, trade_score=trade_score, momentum_surge=momentum_surge,
    )
    if blocked:
        if is_hard_chart_block(chart_reason):
            return False, chart_reason
        if not alignment_override:
            return False, chart_reason

    if not (momentum_surge or alignment_override or breadth.aligned or trade_score >= min_score + 8):
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
    *,
    trail_arm: Optional[float] = None,
    trail_keep: Optional[float] = None,
    trail_step: Optional[float] = None,
    trail_tight_arm: Optional[float] = None,
    trail_tight_pts: Optional[float] = None,
) -> tuple[Optional[str], float]:
    """
    Scalp exit: hard SL when losing, ratcheting trail SL when winning, TP ladder.
    """
    settings = get_settings()
    profile = _hold_profile_for_trade(trade, profile)
    pnl_pts = current_premium - trade.entryPremium
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    hold_seconds = _hold_seconds(trade)
    best = max(trade.bestPnlPoints, pnl_pts)

    from app.engines.bullish_hold import direction_aligned_with_breadth
    from app.engines.confidence_hold import confidence_exit_tuning
    from app.engines.psychology_hold import psychology_exit_tuning

    aligned_hold = direction_aligned_with_breadth(trade)
    conf_tuning = confidence_exit_tuning(trade)
    psy_tuning = psychology_exit_tuning(trade)

    arm = trail_arm if trail_arm is not None else settings.scalp_trail_arm_points
    keep = trail_keep if trail_keep is not None else settings.scalp_trail_keep_ratio
    if aligned_hold:
        keep = min(keep, settings.bullish_hold_trail_keep_ratio)
    if conf_tuning:
        keep = max(keep, conf_tuning.trail_keep_ratio)
    if psy_tuning:
        keep = max(keep, psy_tuning.trail_keep_ratio)
    step = trail_step if trail_step is not None else settings.scalp_trail_step_points
    tight_arm = trail_tight_arm if trail_tight_arm is not None else settings.scalp_trail_tight_arm
    tight_pts = trail_tight_pts if trail_tight_pts is not None else settings.scalp_trail_tight_points

    min_hold = settings.scalp_stop_min_hold_seconds
    micro_giveback = (
        settings.runner_micro_giveback_points
        if best >= settings.runner_min_best_points
        else settings.scalp_micro_giveback_points
    )
    if conf_tuning:
        micro_giveback = max(micro_giveback, conf_tuning.micro_giveback_points)
    if psy_tuning:
        micro_giveback = max(micro_giveback, psy_tuning.micro_giveback_points)
    runner_keep = settings.runner_trail_keep_ratio if best >= settings.runner_min_best_points else keep

    from app.engines.trail_engine import ratcheting_trail_floor

    trail_floor = ratcheting_trail_floor(
        trade,
        best,
        arm_points=arm,
        keep_ratio=keep,
        step_points=step,
        tight_arm=tight_arm,
        tight_points=tight_pts,
        floor_key="scalpTrailFloorPts",
        best_key="scalpTrailBestPts",
    )

    if trail_floor is not None and pnl_pts <= trail_floor and best >= arm:
        return "scalp_trail_sl", pnl_inr

    if trail_floor is None and hold_seconds >= min_hold and pnl_pts <= -profile.stopPoints:
        return "simple_stop_loss", pnl_inr

    if settings.emergency_stop_enabled and pnl_inr <= -settings.emergency_stop_inr:
        return "simple_emergency_inr_stop", pnl_inr

    if pnl_pts >= profile.targetPoints:
        return "simple_profit_target_hit", pnl_inr

    micro_min_best = settings.scalp_micro_lock_min_best_points
    micro_min_hold = settings.scalp_min_hold_before_micro_lock_seconds
    if conf_tuning:
        micro_min_best = max(micro_min_best, conf_tuning.micro_min_best_points)
        micro_min_hold = max(micro_min_hold, conf_tuning.min_hold_before_micro_seconds)
    if psy_tuning:
        micro_min_best = max(micro_min_best, psy_tuning.micro_min_best_points)
        micro_min_hold = max(micro_min_hold, psy_tuning.min_hold_before_micro_seconds)

    micro_ready = (
        best >= micro_min_best
        or hold_seconds >= micro_min_hold
    )
    if micro_ready and pnl_pts >= profile.microTargetPoints:
        if best - pnl_pts >= micro_giveback:
            return "simple_micro_profit_lock", pnl_pts * trade.lots * lot_multiplier

    if trail_floor is None and best >= arm and pnl_pts < best * runner_keep:
        min_hold_before_trail = 0
        if conf_tuning:
            min_hold_before_trail = max(min_hold_before_trail, conf_tuning.min_hold_before_micro_seconds)
        if psy_tuning:
            min_hold_before_trail = max(min_hold_before_trail, psy_tuning.min_hold_before_micro_seconds)
        if hold_seconds >= min_hold_before_trail:
            return "simple_trail_profit_lock", pnl_pts * trade.lots * lot_multiplier

    if hold_seconds >= settings.scalp_no_progress_seconds and best <= 0:
        return "simple_no_progress_scratch", pnl_inr

    if hold_seconds >= profile.maxHoldSeconds:
        if pnl_pts > 0:
            return "simple_time_profit_lock", pnl_inr
        return "simple_time_stop", pnl_inr

    return None, pnl_inr
