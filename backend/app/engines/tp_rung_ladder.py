"""Multi-rung take-profit ladder — one owner for mega stage-ladder exits.

At entry, build N profit rungs (micro/target + stage steps to projectedMaxTp).
While open, confirm rungs from ``best``, ratchet an active floor on the last
confirmed rung, and exit on fade between rungs or a fall through that floor.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from app.config import Settings, get_settings
from app.models.schemas import PaperTrade


def _cfg_float(s: Settings, key: str, default: float) -> float:
    try:
        v = getattr(s, key, default)
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    return x


def trade_uses_tp_rung_ladder(trade: PaperTrade, settings: Optional[Settings] = None) -> bool:
    """True when this leg uses the TP rung owner (mega max-profit stage ladder)."""
    s = settings or get_settings()
    if not bool(getattr(s, "tp_rung_ladder_exit_enabled", True)):
        return False
    ctx = trade.entryContext or {}
    if not bool(ctx.get("maxProfitCapture")):
        return False
    from app.engines.moment_stage_trail import trade_uses_moment_stage_ladder

    if not trade_uses_moment_stage_ladder(trade):
        return False
    plan = ctx.get("exitPlan") or {}
    projected = _safe_float(ctx.get("projectedMaxTp") or plan.get("projectedMaxTp"))
    min_proj = _cfg_float(s, "tp_rung_ladder_min_projected_tp", 400.0)
    return projected + 1e-6 >= min_proj


def build_tp_rung_points(
    *,
    projected_max_tp: float,
    stage_size: float,
    exit_plan: Optional[dict] = None,
    settings: Optional[Settings] = None,
) -> list[float]:
    """Profit rungs in points above entry, sorted ascending."""
    s = settings or get_settings()
    plan = exit_plan or {}
    min_rung = _cfg_float(s, "tp_rung_ladder_min_rung_points", 4.0)
    rungs: list[float] = []

    for key in (
        "microTargetPoints",
        "targetPoints",
        "entryTargetPoints",
        "entryTargetPoints2",
        "targetPoints2",
        "trailArmPoints",
    ):
        v = _safe_float(plan.get(key))
        if v + 1e-6 >= min_rung:
            rungs.append(v)

    stage = max(_safe_float(stage_size), _cfg_float(s, "moment_stage_min_size", 5.0))
    projected = max(_safe_float(projected_max_tp), stage)
    k = 1
    while k * stage <= projected + 1e-6:
        rungs.append(k * stage)
        k += 1
    if projected + 1e-6 >= min_rung and not any(abs(r - projected) < 0.05 for r in rungs):
        rungs.append(projected)

    dedup = sorted({round(r, 2) for r in rungs if r + 1e-6 >= min_rung})
    max_rungs = int(_cfg_float(s, "tp_rung_ladder_max_rungs", 24))
    if len(dedup) > max_rungs:
        dedup = dedup[: max_rungs - 1] + [dedup[-1]]
    return dedup


def ensure_tp_rungs_stamped(trade: PaperTrade, settings: Optional[Settings] = None) -> list[float]:
    """Persist ``tpRungsPts`` on the trade when missing; extend when projection grows."""
    s = settings or get_settings()
    ctx = dict(trade.entryContext or {})
    plan = ctx.get("exitPlan") or {}
    projected = _safe_float(ctx.get("projectedMaxTp") or plan.get("projectedMaxTp"))
    stage = _safe_float(ctx.get("stageSize") or plan.get("stageSize"))
    existing = ctx.get("tpRungsPts")
    if isinstance(existing, list) and existing:
        rungs = [_safe_float(x) for x in existing if _safe_float(x) > 0]
    else:
        rungs = build_tp_rung_points(
            projected_max_tp=projected,
            stage_size=stage,
            exit_plan=plan,
            settings=s,
        )
    rebuilt = build_tp_rung_points(
        projected_max_tp=projected,
        stage_size=stage,
        exit_plan=plan,
        settings=s,
    )
    merged = sorted({round(r, 2) for r in rungs + rebuilt if r > 0})
    ctx["tpRungLadder"] = True
    ctx["tpRungsPts"] = merged
    plan = dict(plan)
    plan["tpRungsPts"] = merged
    plan["tpRungLadder"] = True
    ctx["exitPlan"] = plan
    trade.entryContext = ctx
    return merged


def _confirmed_rung_index(best: float, rungs: list[float], settings: Settings) -> int:
    confirm_slip = _cfg_float(settings, "tp_rung_ladder_confirm_slip_points", 0.25)
    idx = -1
    for i, r in enumerate(rungs):
        if best + 1e-6 >= r - confirm_slip:
            idx = i
    return idx


def _active_floor_pts(confirmed_idx: int, rungs: list[float], settings: Settings) -> float:
    if confirmed_idx < 0 or not rungs:
        return 0.0
    floor_slip = _cfg_float(settings, "tp_rung_ladder_floor_slip_points", 1.0)
    return max(0.0, rungs[confirmed_idx] - floor_slip)


def _seconds_since_peak(trade: PaperTrade) -> Optional[float]:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
    peak_at = getattr(trade, "maxLtpAt", None)
    if peak_at is None:
        return None
    if isinstance(peak_at, str):
        try:
            peak_at = datetime.fromisoformat(peak_at.replace("Z", "+00:00"))
        except ValueError:
            return None
    if peak_at.tzinfo is None:
        peak_at = peak_at.replace(tzinfo=IST)
    return (datetime.now(IST) - peak_at.astimezone(IST)).total_seconds()


def _tp_rung_exit_ready(
    trade: PaperTrade,
    hold_seconds: float,
    settings: Settings,
    *,
    falling_under: bool,
) -> bool:
    if not falling_under:
        min_hold = _cfg_float(settings, "unified_profit_ladder_min_hold_seconds", 180.0)
        if hold_seconds + 1e-6 < min_hold:
            return False
        min_after = _cfg_float(settings, "unified_profit_ladder_min_seconds_after_peak", 180.0)
        if min_after <= 0:
            return True
        since = _seconds_since_peak(trade)
        if since is None:
            return True
        return since + 1e-6 >= min_after
    min_hold = _cfg_float(settings, "unified_profit_ladder_fall_min_hold_seconds", 60.0)
    if hold_seconds + 1e-6 < min_hold:
        return False
    min_after = _cfg_float(settings, "unified_profit_ladder_fall_min_seconds_after_peak", 45.0)
    if min_after <= 0:
        return True
    since = _seconds_since_peak(trade)
    if since is None:
        return True
    return since + 1e-6 >= min_after


def _attempted_next_rung(best: float, confirmed_idx: int, rungs: list[float], settings: Settings) -> bool:
    if confirmed_idx < 0 or confirmed_idx + 1 >= len(rungs):
        return False
    conf = rungs[confirmed_idx]
    nxt = rungs[confirmed_idx + 1]
    buffer = _cfg_float(settings, "tp_rung_ladder_approach_buffer_points", 4.0)
    confirm_need = _cfg_float(settings, "tp_rung_ladder_confirm_slip_points", 0.25)
    mid = conf + (nxt - conf) * 0.5
    approached = best + 1e-6 >= min(mid, nxt - buffer)
    not_confirmed = best + 1e-6 < nxt - confirm_need
    return approached and not_confirmed


def sync_tp_rung_state(
    trade: PaperTrade,
    best: float,
    *,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """Update confirmed rung + ratcheted floor from ``best``."""
    s = settings or get_settings()
    rungs = ensure_tp_rungs_stamped(trade, settings=s)
    ctx = dict(trade.entryContext or {})
    confirmed = _confirmed_rung_index(best, rungs, s)
    prev_confirmed = int(ctx.get("tpRungConfirmedIdx") or -1)
    if confirmed > prev_confirmed:
        ctx["tpRungConfirmedIdx"] = confirmed
    elif confirmed >= 0 and prev_confirmed < 0:
        ctx["tpRungConfirmedIdx"] = confirmed
    else:
        confirmed = max(prev_confirmed, confirmed)
        ctx["tpRungConfirmedIdx"] = confirmed

    floor = _active_floor_pts(confirmed, rungs, s)
    prev_floor = _safe_float(ctx.get("tpRungActiveFloorPts"))
    floor = round(max(prev_floor, floor), 2)
    ctx["tpRungActiveFloorPts"] = floor
    ctx["tpRungLadder"] = True
    trade.entryContext = ctx
    return {
        "rungs": rungs,
        "confirmedIdx": confirmed,
        "activeFloorPts": floor,
    }


def tp_rung_exit_reason(
    trade: PaperTrade,
    *,
    best: float,
    pnl_pts: float,
    hold_seconds: float,
    live_velocity_3s: float = 0.0,
    settings: Optional[Settings] = None,
) -> Optional[str]:
    """Exit when fading between rungs or falling through the active rung floor."""
    s = settings or get_settings()
    if not trade_uses_tp_rung_ladder(trade, settings=s):
        return None

    state = sync_tp_rung_state(trade, best, settings=s)
    rungs: list[float] = state["rungs"]
    confirmed: int = int(state["confirmedIdx"])
    floor: float = float(state["activeFloorPts"])
    if not rungs or confirmed < 0:
        return None

    best = float(best or 0)
    if best + 1e-6 < _cfg_float(s, "tp_rung_ladder_min_best_to_arm_exits", 28.0):
        return None
    pnl_pts = float(pnl_pts or 0)
    try:
        v3 = float(live_velocity_3s or 0.0)
    except (TypeError, ValueError):
        v3 = 0.0

    min_hold = _cfg_float(s, "tp_rung_ladder_min_hold_seconds", 45.0)
    if hold_seconds + 1e-6 < min_hold:
        return None

    if v3 >= _cfg_float(s, "tp_rung_ladder_hot_defer_velocity_3s", 2.5):
        return None

    falling = v3 < 0
    falling_under = v3 < 0 and pnl_pts <= floor + 1e-6
    mega_red = pnl_pts <= 0 and falling
    urgent = falling_under or mega_red or _attempted_next_rung(best, confirmed, rungs, s)
    if not _tp_rung_exit_ready(trade, hold_seconds, s, falling_under=urgent):
        return None

    touch = _cfg_float(s, "tp_rung_ladder_floor_touch_points", 2.0)
    min_giveback = _cfg_float(s, "tp_rung_ladder_fade_min_giveback_points", 2.0)

    # Between rungs: tried the next TP, fading — bank at last confirmed rung (100→28,36,33).
    if (
        falling
        and _attempted_next_rung(best, confirmed, rungs, s)
        and (best - pnl_pts) + 1e-6 >= min_giveback
    ):
        return "explosion_tp_rung_between_fade"

    if pnl_pts <= 0 and falling and confirmed >= 0:
        min_red_best = _cfg_float(s, "tp_rung_ladder_red_min_best_points", 20.0)
        if best + 1e-6 >= min_red_best:
            return "explosion_tp_rung_red_giveback"

    if floor <= 0:
        return None

    if falling_under or (falling and pnl_pts + 1e-6 <= floor + touch):
        return "explosion_tp_rung_floor"

    if falling and pnl_pts + 1e-6 < floor - touch - 1e-6:
        return "explosion_tp_rung_floor_hole"

    return None
