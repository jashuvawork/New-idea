"""Explosion profit mode — ride premium explosions with trailing SL/TP while winning."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.capital_allocator import compute_lots
from app.engines.explosion_detector import ExplosionEvent
from app.models.schemas import Breadth, PaperTrade, Side, SpotChart, StrategyType, SuggestedTrade, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _cfg_float(settings, name: str, default: float) -> float:
    """Float setting with MagicMock-safe fallback (tests often stub settings)."""
    v = getattr(settings, name, default)
    if isinstance(v, bool) or v is None:
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return float(default)
    return float(default)


def _ict_flat_vertical_entry_ok(
    event: ExplosionEvent,
    snap: Optional[SymbolSnapshot],
) -> bool:
    """ICT flat→vertical entry, including a strictly confirmed first lift.

    EXPLODING/ELITE keep the structure+heat path. BUILDING must clear elite-build
    bars so Aug7-style cold prints wait. A WATCH/BUILDING first lift may precede
    the chart-direction flip only when quality, sustained heat, volume and the
    live momentum turn all pass ``first_lift_entry_ready``.
    """
    if event is None or snap is None:
        return False
    tier_u = str(getattr(event, "tier", "") or "").upper()
    from app.engines.ict_breakout_monitor import (
        analyze_explosion_event_ict,
        first_lift_entry_ready,
    )
    from app.engines.spot_direction import side_aligned_with_chart

    ict = analyze_explosion_event_ict(event, snap)
    first_lift_ready = first_lift_entry_ready(
        snap=snap,
        event=event,
        ict=ict,
    )
    chart = getattr(snap, "spotChart", None)
    if (
        chart is not None
        and not side_aligned_with_chart(event.side, chart)
        and not first_lift_ready
    ):
        return False
    if not bool(getattr(ict, "active", False)):
        return False
    if not bool(getattr(ict, "flat_then_vertical", False)):
        return False
    heat = bool(
        getattr(ict, "volume_awakening", False)
        or getattr(ict, "displacement", False)
        or getattr(ict, "premium_fvg", False)
    )
    if not heat:
        return False
    # A high-quality first lift is deliberately earlier than BUILDING/Ichimoku.
    # Its live momentum-turn and volume proof replace those lagging confirmations.
    if first_lift_ready:
        return True
    if tier_u not in ("BUILDING", "EXPLODING", "ELITE"):
        return False
    settings = get_settings()
    if tier_u == "BUILDING":
        if not bool(getattr(settings, "explosion_building_aligned_ict_enabled", True)):
            return False
        min_score = float(getattr(settings, "explosion_building_elite_min_score", 62.0) or 62.0)
        if float(getattr(event, "explosion_score", 0) or 0) < min_score:
            return False
        min_v3 = float(
            getattr(settings, "explosion_building_elite_min_velocity_3s", 2.5) or 2.5
        )
        if float(getattr(event, "velocity_3s", 0) or 0) < min_v3:
            return False
        # Sustained heat — Aug10 CE spiked v3 then cooled (v9≈0).
        min_v9 = float(
            getattr(settings, "explosion_building_elite_min_velocity_9s", 2.5) or 2.5
        )
        if float(getattr(event, "velocity_9s", 0) or 0) < min_v9:
            return False
        min_ict = float(getattr(settings, "explosion_building_elite_min_ict_score", 35.0) or 35.0)
        if float(getattr(ict, "score", 0) or 0) < min_ict:
            return False
    # GainzAlgo-style break-P confirm — reject shallow/fake cloud exits.
    from app.engines.smart_ichimoku import ichimoku_break_supports_side

    ok, _reason = ichimoku_break_supports_side(event.side, snap, require_confirmed=True)
    return ok


def _is_base_rip_runner_trade(trade: PaperTrade) -> bool:
    """High-conviction / ICT flat→vertical / max-profit — deserve never-green grace."""
    ctx = trade.entryContext or {}
    if ctx.get("highConviction") or ctx.get("ictFlatThenVertical") or ctx.get("maxProfitCapture"):
        return True
    try:
        from app.engines.explosion_confidence import trade_is_high_conviction
        from app.engines.ict_breakout_monitor import _ict_max_profit_trade

        if trade_is_high_conviction(trade) or _ict_max_profit_trade(trade):
            return True
    except Exception:
        pass
    return False


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
        int(_cfg_float(settings, "explosion_reentry_cooldown_seconds", 90)),
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
        int(_cfg_float(settings, "explosion_reentry_cooldown_seconds", 90)),
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

    from app.engines.extreme_explosion_moment import is_extreme_explosion_all_in_bypass

    if is_extreme_explosion_all_in_bypass(event=event):
        if explosion_in_cooldown(event.symbol):
            return False, f"explosion_cooldown_{cooldown_remaining_seconds(event.symbol)}s"
        return True, "extreme_all_in_explosion_confirmed"

    # Require chart align — but honor the same capture/structure bypasses as
    # chart_blocks_explosion_side later (afternoon / all-day / premium-led / local-base).
    settings = get_settings()
    early_ict_ok = _ict_flat_vertical_entry_ok(event, snap)
    if bool(getattr(settings, "explosion_require_chart_align_enabled", True)):
        from app.engines.spot_direction import side_aligned_with_chart

        align_chart = chart or (getattr(snap, "spotChart", None) if snap is not None else None)
        if align_chart is not None and not side_aligned_with_chart(event.side, align_chart):
            from app.engines.local_base_chart_bypass import local_base_ichimoku_chart_bypass
            from app.engines.morning_premium_capture import (
                afternoon_capture_skips_chart_block,
                is_all_day_explosion_event,
                premium_led_explosion_bypass,
            )

            breadth_bias = (breadth.bias or "NEUTRAL") if breadth else "NEUTRAL"
            premium_bypass = premium_led_explosion_bypass(
                event, align_chart, breadth_bias, snap=snap,
            )
            local_ichi_bypass = (
                local_base_ichimoku_chart_bypass(event.side, snap, event=event)
                if snap is not None
                else False
            )
            if not (
                premium_bypass
                or local_ichi_bypass
                or early_ict_ok
                or afternoon_capture_skips_chart_block(event, align_chart)
                or is_all_day_explosion_event(event, chart=align_chart)
            ):
                return False, "explosion_requires_chart_align"

    if snap is not None:
        from app.engines.aligned_side_guard import breadth_hard_blocks_side
        from app.engines.morning_premium_capture import counter_trend_entry_allowed

        bias = (snap.breadth.bias if snap.breadth else breadth.bias or "NEUTRAL") or "NEUTRAL"
        hard_blocked, hard_reason = breadth_hard_blocks_side(
            event.side, bias, event=event, snap=snap,
        )
        if hard_blocked:
            return False, hard_reason
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

        if is_premium_capture_event(event, chart=chart):
            pass  # premium-capture BUILDING continues through remaining gates
        elif early_ict_ok:
            pass  # confirmed first-lift or elite-build ICT flat→vertical
        else:
            return False, f"tier_{event.tier}_not_tradeable"

    from app.engines.morning_premium_capture import is_afternoon_capture_event

    if (
        not early_ict_ok
        and event.velocity_3s < 2.0
        and event.velocity_9s < 3.0
    ):
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
    from app.engines.aligned_side_guard import breadth_hard_blocks_side

    hard_blocked, hard_reason = breadth_hard_blocks_side(
        event.side, breadth_bias, event=event, snap=snap,
    )
    if hard_blocked:
        return False, hard_reason

    premium_bypass = premium_led_explosion_bypass(event, chart, breadth_bias, snap=snap)

    blocked, reason = breadth_blocks_explosion_side(
        event.side, breadth.bias, event.tier, event=event, snap=snap,
    )
    if blocked and not premium_bypass:
        return False, reason

    if snap is not None:
        blocked, reason = index_pin_blocks_put_explosion(event, snap)
        if blocked and not premium_bypass:
            return False, reason

    from app.engines.local_base_chart_bypass import local_base_ichimoku_chart_bypass

    local_ichi_bypass = local_base_ichimoku_chart_bypass(
        event.side, snap, event=event,
    )
    blocked, reason = chart_blocks_explosion_side(
        event.side, chart, event.tier, event=event, breadth_bias=breadth_bias, snap=snap,
    )
    if (
        blocked
        and not premium_bypass
        and not local_ichi_bypass
        and not early_ict_ok
        and not afternoon_capture_skips_chart_block(event, chart)
    ):
        if not is_all_day_explosion_event(event, chart=chart):
            return False, reason

    blocked, reason = explosion_exhausted(event)
    if blocked:
        return False, reason

    from app.engines.explosion_entry_guards import (
        explosion_entry_window_blocked,
        live_explosion_confirmation_blocked,
    )
    from app.engines.ict_breakout_monitor import (
        analyze_explosion_event_ict,
        first_lift_entry_ready,
    )

    # Analyze from event even when snap is missing — event carries move/velocity/tier
    # needed for ICT structure. Skipping analyze when snap is None falsely blocked
    # BUILDING+ICT flat→vertical entries (no structure → no_ict_structure_confirmation).
    ict_live = analyze_explosion_event_ict(event, snap)
    first_lift_ready = first_lift_entry_ready(
        snap=snap,
        event=event,
        ict=ict_live,
    )
    from app.engines.elite_never_block import elite_never_block_active

    must_take = elite_never_block_active(
        event=event, snap=snap, ict=ict_live,
    )
    # Flat→vertical ELITE/EXPLODING/BUILDING — require GainzAlgo-style break-P.
    if (
        bool(getattr(ict_live, "flat_then_vertical", False))
        and not first_lift_ready
    ):
        from app.engines.smart_ichimoku import ichimoku_break_supports_side

        ichi_ok, ichi_reason = ichimoku_break_supports_side(
            event.side, snap, require_confirmed=True,
        )
        if not ichi_ok:
            return False, ichi_reason
    from app.engines.advanced_indicators import squeeze_early_base_active
    from app.engines.bullish_local_base import bullish_local_base_prediction

    bullish_base = bullish_local_base_prediction(snap, event, ict_live)

    window_blocked, window_reason = explosion_entry_window_blocked(
        event, ict=ict_live, top_must_take=must_take,
        squeeze_early_base=squeeze_early_base_active(event, snap),
        bullish_local_base=bool(bullish_base.get("active")),
    )
    if window_blocked and not first_lift_ready:
        return False, window_reason
    live_blocked, live_reason = live_explosion_confirmation_blocked(
        event,
        ict=ict_live,
        premium_capture=is_premium_capture_event(event, chart=chart),
        snap=snap,
    )
    if live_blocked and not must_take:
        return False, live_reason

    from app.engines.entry_timing import assess_entry_timing, timing_blocks_entry

    timing = assess_entry_timing(
        event,
        ict=ict_live,
        snap=snap,
        premium_capture=is_premium_capture_event(event, chart=chart),
    )
    timing_blocked, timing_reason = timing_blocks_entry(timing)
    if (
        timing_blocked
        and not must_take
        and not (
            first_lift_ready
            and bool(
                getattr(
                    settings,
                    "first_lift_bypasses_cold_timing_enabled",
                    True,
                )
            )
        )
    ):
        return False, timing_reason

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

    # The strict first-lift proof already requires a measured 15–25% local pad,
    # quality, sustained premium heat, volume and a live side-specific index turn.
    # Do not wait for neutral breadth, a lagging cloud/chart flip or a 2% velocity
    # threshold after those stronger early facts have passed. Expiry safety above,
    # chase/window, live confirmation and cooldown checks still apply.
    if first_lift_ready:
        return True, "first_lift_local_base_confirmed"

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

    afternoon_chart_skip = afternoon_capture_skips_chart_block(event, chart)
    all_day_capture = is_all_day_explosion_event(event, chart=chart)

    blocked_chart, chart_reason = chart_blocks_side(
        event.side,
        chart,
        trade_score=score,
        momentum_surge=index_moment,
        premium_led_bypass=premium_bypass or afternoon_chart_skip or all_day_capture,
        expiry_explosion_bypass=expiry_chart_bypass,
    )
    # Aug6 hard-counter-trend may ignore premium_led_bypass inside chart_blocks_side;
    # still allow intentional afternoon / all-day / premium-led capture paths here.
    if (
        blocked_chart
        and not afternoon_chart_skip
        and not premium_bypass
        and not all_day_capture
        and not first_lift_ready
    ):
        return False, chart_reason

    if event.tier == "ELITE":
        return True, "elite_explosion" if not premium_bypass else "premium_led_elite_explosion"

    settings = get_settings()
    min_score = settings.aggressive_min_explosion_score
    open_move = float(getattr(event, "daily_move_pct", 0) or 0)
    session_move_min = _cfg_float(settings, "all_day_explosion_session_move_min_pct", 40.0)
    if open_move >= session_move_min:
        min_score = min(min_score, _cfg_float(settings, "all_day_explosion_min_score", 38.0))

    if event.tier == "EXPLODING" and event.explosion_score >= min_score:
        return True, "explosion_confirmed" if not premium_bypass else "premium_led_explosion_confirmed"

    if event.tier == "BUILDING" and event.explosion_score >= min_score:
        ict_flat_ok = _ict_flat_vertical_entry_ok(event, snap)
        if (
            is_all_day_explosion_event(event, chart=chart)
            or is_premium_capture_event(event, chart=chart)
            or ict_flat_ok
        ):
            return True, (
                "ict_building_flat_vertical"
                if ict_flat_ok
                else ("building_explosion_confirmed" if not premium_bypass else "premium_led_building_confirmed")
            )

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
    keep_ratio_override: Optional[float] = None,
) -> Optional[float]:
    """Trailing floor in PnL points — arms only after minimum profit."""
    from app.engines.trail_engine import ratcheting_trail_floor

    from app.engines.ict_breakout_monitor import ict_trail_arm_multiplier

    arm = trail_arm_points if trail_arm_points is not None else _cfg_float(settings, "explosion_trail_arm_points", 10.0)
    arm *= ict_trail_arm_multiplier(trade)
    keep_ratio = (
        keep_ratio_override
        if keep_ratio_override is not None
        else _cfg_float(settings, "explosion_trail_keep_ratio", 0.65)
    )
    return ratcheting_trail_floor(
        trade,
        best,
        arm_points=arm,
        keep_ratio=keep_ratio,
        step_points=_cfg_float(settings, "explosion_trail_step_points", 2.0),
        tight_arm=_cfg_float(settings, "explosion_trail_tight_arm", 999.0),
        tight_points=_cfg_float(settings, "explosion_trail_tight_points", 0.0),
        floor_key="explosionTrailFloorPts",
        best_key="explosionBestPts",
    )


def _defer_explosion_trail_while_continuing(
    trade: PaperTrade,
    *,
    best: float,
    pnl_pts: float,
    live_v: float,
    projected_max: float,
    stage_ladder: bool,
    max_profit: bool,
    settings,
) -> bool:
    """Hold through a green trail tick while the vertical is still expanding.

    Never defer into/through a loss. Near the projected ceiling, allow the trail
    to bank. Peak-capture / hard SL still cut dying moves when heat dies.
    """
    if pnl_pts <= 0:
        return False
    if not bool(getattr(settings, "explosion_trail_hot_defer_enabled", True)):
        return False
    if not (stage_ladder or max_profit):
        return False
    hot_min = _cfg_float(settings, "moment_stage_hot_hold_velocity_3s", 2.5)
    if live_v < hot_min:
        return False
    if projected_max > 0:
        frac = _cfg_float(settings, "moment_stage_extend_trigger_frac", 0.92)
        if best >= projected_max * frac:
            return False
    return True


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
    if ctx.get("extremeAllInBypass"):
        return True
    from app.engines.explosion_entry_guards import is_faded_rip_caution_trade

    if is_faded_rip_caution_trade(trade):
        return False
    if (
        ctx.get("ictFirstLift")
        or ctx.get("firstLiftCapture")
        or ctx.get("ictMegaRip")
        or ctx.get("goodDayIctCapture")
        or ctx.get("allDayIctCapture")
        or ctx.get("maxProfitCapture")
        or ctx.get("ictFlatThenVertical")
        or ctx.get("defensiveBaseRip")
    ):
        return True
    edge = ctx.get("edgeScore") or {}
    if edge.get("letRunners"):
        return True
    return False


def _adaptive_stop_min_hold(trade: PaperTrade, settings) -> int:
    """Minimum hold before adaptive SL — longer when chart/breadth support the trade."""
    from app.engines.confidence_hold import chart_confidence_for_trade, is_confidence_runner_hold

    base = settings.explosion_stop_min_hold_seconds
    elevated = _cfg_float(settings, "chart_confidence_elevated_threshold", 56.9)
    if is_confidence_runner_hold(trade):
        conf = chart_confidence_for_trade(trade)
        if conf >= elevated:
            return max(base, 90)
        return max(base, 60)

    chart_conf = chart_confidence_for_trade(trade)
    from app.engines.bullish_hold import direction_aligned_with_breadth

    min_conf = _cfg_float(settings, "all_day_min_chart_confidence", 48.2)
    if direction_aligned_with_breadth(trade) and chart_conf >= min_conf:
        return max(base, 45)
    if chart_conf >= elevated:
        return max(base, 35)
    return base


def _effective_stop_points(trade: PaperTrade, stop_points: float) -> float:
    """Chart-tuned SL from exit plan.

    Confidence may widen thin legacy stops, but must NOT stack multipliers on top
    of an already-calculated local-support / natural SL (Jul30 77700: 40×1.4→56).
    Entry stop is always the hard ceiling.
    """
    from app.engines.confidence_hold import (
        chart_confidence_for_trade,
        confidence_hold_stop_multiplier,
    )

    settings = get_settings()
    ctx = trade.entryContext or {}
    plan = ctx.get("exitPlan") or {}
    plan_stop = float(plan.get("stopPoints") or 0)
    entry_stop = float(plan.get("entryStopPoints") or 0)
    natural = float(plan.get("naturalStopPoints") or plan.get("localSupportStopPoints") or 0)
    base = plan_stop if plan_stop > 0 else stop_points

    # Already at calculated support/natural — do not widen further with conf mult.
    calculated = natural > 0 or bool(plan.get("localSupportStopPoints"))
    if calculated:
        capped = base
        if entry_stop > 0:
            capped = min(capped, entry_stop)
        return round(max(0.0, capped), 2)

    mult = confidence_hold_stop_multiplier(trade)
    conf = chart_confidence_for_trade(trade)
    elevated = _cfg_float(settings, "chart_confidence_elevated_threshold", 56.9)
    if conf >= elevated:
        mult = max(mult, 1.4)
    elif conf >= _cfg_float(settings, "all_day_min_chart_confidence", 48.2):
        mult = max(mult, 1.2)
    widened = base * mult
    if entry_stop > 0:
        widened = min(widened, entry_stop)
    return round(widened, 2)


def _defer_adaptive_stop(
    trade: PaperTrade,
    best: float,
    hold: float,
    settings,
    *,
    pnl_pts: float = 0.0,
    stop_floor: float = 0.0,
) -> bool:
    """Defer adaptive SL while high-confidence trade works toward chart TP."""
    # Base-rip runners get a short never-green grace with a wider floor so a
    # brief dip after entry (Jul23 76300 PE) does not kill the rip at best=0.
    runner = _is_base_rip_runner_trade(trade)
    grace_s = _cfg_float(settings, "base_rip_never_green_grace_seconds", 150.0)
    grace_mult = _cfg_float(settings, "base_rip_never_green_stop_mult", 2.0)
    hard_floor = float(stop_floor or 0)
    if runner and best <= 0 and hold < grace_s and hard_floor > 0:
        hard_floor = hard_floor * grace_mult

    if hard_floor > 0 and pnl_pts <= -hard_floor:
        return False
    # Never defer a never-green loser — except ICT/HC base-rip grace above.
    if best <= 0 and pnl_pts < 0:
        if runner and hold < grace_s:
            return True
        return False
    from app.engines.confidence_hold import (
        hold_until_target_active,
        is_confidence_runner_hold,
        chart_confidence_for_trade,
    )
    from app.engines.bullish_hold import direction_aligned_with_breadth
    from app.engines.explosion_entry_guards import is_faded_rip_caution_trade

    if is_faded_rip_caution_trade(trade):
        return False

    if hold_until_target_active(trade, best):
        return True

    if not is_confidence_runner_hold(trade):
        chart_conf = chart_confidence_for_trade(trade)
        if not direction_aligned_with_breadth(trade):
            return False
        if chart_conf < _cfg_float(settings, "all_day_min_chart_confidence", 48.2):
            return False
        if best < 5.0 and hold < 60:
            return True
        if best < 3.0 and hold < 45:
            return True
    return False


def _no_progress_limit_seconds(trade: PaperTrade, settings) -> int:
    """How long to wait before no-progress exit — longer on aligned bullish holds."""
    if not settings.explosion_no_progress_enabled:
        return 999_999
    from app.engines.bullish_hold import direction_aligned_with_breadth
    from app.engines.ict_breakout_monitor import ict_no_progress_seconds

    ict_limit = ict_no_progress_seconds(trade, settings)
    if ict_limit != settings.explosion_no_progress_seconds:
        return ict_limit
    if direction_aligned_with_breadth(trade) or _chart_aligned_with_trade(trade):
        return settings.explosion_no_progress_aligned_seconds
    ctx = trade.entryContext or {}
    if float(ctx.get("selectionScore") or 0) >= 80:
        return int(settings.explosion_no_progress_seconds * 1.5)
    return settings.explosion_no_progress_seconds


def _peak_fade_bullish_continuation(
    trade: PaperTrade,
    *,
    pnl_pts: float,
    settings: Any,
) -> bool:
    """True when live analysis still supports holding a healthy pullback.

    Chart/breadth bullish alone is NOT enough — options often die while the
    index chart stays bullish. Require aligned direction + live heat, and that
    we still have meaningful remaining green (not almost back to entry).
    """
    if not getattr(settings, "explosion_peak_fade_defer_when_bullish", True):
        return False
    min_remain = float(
        getattr(settings, "explosion_peak_fade_bullish_min_remain_points", 3.0) or 3.0
    )
    if pnl_pts < min_remain:
        return False

    from app.engines.bullish_hold import direction_aligned_with_breadth

    aligned = direction_aligned_with_breadth(trade) or _chart_aligned_with_trade(trade)
    if not aligned:
        return False

    ctx = trade.entryContext or {}
    # Live premium velocity if present on context; else treat as not hot.
    live_v3 = float(
        ctx.get("liveVelocity3s")
        or ctx.get("velocity3s")
        or ctx.get("entryVelocity3s")
        or 0
    )
    # Prefer freshest chart premium momentum when execution chart is attached.
    exec_chart = ctx.get("executionChart") or {}
    prem_chart = exec_chart.get("premiumChart") or ctx.get("premiumChart") or {}
    try:
        mom = float(prem_chart.get("momentum3Pct") or prem_chart.get("momentum5Pct") or 0)
    except (TypeError, ValueError):
        mom = 0.0
    min_v3 = float(
        getattr(settings, "explosion_peak_fade_bullish_min_velocity_3s", 1.5) or 1.5
    )
    # Still expanding / not dead → allow bullish pullback hold.
    return live_v3 >= min_v3 or mom >= 0.8


def _live_premium_heat(trade: PaperTrade, *, live_velocity_3s: float = 0.0) -> tuple[float, float]:
    """Return (live_v3, premium_mom_pct) for rollover detection."""
    ctx = trade.entryContext or {}
    live_v3 = float(
        live_velocity_3s
        or ctx.get("liveVelocity3s")
        or ctx.get("velocity3s")
        or 0
    )
    exec_chart = ctx.get("executionChart") or {}
    prem_chart = exec_chart.get("premiumChart") or ctx.get("premiumChart") or {}
    try:
        mom = float(prem_chart.get("momentum3Pct") or prem_chart.get("momentum5Pct") or 0)
    except (TypeError, ValueError):
        mom = 0.0
    return live_v3, mom


def _premium_rolling_over(
    trade: PaperTrade,
    *,
    settings: Any,
    live_velocity_3s: float = 0.0,
) -> bool:
    """True when live premium heat is dying — safe to capture near the peak.

    Hot velocity vetoes capture so still-expanding rips are not forced out.
    Cold velocity + flat/negative mom confirms rollover.
    """
    live_v3, mom = _live_premium_heat(trade, live_velocity_3s=live_velocity_3s)
    max_v3 = float(
        getattr(settings, "explosion_peak_capture_max_live_velocity_3s", 1.0) or 1.0
    )
    max_mom = float(
        getattr(settings, "explosion_peak_capture_max_premium_mom_pct", 0.15) or 0.15
    )
    if live_v3 > max_v3:
        return False
    return mom <= max_mom


def _near_base_top_runner(trade: PaperTrade) -> bool:
    """True when this trade entered very near its local base on a top tier — the base
    rip is still ahead, so soft profit-locks should wait for a bigger peak."""
    settings = get_settings()
    if not getattr(settings, "explosion_near_base_hold_enabled", True):
        return False
    ctx = trade.entryContext or {}
    rel = ctx.get("localBaseBaseRelPct")
    if rel is None:
        return False
    try:
        rel = float(rel)
    except (TypeError, ValueError):
        return False
    max_rel = float(
        getattr(settings, "explosion_near_base_hold_max_entry_rel_pct", 20.0) or 20.0
    )
    # ICT flat→vertical / max-profit: hold further into the pad toward max TP.
    ict_max = bool(
        ctx.get("ictFirstLift")
        or ctx.get("firstLiftCapture")
        or ctx.get("ictFlatThenVertical")
        or ctx.get("maxProfitCapture")
        or ctx.get("defensiveBaseRip")
    )
    if ict_max:
        max_rel = max(
            max_rel,
            float(
                getattr(settings, "explosion_near_base_hold_ict_max_entry_rel_pct", 40.0)
                or 40.0
            ),
        )
    if rel <= 0 or rel > max_rel:
        return False
    # True protective psychology overrides the hold. OVERCONFIDENCE must NOT —
    # it often prints on strong ICT winners and was disabling the hold on Aug6
    # SENSEX 78700 CE (14.5% off base → soft-locked +6.5 before LTP 460).
    psych = str(ctx.get("psychologyLabel") or ctx.get("psychology") or "").upper()
    if psych in ("CAUTION", "FEAR") or str(
        ctx.get("psychologyExitBias") or ""
    ).upper() in ("PROTECT", "TIGHT_STOPS"):
        return False
    tier = str(ctx.get("explosionTier") or ctx.get("tier") or "").upper()
    if tier in ("ELITE", "EXPLODING") or ict_max:
        return True
    from app.engines.explosion_confidence import trade_is_high_conviction

    return bool(trade_is_high_conviction(trade))


def _near_base_hold_min_best(
    trade: PaperTrade,
    base_min_best: float,
    *,
    max_profit: bool = False,
) -> float:
    """Raise the soft-lock min-best for a near-base top runner so a small early peak
    doesn't book before the base rip develops."""
    if not _near_base_top_runner(trade):
        return base_min_best
    settings = get_settings()
    hold_min = float(
        getattr(settings, "explosion_near_base_hold_min_best_points", 40.0) or 40.0
    )
    if max_profit:
        hold_min = max(
            hold_min,
            float(
                getattr(
                    settings,
                    "explosion_near_base_hold_max_profit_min_best_points",
                    55.0,
                )
                or 55.0
            ),
        )
    return max(base_min_best, hold_min)


