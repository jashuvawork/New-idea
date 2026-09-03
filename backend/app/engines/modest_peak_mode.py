"""Modest peak mode — tighter 75% peak-keep for chop-day explosions that are not mega FTV.

Sep03 NIFTY PUT 23900: ELITE afternoon chop pop peaked +16.4pt then gave back to +4pt
because maxProfitCapture + stage ladder used wide pre-stage floors and %-keep never armed
(20.6% gain < 25% arm, best 16.4 < 20pt max-profit arm). Modest peak mode stamps at entry
and lowers the arm threshold so peak-keep exits fire on real but modest moves.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import Settings, get_settings
from app.models.schemas import PaperTrade, SymbolSnapshot


def _cfg_float(settings: Settings, name: str, default: float) -> float:
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


def _edge_reasons(edge: Any) -> list[str]:
    if edge is None:
        return []
    reasons = getattr(edge, "reasons", None)
    if reasons is None and isinstance(edge, dict):
        reasons = edge.get("reasons") or (edge.get("edgeScore") or {}).get("reasons")
    return [str(r) for r in (reasons or [])]


def trade_uses_modest_peak_mode(trade: PaperTrade) -> bool:
    ctx = trade.entryContext or {}
    plan = ctx.get("exitPlan") or {}
    return bool(ctx.get("modestPeakMode") or plan.get("modestPeakMode"))


def classify_modest_peak_entry(
    *,
    edge: Any,
    tier: str,
    afternoon_capture: bool,
    ict_flat_vertical: bool,
    mega_rip: bool,
    first_lift_runner: bool,
    velocity_3s: float,
    lift_readiness_reason: str,
    max_profit_capture: bool,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    settings: Optional[Settings] = None,
) -> tuple[bool, str]:
    """Return (use_modest_peak, reason_code)."""
    s = settings or get_settings()
    if not bool(getattr(s, "modest_peak_mode_enabled", True)):
        return False, ""

    if ict_flat_vertical or mega_rip:
        return False, ""

    hot_v = _cfg_float(s, "modest_peak_skip_hot_velocity_3s", 4.0)
    if first_lift_runner and velocity_3s >= hot_v:
        return False, ""

    ftv_pad_lanes = {
        "first_lift_local_base_ready",
        "armed_base_local_base_ready",
        "flat_then_vertical_ready",
        "slow_grind_sudden_lift_ready",
        "fast_bullish_local_base_ready",
        "v_rip_session_low_ready",
        "building_local_base_lift_ready",
        "squeeze_release_ready",
        "premium_fvg_pad_ready",
    }
    reasons = _edge_reasons(edge)
    chop_reasons: list[str] = []
    if "midday_chop" in reasons:
        chop_reasons.append("midday_chop")
    if "tighten_exits_pf" in reasons:
        chop_reasons.append("tighten_exits_pf")

    try:
        from app.engines.session_timing import in_midday_chop_window

        if in_midday_chop_window():
            chop_reasons.append("midday_chop_window")
    except Exception:
        pass

    if snapshots:
        try:
            from app.engines.chop_day_guards import is_chop_session

            if is_chop_session(snapshots):
                chop_reasons.append("chop_session")
        except Exception:
            pass

    if not chop_reasons:
        return False, ""

    if lift_readiness_reason in ftv_pad_lanes and not {"midday_chop", "chop_session"} & set(
        chop_reasons
    ):
        return False, ""

    tier_u = str(tier or "").upper()
    if tier_u not in ("ELITE", "EXPLODING", "STRONG"):
        return False, ""

    if afternoon_capture and "midday_chop" in chop_reasons:
        return True, "afternoon_chop_capture"
    if max_profit_capture and chop_reasons:
        return True, "elite_chop_modest_peak"
    if "midday_chop" in chop_reasons and tier_u in ("ELITE", "EXPLODING"):
        return True, "midday_chop_explosion"
    if "chop_session" in chop_reasons and tier_u in ("ELITE", "EXPLODING"):
        return True, "chop_session_explosion"
    return False, ""


def cap_modest_peak_stage_plan(
    stage_plan: dict[str, Any],
    entry_premium: float,
    *,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """Cap projected TP / stage size so chop pops do not inherit mega-rip exit fantasy."""
    s = settings or get_settings()
    out = dict(stage_plan)
    entry = float(entry_premium or 0)
    max_pts = _cfg_float(s, "modest_peak_max_projected_tp_points", 60.0)
    max_frac = _cfg_float(s, "modest_peak_max_projected_tp_frac_of_entry", 0.85)
    cap = max_pts
    if entry > 0:
        cap = min(cap, entry * max_frac)
    cap = max(_cfg_float(s, "moment_stage_min_projected_tp", 40.0), cap)
    projected = min(float(out.get("projectedMaxTp") or cap), cap)
    out["projectedMaxTp"] = round(projected, 1)
    max_stage = _cfg_float(s, "modest_peak_max_stage_size", 30.0)
    stage = min(float(out.get("stageSize") or max_stage), max_stage)
    out["stageSize"] = round(stage, 1)
    return out


def apply_modest_peak_entry_stamp(
    ctx_extra: dict[str, Any],
    *,
    edge: Any,
    tier: str,
    afternoon_capture: bool,
    ict_flat_vertical: bool,
    mega_rip: bool,
    first_lift_runner: bool,
    velocity_3s: float,
    lift_readiness_reason: str,
    entry_premium: float,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    settings: Optional[Settings] = None,
) -> bool:
    """Stamp modestPeakMode on ctx + exitPlan; tighten exit bias. Returns True when stamped."""
    s = settings or get_settings()
    use, reason = classify_modest_peak_entry(
        edge=edge,
        tier=tier,
        afternoon_capture=afternoon_capture,
        ict_flat_vertical=ict_flat_vertical,
        mega_rip=mega_rip,
        first_lift_runner=first_lift_runner,
        velocity_3s=velocity_3s,
        lift_readiness_reason=lift_readiness_reason,
        max_profit_capture=bool(ctx_extra.get("maxProfitCapture")),
        snapshots=snapshots,
        settings=s,
    )
    if not use:
        return False

    ctx_extra["modestPeakMode"] = True
    ctx_extra["modestPeakReason"] = reason
    plan = dict(ctx_extra.get("exitPlan") or {})
    plan["modestPeakMode"] = True
    plan["modestPeakReason"] = reason
    if str(plan.get("exitBias") or "").upper() == "LET_RUNNERS":
        plan["exitBias"] = "PROTECT"
        plan["psychologyLabel"] = plan.get("psychologyLabel") or ctx_extra.get("psychologyLabel")
        reasons = list(plan.get("reasoning") or [])
        reasons.append(f"modest_peak_mode:{reason} — tighten exit (chop pop, not mega FTV)")
        plan["reasoning"] = reasons
    ctx_extra["exitPlan"] = plan
    ctx_extra["psychologyExitBias"] = plan.get("exitBias", ctx_extra.get("psychologyExitBias"))

    if ctx_extra.get("projectedMaxTp"):
        capped = cap_modest_peak_stage_plan(
            {
                "projectedMaxTp": ctx_extra.get("projectedMaxTp"),
                "stageSize": ctx_extra.get("stageSize"),
            },
            entry_premium,
            settings=s,
        )
        ctx_extra.update(capped)
        plan.update(capped)
        ctx_extra["exitPlan"] = plan
    return True


def modest_peak_pct_arm_thresholds(
    trade: PaperTrade,
    *,
    settings: Optional[Settings] = None,
) -> tuple[float, float, float] | None:
    """Return (arm_gain_pct, arm_min_best_points, keep_ratio) when modest peak applies."""
    if not trade_uses_modest_peak_mode(trade):
        return None
    s = settings or get_settings()
    return (
        _cfg_float(s, "modest_peak_arm_gain_pct", 15.0),
        _cfg_float(s, "modest_peak_arm_min_best_points", 12.0),
        _cfg_float(s, "modest_peak_keep_ratio", 0.75),
    )
