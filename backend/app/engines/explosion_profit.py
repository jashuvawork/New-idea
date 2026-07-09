"""Explosion profit mode — ride premium explosions with trailing SL/TP while winning."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.capital_allocator import compute_lots
from app.engines.explosion_detector import ExplosionEvent
from app.models.schemas import Breadth, PaperTrade, Side, SpotChart, StrategyType, SuggestedTrade, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

# symbol -> last explosion stop timestamp (IST)
_explosion_stop_at: dict[str, datetime] = {}
_explosion_stop_cooldown_sec: dict[str, int] = {}


@dataclass
class ExplosionExitParams:
    stop_points: float
    target_points: float
    trail_arm_points: float
    trail_keep_ratio: float
    micro_target_points: float = 3.0
    adaptive_stop: bool = False  # per-trade plan — no fixed explosion_stop_loss


def default_explosion_exit_params(event_tier: str = "EXPLODING") -> ExplosionExitParams:
    settings = get_settings()
    return ExplosionExitParams(
        stop_points=settings.explosion_initial_stop_points,
        target_points=_target_points(event_tier),
        trail_arm_points=settings.explosion_trail_arm_points,
        trail_keep_ratio=settings.explosion_trail_keep_ratio,
        micro_target_points=3.0,
    )


def explosion_exit_params_from_plan(plan, event_tier: str = "EXPLODING") -> ExplosionExitParams:
    """Map adaptive exit plan onto explosion exit knobs — per-trade SL, no fixed stop."""
    base = default_explosion_exit_params(event_tier)
    return ExplosionExitParams(
        stop_points=plan.stopPoints or base.stop_points,
        target_points=plan.targetPoints or base.target_points,
        trail_arm_points=plan.trailArmPoints or base.trail_arm_points,
        trail_keep_ratio=plan.trailKeepRatio or base.trail_keep_ratio,
        micro_target_points=plan.microTargetPoints or base.micro_target_points,
        adaptive_stop=True,
    )


def record_explosion_stop(symbol: str, cooldown_seconds: Optional[int] = None) -> None:
    sym = symbol.upper()
    _explosion_stop_at[sym] = datetime.now(IST)
    if cooldown_seconds is not None:
        _explosion_stop_cooldown_sec[sym] = cooldown_seconds
    else:
        _explosion_stop_cooldown_sec.pop(sym, None)


def explosion_in_cooldown(symbol: str) -> bool:
    settings = get_settings()
    ts = _explosion_stop_at.get(symbol.upper())
    if not ts:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    elapsed = (datetime.now(IST) - ts.astimezone(IST)).total_seconds()
    cooldown = _explosion_stop_cooldown_sec.get(
        symbol.upper(),
        settings.explosion_reentry_cooldown_seconds,
    )
    return elapsed < cooldown


def cooldown_remaining_seconds(symbol: str) -> int:
    settings = get_settings()
    ts = _explosion_stop_at.get(symbol.upper())
    if not ts:
        return 0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    elapsed = (datetime.now(IST) - ts.astimezone(IST)).total_seconds()
    cooldown = _explosion_stop_cooldown_sec.get(
        symbol.upper(),
        settings.explosion_reentry_cooldown_seconds,
    )
    return max(0, int(cooldown - elapsed))


def check_explosion_entry(
    event: ExplosionEvent,
    trade: SuggestedTrade,
    breadth: Breadth,
    calibration_blocked: bool,
    *,
    index_moment: bool = False,
    chart: Optional[SpotChart] = None,
    snap: Optional[SymbolSnapshot] = None,
) -> tuple[bool, str]:
    """Fast entry on explosion — minimal gates, speed is everything."""
    if calibration_blocked:
        return False, "calibration_block"

    if snap is not None:
        from app.engines.morning_premium_capture import counter_trend_entry_allowed

        if not counter_trend_entry_allowed(event.side, snap, explosion_event=event):
            return False, "counter_trend_requires_elite"

    if snap is not None:
        from app.engines.expiry_day_guards import check_expiry_explosion_open_block

        blocked, reason = check_expiry_explosion_open_block(
            snap=snap,
            tier=event.tier,
            side=event.side,
            breadth=breadth,
        )
        if blocked:
            return False, reason

    if explosion_in_cooldown(event.symbol):
        return False, f"explosion_cooldown_{cooldown_remaining_seconds(event.symbol)}s"

    if event.tier not in ("EXPLODING", "ELITE"):
        from app.engines.morning_premium_capture import is_premium_capture_event

        if not is_premium_capture_event(event, chart=chart):
            return False, f"tier_{event.tier}_not_tradeable"

    from app.engines.morning_premium_capture import is_afternoon_capture_event

    if event.velocity_3s < 2.0 and event.velocity_9s < 3.0:
        open_move = float(getattr(event, "daily_move_pct", 0) or 0)
        open_min = float(getattr(get_settings(), "open_premium_min_move_pct", 25.0) or 25.0)
        if not is_afternoon_capture_event(event, chart=chart) and open_move < open_min:
            return False, "velocity_too_low"

    from app.engines.rally_capture import (
        breadth_blocks_explosion_side,
        chart_blocks_explosion_side,
        cross_side_chase_blocked,
        explosion_exhausted,
        index_pin_blocks_put_explosion,
    )
    from app.engines.morning_premium_capture import (
        afternoon_capture_skips_chart_block,
        is_all_day_explosion_event,
        is_premium_capture_event,
        premium_led_explosion_bypass,
    )

    breadth_bias = (breadth.bias or "NEUTRAL") if breadth else "NEUTRAL"
    premium_bypass = premium_led_explosion_bypass(event, chart, breadth_bias)

    blocked, reason = breadth_blocks_explosion_side(event.side, breadth.bias, event.tier)
    if blocked and not premium_bypass:
        return False, reason

    if snap is not None:
        blocked, reason = index_pin_blocks_put_explosion(event, snap)
        if blocked and not premium_bypass:
            return False, reason

    blocked, reason = chart_blocks_explosion_side(event.side, chart, event.tier)
    if blocked and not premium_bypass and not afternoon_capture_skips_chart_block(event, chart):
        if not is_all_day_explosion_event(event, chart=chart):
            return False, reason

    blocked, reason = explosion_exhausted(event)
    if blocked:
        return False, reason

    from app.engines.chop_day_guards import neutral_breadth_blocks_entry

    score = max(event.explosion_score, trade.tqs or 0, trade.confidence or 0)
    if snap is not None:
        from app.engines.expiry_day_guards import is_symbol_expiry_day

        if is_symbol_expiry_day(snap):
            label = str((snap.psychology or {}).get("label", "NEUTRAL")).upper()
            if label in ("CAUTION", "FEAR") and event.tier != "ELITE":
                return False, f"expiry_psychology_block_{label.lower()}"
            settings = get_settings()
            if (breadth.bias or "NEUTRAL").upper() == "NEUTRAL" and score < settings.expiry_min_rank_score:
                return False, f"expiry_neutral_breadth_below_{settings.expiry_min_rank_score:.0f}"
            from app.engines.symbol_cooldown import side_aligned_with_breadth

            if settings.expiry_counter_breadth_elite_only:
                side_val = event.side.value if hasattr(event.side, "value") else str(event.side).upper()
                if not side_aligned_with_breadth(side_val, breadth.bias) and event.tier != "ELITE":
                    if not (premium_bypass and event.tier in ("EXPLODING", "ELITE", "BUILDING")):
                        return False, "expiry_counter_breadth_elite_only"

    blocked, nb_reason = neutral_breadth_blocks_entry(
        breadth.bias,
        score,
        event.velocity_3s,
        explosion=True,
        volume_surge=event.volume_surge,
    )
    if blocked and not index_moment:
        return False, nb_reason

    from app.engines.chop_day_guards import in_momentum_rally_window

    if in_momentum_rally_window() and event.tier == "EXPLODING" and event.velocity_3s < 2.0:
        return False, "explosion_wait_velocity"

    from app.engines.spot_direction import chart_blocks_side

    expiry_chart_bypass = False
    if snap is not None:
        from app.engines.aligned_explosion_bypass import expiry_chart_bypass_for_event

        expiry_chart_bypass = expiry_chart_bypass_for_event(event, snap)

    blocked_chart, chart_reason = chart_blocks_side(
        event.side,
        chart,
        trade_score=score,
        momentum_surge=index_moment,
        premium_led_bypass=premium_bypass,
        expiry_explosion_bypass=expiry_chart_bypass,
    )
    if blocked_chart:
        return False, chart_reason

    if event.tier == "ELITE":
        return True, "elite_explosion" if not premium_bypass else "premium_led_elite_explosion"

    settings = get_settings()
    min_score = settings.aggressive_min_explosion_score
    open_move = float(getattr(event, "daily_move_pct", 0) or 0)
    if open_move >= settings.all_day_explosion_session_move_min_pct:
        min_score = min(min_score, settings.all_day_explosion_min_score)

    if event.tier == "EXPLODING" and event.explosion_score >= min_score:
        return True, "explosion_confirmed" if not premium_bypass else "premium_led_explosion_confirmed"

    if event.tier == "BUILDING" and event.explosion_score >= min_score:
        if is_all_day_explosion_event(event, chart=chart) or is_premium_capture_event(event, chart=chart):
            return True, "building_explosion_confirmed" if not premium_bypass else "premium_led_building_confirmed"

    if event.velocity_3s >= 3.0 and event.volume_surge >= 1.5:
        return True, "early_explosion"

    if is_premium_capture_event(event, chart=chart):
        return True, "premium_capture_confirmed"

    return False, "not_confirmed"


def compute_explosion_lots(event: ExplosionEvent, tqs: float, premium: float) -> int:
    """Size explosion trades at 85% capital max — same as compute_lots."""
    lots = compute_lots(
        event.symbol,
        premium,
        stop_points=get_settings().explosion_initial_stop_points,
        tqs=tqs,
        strategy_type=StrategyType.EXPLOSIVE,
        confidence=event.explosion_score,
        tier=event.tier,
    )
    return cap_explosion_lots(lots, premium)


def cap_explosion_lots(lots: int, premium: float) -> int:
    settings = get_settings()
    if premium > settings.explosion_high_premium_threshold_inr:
        return min(lots, settings.explosion_high_premium_lot_cap)
    if premium <= settings.expiry_cheap_premium_threshold_inr:
        return min(lots, settings.expiry_cheap_premium_lot_cap)
    return lots


def expiry_session_lot_cap(
    lots: int,
    premium: float,
    symbol_tqs: float,
    snapshots: dict[str, SymbolSnapshot],
) -> int:
    """Cap oversized lot counts on cheap premiums / low TQS during expiry sessions."""
    from app.engines.expiry_day_guards import is_expiry_session

    settings = get_settings()
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return lots
    if premium <= settings.expiry_cheap_premium_threshold_inr:
        lots = min(lots, settings.expiry_cheap_premium_lot_cap)
    if float(symbol_tqs or 0) < settings.expiry_low_tqs_lot_cap_tqs:
        lots = min(lots, settings.expiry_low_tqs_lot_cap)
    return lots


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


def _trail_floor_pts(
    trade: PaperTrade,
    best: float,
    settings,
    *,
    trail_arm_points: Optional[float] = None,
) -> Optional[float]:
    """Trailing floor in PnL points — arms only after minimum profit."""
    from app.engines.trail_engine import ratcheting_trail_floor

    arm = trail_arm_points if trail_arm_points is not None else settings.explosion_trail_arm_points
    return ratcheting_trail_floor(
        trade,
        best,
        arm_points=arm,
        keep_ratio=settings.explosion_trail_keep_ratio,
        step_points=settings.explosion_trail_step_points,
        tight_arm=settings.explosion_trail_tight_arm,
        tight_points=settings.explosion_trail_tight_points,
        floor_key="explosionTrailFloorPts",
        best_key="explosionBestPts",
    )


def _chart_aligned_with_trade(trade: PaperTrade) -> bool:
    """CALL+BULLISH or PUT+BEARISH — snapshot scan chart or entry execution chart."""
    from app.engines.bullish_hold import direction_aligned_with_breadth

    if direction_aligned_with_breadth(trade):
        return True
    ctx = trade.entryContext or {}
    exec_chart = (ctx.get("executionChart") or {}).get("indexChart") or {}
    snap_chart = (ctx.get("executionChart") or {}).get("snapshotChart") or {}
    for chart in (snap_chart, exec_chart):
        direction = str(chart.get("direction", "NEUTRAL")).upper()
        if trade.side == Side.CALL and direction == "BULLISH":
            return True
        if trade.side == Side.PUT and direction == "BEARISH":
            return True
    return False


def _should_skip_no_progress(trade: PaperTrade, settings) -> bool:
    """Bullish/directional holds can grind for minutes before premium expands."""
    if not settings.explosion_no_progress_enabled:
        return True
    if not settings.explosion_no_progress_skip_when_aligned:
        return False
    from app.engines.bullish_hold import direction_aligned_with_breadth

    if direction_aligned_with_breadth(trade) or _chart_aligned_with_trade(trade):
        return True
    ctx = trade.entryContext or {}
    edge = ctx.get("edgeScore") or {}
    if edge.get("letRunners"):
        return True
    return False


def _no_progress_limit_seconds(trade: PaperTrade, settings) -> int:
    """How long to wait before no-progress exit — longer on aligned bullish holds."""
    if not settings.explosion_no_progress_enabled:
        return 999_999
    from app.engines.bullish_hold import direction_aligned_with_breadth

    if direction_aligned_with_breadth(trade) or _chart_aligned_with_trade(trade):
        return settings.explosion_no_progress_aligned_seconds
    ctx = trade.entryContext or {}
    if float(ctx.get("selectionScore") or 0) >= 80:
        return int(settings.explosion_no_progress_seconds * 1.5)
    return settings.explosion_no_progress_seconds


def evaluate_explosion_exit(
    trade: PaperTrade,
    current_premium: float,
    event_tier: str = "EXPLODING",
    lot_multiplier: int = 25,
    params: Optional[ExplosionExitParams] = None,
) -> tuple[Optional[str], float]:
    """
    Explosion exits: hard SL when losing, trailing SL + TP while winning.
    Lets runners extend; locks profit as peak builds.
    """
    settings = get_settings()
    exit_params = params or default_explosion_exit_params(event_tier)
    pnl_pts = current_premium - trade.entryPremium
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    best = max(trade.bestPnlPoints, pnl_pts)
    hold = _hold_seconds(trade)
    target = exit_params.target_points
    trail_floor = _trail_floor_pts(
        trade, best, settings, trail_arm_points=exit_params.trail_arm_points,
    )
    trail_keep = (
        settings.runner_trail_keep_ratio
        if best >= settings.runner_min_best_points
        else exit_params.trail_keep_ratio
    )

    if (
        not exit_params.adaptive_stop
        and trail_floor is None
        and hold >= settings.explosion_stop_min_hold_seconds
        and pnl_pts <= -exit_params.stop_points
    ):
        return "explosion_stop_loss", pnl_inr

    if settings.emergency_stop_enabled and pnl_inr <= -settings.emergency_stop_inr:
        return "explosion_emergency_stop", pnl_inr

    if pnl_pts >= target:
        return "explosion_target_hit", pnl_inr

    if trail_floor is not None and pnl_pts <= trail_floor and best >= exit_params.trail_arm_points:
        return "explosion_trail_sl", pnl_inr

    if trail_floor is not None and pnl_pts < best * trail_keep and best >= 8:
        return "explosion_trail_lock", pnl_inr

    if (
        pnl_pts >= exit_params.micro_target_points
        and best - pnl_pts >= settings.runner_micro_giveback_points
        and best >= settings.runner_min_best_points
    ):
        return "explosion_micro_profit_lock", pnl_inr

    if (
        exit_params.adaptive_stop
        and hold >= settings.explosion_stop_min_hold_seconds
        and pnl_pts <= -exit_params.stop_points
    ):
        return "adaptive_stop_loss", pnl_inr

    if _should_skip_no_progress(trade, settings):
        pass
    elif hold >= _no_progress_limit_seconds(trade, settings) and best < exit_params.trail_arm_points:
        return "explosion_no_progress", pnl_inr

    max_hold = 420 if best >= settings.runner_min_best_points else (360 if event_tier == "ELITE" or best >= 15 else 300)
    ctx = trade.entryContext or {}
    if ctx.get("afternoonCapture"):
        max_hold = max(max_hold, settings.afternoon_capture_exit_max_hold_seconds)
    if aligned := ctx.get("breadth"):
        side_bias = "BULLISH" if trade.side.value == "CALL" else "BEARISH"
        if str(aligned).upper() == side_bias:
            max_hold = int(max_hold * 1.4)
    if hold >= max_hold:
        return ("explosion_time_profit" if pnl_pts > 0 else "explosion_time_stop"), pnl_inr

    return None, pnl_inr