def peak_capture_profit_lock_reason(
    trade: PaperTrade,
    *,
    best: float,
    pnl_pts: float,
    max_profit: bool = False,
    live_velocity_3s: float = 0.0,
) -> Optional[str]:
    """Bank near the peak once a real top prints and premium starts rolling over.

    Unlike deep peak-fade (55% giveback), this keeps ~75–80% of the peak when
    analysis shows the move is dying — e.g. best +12 → exit around +9.
    Still-rising heat (hot velocity / positive mom) skips capture so runners extend.
    """
    settings = get_settings()
    if not getattr(settings, "explosion_peak_capture_enabled", True):
        return None

    min_best = float(
        getattr(settings, "explosion_peak_capture_min_best_points", 8.0) or 8.0
    )
    giveback_ratio = float(
        getattr(settings, "explosion_peak_capture_giveback_ratio", 0.22) or 0.22
    )
    if max_profit:
        min_best = max(
            min_best,
            float(
                getattr(settings, "explosion_peak_capture_max_profit_min_best", 28.0)
                or 28.0
            ),
        )
        giveback_ratio = max(
            giveback_ratio,
            float(
                getattr(
                    settings, "explosion_peak_capture_max_profit_giveback_ratio", 0.35
                )
                or 0.35
            ),
        )

    ctx = trade.entryContext or {}
    # Psychology tighten is for normal trades only — never shrink ICT max-profit
    # capture band (Aug6 78700 CE OVERCONFIDENCE forced an early bank).
    if not max_profit:
        psych = str(
            ctx.get("psychologyLabel")
            or ctx.get("psychology")
            or ((ctx.get("exitPlan") or {}).get("psychologyLabel"))
            or ""
        ).upper()
        if psych in ("CAUTION", "FEAR", "OVERCONFIDENCE") or str(
            ctx.get("psychologyExitBias") or ""
        ).upper() in ("PROTECT", "TIGHT_STOPS"):
            min_best = max(6.0, min_best * 0.85)
            giveback_ratio = min(giveback_ratio, 0.18)

    # Large confirmed-rollover peak → bank near the top. Ordinary trades tighten at
    # +25pt (6% giveback). Max-profit FTV / local-base winners wait for a true
    # expansion peak (≥80pt) so 100%+ rips are not clipped on a mid-leg dip.
    if max_profit:
        big_peak = float(
            getattr(
                settings,
                "explosion_peak_capture_max_profit_big_peak_points",
                80.0,
            )
            or 80.0
        )
        big_peak_ratio = float(
            getattr(
                settings,
                "explosion_peak_capture_max_profit_big_peak_giveback_ratio",
                0.28,
            )
            or 0.28
        )
    else:
        big_peak = float(
            getattr(settings, "explosion_peak_capture_big_peak_points", 25.0) or 25.0
        )
        big_peak_ratio = float(
            getattr(settings, "explosion_peak_capture_big_peak_giveback_ratio", 0.22)
            or 0.22
        )
    if big_peak > 0 and best >= big_peak:
        giveback_ratio = min(giveback_ratio, big_peak_ratio)

    # Near-base top runner → hold for a bigger peak before capturing (base rip ahead).
    min_best = _near_base_hold_min_best(trade, min_best, max_profit=max_profit)

    if best < min_best:
        return None

    giveback = best - pnl_pts
    min_give = float(
        getattr(settings, "explosion_peak_capture_min_giveback_points", 2.0) or 2.0
    )
    max_give = _cfg_float(settings, "explosion_peak_capture_max_giveback_points", 8.0)
    if max_profit:
        # Mid-leg FTV (< big-peak threshold): ratio-only — an 8pt dip must not bank
        # before 100%+. After a true expansion peak, allow a higher absolute ceiling
        # so confirmed rollovers still bank near the top without waiting a full 28%.
        mp_big = float(
            getattr(
                settings,
                "explosion_peak_capture_max_profit_big_peak_points",
                80.0,
            )
            or 80.0
        )
        if best < mp_big:
            max_give = 0.0
        else:
            max_give = _cfg_float(
                settings,
                "explosion_peak_capture_max_profit_max_giveback_points",
                24.0,
            )
    min_remain = float(
        getattr(settings, "explosion_peak_capture_min_remain_points", 1.0) or 1.0
    )
    if pnl_pts < min_remain:
        return None
    ratio_giveback = best * giveback_ratio
    required_giveback = max(
        min_give,
        min(ratio_giveback, max_give) if max_give > 0 else ratio_giveback,
    )
    if giveback < required_giveback:
        return None
    # Only capture when the tape shows rollover — not on a still-expanding rip.
    if not _premium_rolling_over(
        trade, settings=settings, live_velocity_3s=live_velocity_3s,
    ):
        return None
    return "explosion_peak_capture"


