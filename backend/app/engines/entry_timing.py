"""Per-trade entry timing assessment — is this rip still live?

Aug4 NIFTY 24550 PUT: ELITE / mega_rip / localBase 28.8% with live v3=0.8.
Blind max-lot cold fill was bad; blocking the whole thesis missed LTP→120.
Structured cold-base (local still in window + heat + aligned) is allowed at
full/max lots; true LATE/CHASE without a live local base stays blocked.

Timing verdicts:
  GOOD       — structured + in window + hot live velocity → full size OK
  OK         — in window with adequate live heat → allow
  COLD_BASE  — ICT local-base pause (cold tape, still in window) → max lots
  COLD       — structure/ELITE but live velocity dead → block (chop) or lot-cap
  LATE       — peak already extended and live cooled → block
  CHASE      — past structured/local chase ceiling → block
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import SymbolSnapshot


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v if v is not None else default)
    except (TypeError, ValueError):
        return default


def _session_move(event: Any) -> float:
    if event is None:
        return 0.0
    return max(
        _f(getattr(event, "daily_move_pct", 0)),
        _f(getattr(event, "peak_move_pct", 0)),
    )


def _live_v3(event: Any) -> float:
    if event is None:
        return 0.0
    return _f(getattr(event, "velocity_3s", 0))


def _local_base_pct(ict: Any) -> float:
    if ict is None:
        return 0.0
    from app.engines.explosion_entry_guards import trustworthy_local_base_move

    return _f(trustworthy_local_base_move(ict))


def _structured(ict: Any) -> bool:
    if ict is None:
        return False
    return bool(
        getattr(ict, "flat_then_vertical", False)
        or getattr(ict, "local_swing_base", False)
    )


def _has_heat(ict: Any) -> bool:
    if ict is None:
        return False
    return bool(
        getattr(ict, "volume_awakening", False)
        or getattr(ict, "displacement", False)
        or getattr(ict, "premium_fvg", False)
    )


def _chop_or_worst(snap: Optional[SymbolSnapshot], midday_chop: bool) -> bool:
    if midday_chop:
        return True
    if snap is None:
        return False
    regime_value = getattr(snap, "regime", "") or ""
    regime = str(
        regime_value.value if hasattr(regime_value, "value") else regime_value
    ).upper()
    if regime in ("CHOP", "RANGE_BOUND", "WORST"):
        return True
    return False


def _side_aligned(event: Any, snap: Optional[SymbolSnapshot]) -> bool:
    """Breadth or chart agrees with option side (CALL↔BULLISH / PUT↔BEARISH)."""
    if event is None or snap is None:
        return False
    side_v = getattr(event, "side", None)
    side = side_v.value if hasattr(side_v, "value") else str(side_v or "").upper()
    want = "BULLISH" if side == "CALL" else "BEARISH" if side == "PUT" else ""
    if not want:
        return False
    breadth = getattr(snap, "breadth", None)
    bias = str(getattr(breadth, "bias", "") or "").upper() if breadth is not None else ""
    chart = getattr(snap, "spotChart", None) or getattr(snap, "indexChart", None)
    direction = str(getattr(chart, "direction", "") or "").upper() if chart is not None else ""
    return bias == want or direction == want


def _structured_cold_base_ok(
    *,
    settings: Any,
    structured: bool,
    in_window: bool,
    local: float,
    heat: bool,
    live_v: float,
    good_min: float,
    event: Any,
    snap: Optional[SymbolSnapshot],
) -> bool:
    """Pause-before-continuation: ICT local base still early, live tape cold."""
    if not bool(getattr(settings, "entry_timing_structured_cold_base_allow", True)):
        return False
    if not structured or not in_window or local <= 0:
        return False
    # Only when live is actually cold — hot path uses GOOD/OK instead.
    if live_v >= good_min:
        return False
    min_velocity = _f(
        getattr(settings, "entry_timing_structured_cold_min_velocity_3s", 0.5),
        0.5,
    )
    if live_v < min_velocity:
        return False
    if bool(getattr(settings, "entry_timing_structured_cold_require_heat", True)) and not heat:
        return False
    if bool(getattr(settings, "entry_timing_structured_cold_require_aligned", True)):
        if not _side_aligned(event, snap):
            return False
    return True


def assess_entry_timing(
    event: Any,
    *,
    ict: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    midday_chop: bool = False,
    premium_capture: bool = False,
) -> dict[str, Any]:
    """Return timingAssessment dict for journal + entry gates."""
    settings = get_settings()
    live_v = _live_v3(event)
    session = _session_move(event)
    local = _local_base_pct(ict)
    structured = _structured(ict)
    heat = _has_heat(ict)
    tier = str(getattr(event, "tier", "") or "").upper() if event is not None else ""

    # Window bounds — structured ICT uses nearer-base band when available.
    from app.engines.explosion_entry_guards import entry_window_bounds

    try:
        lo, hi = entry_window_bounds(ict)
        lo, hi = _f(lo, 28.0), _f(hi, 55.0)
    except (TypeError, ValueError):
        lo, hi = 28.0, 55.0
    if hi <= lo:
        lo, hi = 28.0, 55.0
    move_for_window = local if local > 0 else session
    in_window = lo <= move_for_window <= hi if move_for_window > 0 else False

    cold_max = _f(getattr(settings, "entry_timing_cold_max_velocity_3s", 1.5), 1.5)
    good_min = _f(getattr(settings, "entry_timing_good_min_velocity_3s", 2.0), 2.0)
    ok_min = _f(getattr(settings, "entry_timing_ok_min_velocity_3s", 1.5), 1.5)
    late_peak = _f(getattr(settings, "entry_timing_late_min_peak_pct", 55.0), 55.0)
    late_max_v = _f(getattr(settings, "entry_timing_late_max_live_velocity_3s", 1.0), 1.0)
    chase_hi = hi

    reasons: list[str] = []
    assessment = "OK"
    action = "allow"
    lot_cap: Optional[int] = None

    # Soft near-ATM floor for structured (matches live-confirm soft floor).
    near_atm_soft = False
    if snap is not None and event is not None and structured:
        try:
            from app.engines.explosion_entry_guards import structured_near_atm

            near_atm_soft = structured_near_atm(
                getattr(event, "side", ""),
                float(getattr(event, "strike", 0) or 0),
                snap,
                ict=ict,
                event=event,
            )
        except Exception:
            near_atm_soft = False
    effective_cold = min(cold_max, 1.0) if near_atm_soft else cold_max
    effective_ok = min(ok_min, 1.0) if near_atm_soft else ok_min

    cold_base = _structured_cold_base_ok(
        settings=settings,
        structured=structured,
        in_window=in_window,
        local=local,
        heat=heat,
        live_v=live_v,
        good_min=good_min,
        event=event,
        snap=snap,
    )

    structured_failed_launch = bool(
        structured
        and in_window
        and local > 0
        and live_v
        < _f(
            getattr(settings, "entry_timing_structured_cold_min_velocity_3s", 0.5),
            0.5,
        )
    )

    # --- priority: CHASE > failed launch > structured cold-base > LATE/COLD > GOOD/OK ---
    if local > chase_hi > 0:
        assessment = "CHASE"
        action = "block"
        reasons.append(f"local_base_{local:.0f}%>ceiling_{chase_hi:.0f}%")
    elif local <= 0 and session > chase_hi > 0 and not (structured and heat and live_v >= good_min):
        assessment = "CHASE"
        action = "block"
        reasons.append(f"session_{session:.0f}%>ceiling_{chase_hi:.0f}%")
    elif structured_failed_launch:
        assessment = "FAILED_LAUNCH"
        action = "block"
        reasons.append(f"structured_base_negative_v3_{live_v:.1f}")
        reasons.append("wait_for_positive_reacceleration")
    elif cold_base:
        # Positive but sub-breakout velocity: take only a small probe. Full sleeve
        # requires the separate armed-launch/CVD proof in auto_trader.
        assessment = "COLD_BASE"
        action = "lot_cap"
        lot_cap = max(
            1,
            int(getattr(settings, "entry_timing_structured_cold_lot_cap", 3) or 3),
        )
        reasons.append(f"structured_cold_base_v3_{live_v:.1f}")
        reasons.append(f"local_base_{local:.0f}%_in_window")
        reasons.append(f"cold_base_lot_cap_{lot_cap}")
    elif (
        session >= late_peak
        and live_v <= late_max_v
        and not (structured and in_window and live_v >= good_min)
    ):
        # Extended day peak with dead tape — late chase (unless hot structured in window).
        assessment = "LATE"
        action = "block"
        reasons.append(f"peak_{session:.0f}%_live_v3_{live_v:.1f}")
    elif (
        not premium_capture
        and tier in ("ELITE", "EXPLODING", "BUILDING")
        and live_v < effective_cold
        and (structured or tier in ("ELITE", "EXPLODING"))
    ):
        assessment = "COLD"
        reasons.append(f"live_v3_{live_v:.1f}<{effective_cold:.1f}")
        if local > 0:
            reasons.append(f"local_base_{local:.0f}%")
        chopish = _chop_or_worst(snap, midday_chop)
        if chopish and bool(getattr(settings, "entry_timing_cold_block_on_chop", True)):
            action = "block"
            reasons.append("chop_or_worst_cold_block")
        else:
            action = "lot_cap"
            lot_cap = int(getattr(settings, "entry_timing_cold_lot_cap", 3) or 3)
            reasons.append(f"cold_lot_cap_{lot_cap}")
    elif structured and in_window and live_v >= good_min and (heat or live_v >= good_min + 0.5):
        assessment = "GOOD"
        action = "allow"
        reasons.append(f"hot_v3_{live_v:.1f}_in_window_{move_for_window:.0f}%")
    elif in_window and live_v >= effective_ok:
        assessment = "OK"
        action = "allow"
        reasons.append(f"live_v3_{live_v:.1f}_in_window_{move_for_window:.0f}%")
    elif live_v >= good_min and in_window:
        assessment = "OK"
        action = "allow"
        reasons.append(f"hot_v3_{live_v:.1f}_in_window")
    else:
        # Default: weak heat / unclear window — treat as COLD soft.
        if live_v < effective_ok and tier in ("ELITE", "EXPLODING"):
            assessment = "COLD"
            reasons.append(f"weak_live_v3_{live_v:.1f}")
            if _chop_or_worst(snap, midday_chop) and bool(
                getattr(settings, "entry_timing_cold_block_on_chop", True)
            ):
                action = "block"
                reasons.append("chop_or_worst_cold_block")
            else:
                action = "lot_cap"
                lot_cap = int(getattr(settings, "entry_timing_cold_lot_cap", 3) or 3)
        else:
            assessment = "OK"
            action = "allow"
            reasons.append("default_ok")

    return {
        "assessment": assessment,
        "action": action,
        "lotCap": lot_cap,
        "liveVelocity3s": round(live_v, 3),
        "sessionMovePct": round(session, 2),
        "localBasePct": round(local, 2),
        "inWindow": in_window,
        "window": [round(lo, 1), round(hi, 1)],
        "structured": structured,
        "heat": heat,
        "tier": tier,
        "nearAtmSoft": near_atm_soft,
        "premiumCapture": bool(premium_capture),
        "structuredColdBase": assessment == "COLD_BASE",
        "reasons": reasons,
    }


def timing_blocks_entry(timing: dict[str, Any]) -> tuple[bool, str]:
    """Hard-block when timing action is block."""
    settings = get_settings()
    if not bool(getattr(settings, "entry_timing_assessment_enabled", True)):
        return False, ""
    if not timing:
        return False, ""
    if str(timing.get("action") or "") != "block":
        return False, ""
    label = str(timing.get("assessment") or "COLD")
    why = ",".join(str(r) for r in (timing.get("reasons") or [])[:3])
    return True, f"entry_timing_{label.lower()}_{why}"


def cap_lots_for_timing(lots: int, timing: dict[str, Any]) -> int:
    """Apply lot cap when timing says lot_cap (COLD soft path)."""
    settings = get_settings()
    if not bool(getattr(settings, "entry_timing_assessment_enabled", True)):
        return lots
    if str(timing.get("action") or "") != "lot_cap":
        return lots
    cap = timing.get("lotCap")
    if cap is None:
        cap = int(getattr(settings, "entry_timing_cold_lot_cap", 3) or 3)
    return min(max(1, int(lots)), max(1, int(cap)))


def timing_allows_full_size(timing: dict[str, Any]) -> bool:
    """Max-lot boosts require positive launch timing; COLD_BASE stays probe-sized."""
    if not timing:
        return True
    settings = get_settings()
    if not bool(getattr(settings, "entry_timing_assessment_enabled", True)):
        return True
    return str(timing.get("assessment") or "").upper() in ("GOOD", "OK")


def elite_bypass_allowed_for_timing(timing: dict[str, Any]) -> bool:
    """Elite never-block may skip FOMO gates only on GOOD timing.

    GOOD = structured ICT + in-window + hot live velocity. Hot displacement
    alone (OK) must not skip live-confirm / fake-trap — those gates exist to
    catch Jul20/Jul23 FOMO spikes that look ELITE without a real base rip.
    """
    settings = get_settings()
    if not bool(getattr(settings, "entry_timing_elite_bypass_requires_hot", True)):
        return True
    if not bool(getattr(settings, "entry_timing_assessment_enabled", True)):
        return True
    return str(timing.get("assessment") or "").upper() == "GOOD"


def assess_timing_for_event(
    event: Any,
    *,
    ict: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    midday_chop: bool = False,
    premium_capture: bool = False,
) -> dict[str, Any]:
    """Convenience: analyze ICT if missing, then assess."""
    if event is None:
        return {
            "assessment": "OK",
            "action": "allow",
            "lotCap": None,
            "reasons": ["no_event"],
        }
    resolved_ict = ict
    if resolved_ict is None:
        try:
            from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

            resolved_ict = analyze_explosion_event_ict(event, snap)
        except Exception:
            resolved_ict = None
    if not midday_chop:
        try:
            from app.engines.session_timing import in_midday_chop_window

            midday_chop = bool(in_midday_chop_window())
        except Exception:
            midday_chop = False
    return assess_entry_timing(
        event,
        ict=resolved_ict,
        snap=snap,
        midday_chop=midday_chop,
        premium_capture=premium_capture,
    )