def peak_fade_profit_lock_reason(
    trade: PaperTrade,
    *,
    best: float,
    pnl_pts: float,
    max_profit: bool = False,
    live_velocity_3s: float = 0.0,
) -> Optional[str]:
    """Book remaining profit (or scratch near BE) when a peaked trade is fading to losses.

    Trail only arms after a high peak (often 20pt+). Jul31 NIFTY 24500 CE peaked
    +12.5pt then faded toward red with trail still unarmed — this closes that hole
    without forcing tiny early TPs on still-rising rips.

    Order: peak-capture (near top) → breakeven protect → deep fade lock.
    Bullish continuation can defer the deep soft lock only.
    """
    settings = get_settings()

    # Even an FTV runner loses its free option once a small winner fully rolls over.
    # This acts only near breakeven with non-positive live velocity, so a normal
    # pullback that remains green or is already reaccelerating keeps running.
    if bool(getattr(settings, "explosion_early_green_lock_enabled", True)):
        early_min_best = _cfg_float(
            settings, "explosion_early_green_lock_min_best_points", 3.5
        )
        early_buffer = _cfg_float(
            settings, "explosion_early_green_lock_buffer_points", 0.5
        )
        early_max_v = _cfg_float(
            settings, "explosion_early_green_lock_max_velocity_3s", 0.0
        )
        if (
            best >= early_min_best
            and pnl_pts <= early_buffer
            and live_velocity_3s <= early_max_v
        ):
            return "explosion_early_green_breakeven"

    # Near-peak capture when rollover is confirmed (best +12 → book ~+9).
    # Own enable flag — runs even if deep peak-fade lock is disabled.
    capture = peak_capture_profit_lock_reason(
        trade,
        best=best,
        pnl_pts=pnl_pts,
        max_profit=max_profit,
        live_velocity_3s=live_velocity_3s,
    )
    if capture:
        return capture

    if not getattr(settings, "explosion_peak_fade_lock_enabled", True):
        return None

    min_best = float(
        getattr(settings, "explosion_peak_fade_min_best_points", 6.0) or 6.0
    )
    giveback_ratio = float(
        getattr(settings, "explosion_peak_fade_giveback_ratio", 0.55) or 0.55
    )
    if max_profit:
        min_best = max(
            min_best,
            float(
                getattr(settings, "explosion_peak_fade_max_profit_min_best", 28.0)
                or 28.0
            ),
        )
        giveback_ratio = max(
            giveback_ratio,
            float(
                getattr(settings, "explosion_peak_fade_max_profit_giveback_ratio", 0.80)
                or 0.80
            ),
        )

    # CAUTION / PROTECT psychology → slightly tighter fade lock on normal trades.
    # Never tighten ICT max-profit runners — that undoes the hold band.
    ctx = trade.entryContext or {}
    if not max_profit:
        psych = str(
            ctx.get("psychologyLabel")
            or ctx.get("psychology")
            or ((ctx.get("exitPlan") or {}).get("psychologyLabel"))
            or ""
        ).upper()
        if psych in ("CAUTION", "FEAR", "OVERCONFIDENCE") or str(
            ctx.get("psychologyExitBias") or ""
        ).upper() in ("PROTECT", "TIGHT_STOPS"):
            min_best = max(5.0, min_best * 0.85)
            giveback_ratio = min(giveback_ratio, 0.50)

    if best < min_best:
        return None

    giveback = best - pnl_pts
    min_give = float(
        getattr(settings, "explosion_peak_fade_min_giveback_points", 4.0) or 4.0
    )
    min_remain = float(
        getattr(settings, "explosion_peak_fade_min_remain_points", 0.4) or 0.4
    )

    # Peaked then back to ~breakeven / slightly red — ALWAYS protect.
    # Chart may still print BULLISH while premium is already dead.
    if getattr(settings, "explosion_peak_fade_breakeven_lock", True):
        be_buf = float(
            getattr(settings, "explosion_peak_fade_breakeven_buffer", 0.5) or 0.5
        )
        if pnl_pts <= be_buf and giveback >= min_give:
            return "explosion_peak_fade_breakeven"

    # Soft lock: still green, but most of the peak is gone.
    # Near-base top runner → require a bigger peak before the soft lock so a small early
    # fade doesn't book the base rip early (breakeven lock above still protects downside).
    soft_min_best = _near_base_hold_min_best(trade, min_best, max_profit=max_profit)
    if (
        pnl_pts >= min_remain
        and best >= soft_min_best
        and giveback >= max(min_give, best * giveback_ratio)
    ):
        if _peak_fade_bullish_continuation(trade, pnl_pts=pnl_pts, settings=settings):
            # Healthy bullish pullback — hold; do not force early bank.
            return None
        return "explosion_peak_fade_profit_lock"

    return None


def evaluate_explosion_exit(
    trade: PaperTrade,
    current_premium: float,
    event_tier: str = "EXPLODING",
    lot_multiplier: int = 25,
    params: Optional[ExplosionExitParams] = None,
    *,
    live_velocity_3s: float = 0.0,
) -> tuple[Optional[str], float]:
    """
    Explosion exits: hard SL when losing, trailing SL + TP while winning.
    Lets runners extend; locks profit as peak builds.
    """
    settings = get_settings()
    exit_params = params or default_explosion_exit_params(event_tier)
    pnl_pts = current_premium - trade.entryPremium
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    observed_best = (
        float(trade.maxLtp) - float(trade.entryPremium)
        if trade.maxLtp is not None
        else 0.0
    )
    best = max(trade.bestPnlPoints, pnl_pts, observed_best)
    hold = _hold_seconds(trade)
    try:
        v3 = float(live_velocity_3s or 0.0)
    except (TypeError, ValueError):
        v3 = 0.0
    if trade.entryContext is None:
        trade.entryContext = {}
    if v3 or "liveVelocity3s" not in trade.entryContext:
        trade.entryContext["liveVelocity3s"] = round(v3, 3)

    from app.engines.explosion_entry_guards import faded_rip_no_green_exit_reason

    faded_exit = faded_rip_no_green_exit_reason(trade, hold_seconds=hold, best_points=best)
    if faded_exit:
        return faded_exit, pnl_inr

    # The launch thesis failed immediately: it never established green and live
    # premium is still contracting. Scratch before the wider structural stop.
    if bool(getattr(settings, "explosion_failed_launch_exit_enabled", True)):
        failed_min_hold = int(
            _cfg_float(settings, "explosion_failed_launch_min_hold_seconds", 15)
        )
        failed_max_hold = int(
            _cfg_float(settings, "explosion_failed_launch_max_hold_seconds", 45)
        )
        failed_max_best = _cfg_float(
            settings, "explosion_failed_launch_max_best_points", 1.0
        )
        failed_min_loss = _cfg_float(
            settings, "explosion_failed_launch_min_loss_points", 1.5
        )
        failed_max_v = _cfg_float(
            settings, "explosion_failed_launch_max_velocity_3s", 0.0
        )
        if (
            failed_min_hold <= hold <= failed_max_hold
            and best <= failed_max_best
            and pnl_pts <= -failed_min_loss
            and v3 < failed_max_v
        ):
            return "explosion_failed_launch", pnl_inr

    # Never-green hard cut: a trade that printed NO green and is now down past a tight
    # floor is directionally wrong from entry (Aug6 78800 PE: best=0 → ran to −37pt).
    # Cut it faster than the full adaptive stop. Threshold = max(points floor, % of entry
    # premium) so cheap and expensive options are both handled sensibly.
    if bool(getattr(settings, "explosion_never_green_stop_enabled", True)):
        ng_min_green = _cfg_float(settings, "explosion_never_green_min_green_points", 0.5)
        ng_floor = _cfg_float(settings, "explosion_never_green_stop_points", 18.0)
        ng_pct = _cfg_float(settings, "explosion_never_green_stop_pct", 6.0)
        ng_min_hold = int(_cfg_float(settings, "explosion_never_green_min_hold_seconds", 20))
        ng_stop = max(ng_floor, float(trade.entryPremium or 0) * ng_pct / 100.0)
        if best <= ng_min_green and hold >= ng_min_hold and pnl_pts <= -ng_stop:
            return "explosion_never_green_stop", pnl_inr

    # Hard per-trade ₹ loss cap — optional (0 = disabled). Prefer never-green + point SL
    # so ICT/base runners are not clipped by a rupee ceiling before the thesis stop.
    ctx = trade.entryContext or {}
    if bool(ctx.get("fullSleeveQualified")):
        hard_cap = _cfg_float(
            settings,
            "explosion_exceptional_per_trade_max_loss_inr",
            4_000.0,
        )
    else:
        hard_cap = _cfg_float(
            settings,
            "explosion_per_trade_max_loss_inr",
            2_000.0,
        )
    if hard_cap > 0 and pnl_inr <= -hard_cap:
        return "explosion_per_trade_risk_cap", pnl_inr

    from app.engines.ict_breakout_monitor import _ict_max_profit_trade

    max_profit = _ict_max_profit_trade(trade)

    # Peak→fade toward losses: book remaining green / BE before hard SL.
    # Runs before trail-arm gates so unarmed trails cannot give winners back.
    fade_lock = peak_fade_profit_lock_reason(
        trade,
        best=best,
        pnl_pts=pnl_pts,
        max_profit=max_profit,
        live_velocity_3s=v3,
    )
    if fade_lock:
        return fade_lock, pnl_inr

    from app.engines.moment_stage_trail import (
        compose_trail_floor_with_stages,
        maybe_extend_projected_max,
        trade_uses_moment_stage_ladder,
    )

    target = exit_params.target_points
    if max_profit:
        target = max(
            target,
            float(getattr(settings, "ict_max_profit_target_points", 180.0) or 180.0),
        )
    # Flat→vertical stage ladder: hold toward projected max TP (e.g. 440).
    stage_ladder = trade_uses_moment_stage_ladder(trade)
    projected_max = 0.0
    if stage_ladder:
        projected_max = maybe_extend_projected_max(trade, best, settings)
        if projected_max <= 0:
            try:
                projected_max = float(
                    (trade.entryContext or {}).get("projectedMaxTp")
                    or ((trade.entryContext or {}).get("exitPlan") or {}).get("projectedMaxTp")
                    or 0
                )
            except (TypeError, ValueError):
                projected_max = 0.0
        if projected_max > 0:
            target = max(target, projected_max)

    # High-conviction base rip → hold the runner (wider trail = lower keep floor).
    # Still exits on real reversal; just does not book at ~38% of peak (Jul22 SENSEX PE).
    from app.engines.explosion_confidence import trade_is_high_conviction

    high_conviction_trade = trade_is_high_conviction(trade)
    hc_keep = (
        float(getattr(settings, "high_conviction_trail_keep_ratio", 0.30) or 0.30)
        if high_conviction_trade
        else None
    )
    trail_floor = _trail_floor_pts(
        trade, best, settings, trail_arm_points=exit_params.trail_arm_points,
        keep_ratio_override=hc_keep,
    )
    trail_floor, stage_floor = compose_trail_floor_with_stages(
        trade, best, trail_floor, settings=settings,
    )
    try:
        stage_size = float(
            (trade.entryContext or {}).get("stageSize")
            or ((trade.entryContext or {}).get("exitPlan") or {}).get("stageSize")
            or 0
        )
    except (TypeError, ValueError):
        stage_size = 0.0
    trail_keep = (
        settings.runner_trail_keep_ratio
        if best >= settings.runner_min_best_points
        else exit_params.trail_keep_ratio
    )
    if max_profit:
        trail_keep = min(
            trail_keep,
            float(getattr(settings, "ict_max_profit_trail_keep_ratio", 0.42) or 0.42),
        )
    if high_conviction_trade and best >= settings.runner_min_best_points and hc_keep is not None:
        trail_keep = min(trail_keep, hc_keep)

    if (
        not exit_params.adaptive_stop
        and trail_floor is None
        and hold >= settings.explosion_stop_min_hold_seconds
        and pnl_pts <= -_effective_stop_points(trade, exit_params.stop_points)
    ):
        return "explosion_stop_loss", pnl_inr

    if settings.emergency_stop_enabled and pnl_inr <= -settings.emergency_stop_inr:
        return "explosion_emergency_stop", pnl_inr

    # Base→vertical ICT (12→392 PE): skip tiny hard TP — trail toward max.
    # Stage-ladder trades also skip tiny TP and ride stages to projectedMaxTp.
    skip_hard_tp = (max_profit or stage_ladder) and bool(
        getattr(settings, "ict_max_profit_skip_hard_target", True)
    )
    if not skip_hard_tp:
        # Peak touch counts — polling can miss the exact TP tick (e.g. best 12pt, current 8pt)
        if best >= target:
            return "explosion_target_hit", pnl_inr
        near = max(0.5, target * 0.04)
        if best >= target - near and best >= settings.explosion_trail_arm_points:
            return "explosion_target_hit", pnl_inr
    # Max-profit / stage-ladder targets are projections, not clairvoyant tops.
    # Once reached, keep following the observed LTP and let confirmed rollover,
    # peak capture, or the ratcheting stage floor exit the move.

    from app.engines.confidence_hold import (
        chart_confidence_for_trade,
        half_tp_giveback_exit,
        hold_until_target_active,
        should_defer_profit_lock,
        target_points_for_trade,
    )

    chart_target = target_points_for_trade(trade)
    chart_conf = chart_confidence_for_trade(trade)
    defer_tp_min = _cfg_float(settings, "chart_confidence_defer_tp_min", 60.6)
    defer_target = chart_target if chart_conf >= defer_tp_min else target
    if stage_ladder and projected_max > 0:
        defer_target = max(defer_target, projected_max)

    def _profit_lock_ok() -> bool:
        if max_profit or stage_ladder:
            # Let ICT / stage-ladder base rips run — only trail after a real expansion.
            return best >= min(40.0, target * 0.25)
        if not should_defer_profit_lock(trade, best, target_points=defer_target):
            return True
        if chart_conf >= defer_tp_min:
            return False
        # Standard explosion TP zone reached — don't block trail for distant chart TP
        return best >= _cfg_float(settings, "explosion_target_standard", 18.0) * 0.95

    defer_hc_lock = high_conviction_trade and bool(
        getattr(settings, "high_conviction_defer_profit_lock", True)
    )
    if (
        not max_profit
        and not stage_ladder
        and not defer_hc_lock
        and half_tp_giveback_exit(trade, best, pnl_pts, target_points=defer_target)
    ):
        return "explosion_half_tp_profit_lock", pnl_inr

    # Stage ladder (incl. pre-stage provisional floor): pullback through the
    # stage floor books profit; otherwise hold toward projectedMaxTp.
    stage_armed = stage_floor is not None and (
        best >= exit_params.trail_arm_points
        or (stage_size > 0 and best >= stage_size)
    )
    if stage_armed and pnl_pts <= stage_floor:
        return "explosion_stage_trail", pnl_inr

    # When stage ladder owns the trail, skip micro step / keep-ratio locks —
    # stage floors + projectedMaxTp are the profit path.
    if not stage_armed:
        if trail_floor is not None and pnl_pts <= trail_floor and best >= exit_params.trail_arm_points:
            # Hot continuing ICT/stage rips: defer green trail ticks so a 6pt
            # dip cannot cut a still-expanding move (392→500 case). Never defer
            # into a loss — _defer_explosion_trail_while_continuing enforces that.
            if not _defer_explosion_trail_while_continuing(
                trade,
                best=best,
                pnl_pts=pnl_pts,
                live_v=v3,
                projected_max=projected_max,
                stage_ladder=stage_ladder,
                max_profit=max_profit,
                settings=settings,
            ):
                return "explosion_trail_sl", pnl_inr

        if trail_floor is not None and pnl_pts < best * trail_keep and best >= (20 if max_profit else 8):
            if pnl_pts <= 0 or _profit_lock_ok():
                if not _defer_explosion_trail_while_continuing(
                    trade,
                    best=best,
                    pnl_pts=pnl_pts,
                    live_v=v3,
                    projected_max=projected_max,
                    stage_ladder=stage_ladder,
                    max_profit=max_profit,
                    settings=settings,
                ):
                    return "explosion_trail_lock", pnl_inr

    if (
        not max_profit
        and not stage_ladder
        and pnl_pts >= exit_params.micro_target_points
        and best - pnl_pts >= settings.runner_micro_giveback_points
        and best >= settings.runner_min_best_points
    ):
        if _profit_lock_ok():
            return "explosion_micro_profit_lock", pnl_inr

    stop_floor = _effective_stop_points(trade, exit_params.stop_points)
    if (
        exit_params.adaptive_stop
        and hold >= _adaptive_stop_min_hold(trade, settings)
        and pnl_pts <= -stop_floor
        and not _defer_adaptive_stop(
            trade, best, hold, settings, pnl_pts=pnl_pts, stop_floor=stop_floor,
        )
    ):
        return "adaptive_stop_loss", pnl_inr

    if _should_skip_no_progress(trade, settings):
        pass
    elif hold >= _no_progress_limit_seconds(trade, settings) and best < exit_params.trail_arm_points:
        from app.engines.confidence_hold import hold_until_target_active

        if not hold_until_target_active(trade, best, target_points=target):
            return "explosion_no_progress", pnl_inr

    # Peak fade after reaching explosion TP zone — even without confidence-runner hold
    target_std = _cfg_float(settings, "explosion_target_standard", 18.0)
    if (
        not max_profit
        and best >= target_std * 0.85
        and pnl_pts > 0
        and best >= exit_params.trail_arm_points
    ):
        giveback = best - pnl_pts
        min_give = max(
            settings.runner_micro_giveback_points,
            best * float(getattr(settings, "chart_confidence_half_tp_giveback_ratio", 0.40) or 0.40),
        )
        if giveback >= min_give:
            return "explosion_runner_giveback", pnl_inr

    max_hold = 420 if best >= settings.runner_min_best_points else (360 if event_tier == "ELITE" or best >= 15 else 300)
    from app.engines.confidence_hold import confidence_hold_max_seconds, hold_until_target_active

    conf_max = confidence_hold_max_seconds(trade)
    if conf_max > 0:
        max_hold = max(max_hold, conf_max)
    ctx = trade.entryContext or {}
    if max_profit:
        max_hold = max(
            max_hold,
            int(getattr(settings, "ict_max_profit_max_hold_seconds", 1200) or 1200),
        )
    if ctx.get("afternoonCapture"):
        max_hold = max(max_hold, settings.afternoon_capture_exit_max_hold_seconds)
    # ELITE/EXPLODING runners need room for the vertical (Jul29 77600 CE timed out
    # at +0.3pt / best +5.5 then LTP ran 253→290).
    tier_u = str(event_tier or ctx.get("explosionTier") or "").upper()
    elite_hold = int(getattr(settings, "explosion_elite_max_hold_seconds", 1800) or 1800)
    if tier_u in ("ELITE", "EXPLODING") and elite_hold > 0:
        max_hold = max(max_hold, elite_hold)
    if ctx.get("topExplosionMaxLots") or high_conviction_trade:
        max_hold = max(
            max_hold,
            int(getattr(settings, "ict_max_profit_max_hold_seconds", 1200) or 1200),
        )
    breadth_raw = ctx.get("breadth")
    breadth_bias = (
        str((breadth_raw or {}).get("bias") or "").upper()
        if isinstance(breadth_raw, dict)
        else str(breadth_raw or "").upper()
    )
    side_bias = "BULLISH" if trade.side.value == "CALL" else "BEARISH"
    if breadth_bias == side_bias:
        max_hold = int(max_hold * 1.4)
    # Structured + already-green thesis: hold via trail/SL/TP, not the clock
    # (Aug4 24550 PUT → 90–100). Never-green losers keep the elite time-stop.
    thesis_hold = _structured_green_thesis_hold_seconds(trade, best=best, settings=settings)
    if thesis_hold > 0:
        max_hold = max(max_hold, thesis_hold)
    if hold >= max_hold:
        # Prefer trail/giveback over blind time exit when runner peaked then faded
        if best >= exit_params.trail_arm_points:
            giveback = best - pnl_pts
            min_give = max(
                settings.runner_micro_giveback_points,
                best * settings.explosion_trail_keep_ratio * 0.5,
            )
            if giveback >= min_give and pnl_pts > 0:
                return "explosion_trail_sl", pnl_inr
            if trail_floor is not None and pnl_pts <= trail_floor:
                return "explosion_trail_sl", pnl_inr
            if pnl_pts < best * trail_keep and best >= 8:
                return "explosion_trail_lock", pnl_inr
        # Once thesis has gone green: never time-exit — SL / trail / peak-capture only.
        if _skip_time_exit_for_green_thesis(trade, best=best, settings=settings):
            return None, pnl_inr
        # A green FTV stage runner exits on observed rollover / its ratcheting
        # floor, never because a projection or generic hold clock expired.
        if pnl_pts > 0 and stage_ladder:
            return None, pnl_inr
        # Jul29 77600 CE: explosion_time_profit @ +0.3pt while still far from TP 37 —
        # LTP later printed 290. Skip green time-exit on top explosions working to TP.
        if pnl_pts > 0 and _skip_explosion_time_profit(
            trade,
            best=best,
            target=target,
            event_tier=tier_u,
            settings=settings,
        ):
            return None, pnl_inr
        if pnl_pts > 0 and hold_until_target_active(trade, best, target_points=target):
            return None, pnl_inr
        return ("explosion_time_profit" if pnl_pts > 0 else "explosion_time_stop"), pnl_inr

    return None, pnl_inr


def _green_thesis_active(trade: Any, *, best: float, settings: Any) -> bool:
    """True when ICT/HC structure has already printed meaningful green + side aligned."""
    if not bool(getattr(settings, "explosion_thesis_hold_enabled", True)):
        return False
    min_best = _cfg_float(settings, "explosion_thesis_hold_min_best_points", 2.0)
    if float(best or 0) < min_best:
        return False

    ctx = getattr(trade, "entryContext", None) or {}
    pattern = str(ctx.get("ictPattern") or "").lower()
    structured = bool(
        ctx.get("ictFirstLift")
        or ctx.get("firstLiftCapture")
        or ctx.get("ictFlatThenVertical")
        or ctx.get("ictMegaRip")
        or ctx.get("maxProfitCapture")
        or ctx.get("momentStageLadder")
        or ctx.get("highConviction")
        or ctx.get("defensiveBaseRip")
        or pattern
        in (
            "flat_then_vertical",
            "mega_rip",
            "early_flat_break",
            "local_swing_base",
            "first_lift_local_base",
            "premium_fvg",
        )
    )
    if not structured:
        return False

    side_v = trade.side.value if hasattr(trade.side, "value") else str(trade.side).upper()
    side_bias = "BULLISH" if side_v == "CALL" else "BEARISH"
    breadth_raw = ctx.get("breadth")
    breadth_bias = (
        str((breadth_raw or {}).get("bias") or "").upper()
        if isinstance(breadth_raw, dict)
        else str(breadth_raw or "").upper()
    )
    chart_dir = str(
        (ctx.get("indexChart") or {}).get("direction")
        or (ctx.get("spotChart") or {}).get("direction")
        or ""
    ).upper()
    return breadth_bias == side_bias or chart_dir == side_bias


def _skip_time_exit_for_green_thesis(trade: Any, *, best: float, settings: Any) -> bool:
    """Once green thesis is active, never fire time_stop / time_profit."""
    if not bool(getattr(settings, "explosion_thesis_hold_skip_time_exit", True)):
        return False
    return _green_thesis_active(trade, best=best, settings=settings)


def _structured_green_thesis_hold_seconds(
    trade: Any,
    *,
    best: float,
    settings: Any,
) -> int:
    """Fallback max-hold bump for green ICT/HC thesis (used if skip-time is off).

    Qualifies as soon as best clears the green floor + structure + side aligned.
    Does NOT qualify never-green losers — they keep the elite time-stop clock.
    """
    if not _green_thesis_active(trade, best=best, settings=settings):
        return 0
    return int(getattr(settings, "explosion_thesis_hold_max_seconds", 10800) or 10800)


def _skip_explosion_time_profit(
    trade: Any,
    *,
    best: float,
    target: float,
    event_tier: str,
    settings: Any,
) -> bool:
    """True → do not fire explosion_time_profit; let trail/SL/TP manage the exit."""
    if not getattr(settings, "explosion_skip_time_profit_enabled", True):
        return False
    ctx = getattr(trade, "entryContext", None) or {}
    tiers_raw = str(
        getattr(settings, "explosion_skip_time_profit_tiers_csv", "ELITE,EXPLODING")
        or "ELITE,EXPLODING"
    )
    tiers = {t.strip().upper() for t in tiers_raw.split(",") if t.strip()}
    tier = str(event_tier or ctx.get("explosionTier") or "").upper()
    top_size = bool(
        ctx.get("topExplosionMaxLots")
        or ctx.get("highConviction")
        or ctx.get("ictFirstLift")
        or ctx.get("firstLiftCapture")
    )
    if tier not in tiers and not top_size:
        return False
    frac = float(
        getattr(settings, "explosion_skip_time_profit_until_target_frac", 0.85) or 0.85
    )
    entry_tp = float(
        (ctx.get("exitPlan") or {}).get("entryTargetPoints")
        or (ctx.get("exitPlan") or {}).get("targetPoints")
        or target
        or 0
    )
    floor = max(float(getattr(settings, "runner_min_best_points", 5.0) or 5.0), entry_tp * frac)
    return best < floor
