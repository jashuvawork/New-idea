"""TP anchor for maxProfitCapture moment-stage trades — hold through pullbacks until anchor."""

from __future__ import annotations

from typing import Any, Optional

from app.config import Settings, get_settings
from app.models.schemas import PaperTrade, Side, SymbolSnapshot


def _cfg_float(settings: Any, name: str, default: float) -> float:
    try:
        return float(getattr(settings, name, default) or default)
    except (TypeError, ValueError):
        return default


def compute_moment_capture_tp_anchor_pts(
    *,
    entry_premium: float,
    projected_max_tp: float = 0.0,
    stage_size: float = 0.0,
    plan_target_pts: float = 0.0,
    settings: Any = None,
) -> float:
    """Hold target in open PnL points before scratch exits (between-fade, tier-2 guard)."""
    s = settings or get_settings()
    entry = float(entry_premium or 0)
    if entry <= 0:
        return 0.0
    rung = _cfg_float(s, "tp_rung_ladder_min_best_to_arm_exits", 28.0)
    projected = float(projected_max_tp or 0)
    plan_tgt = float(plan_target_pts or 0)
    proj_frac = _cfg_float(s, "moment_capture_tp_anchor_projected_frac", 0.35)
    max_entry_2x = _cfg_float(s, "moment_capture_tp_anchor_2x_max_entry_premium_inr", 150.0)
    mult = _cfg_float(s, "moment_capture_tp_anchor_entry_multiple", 2.0)
    stage_frac = _cfg_float(s, "moment_capture_tp_anchor_stage_frac", 0.5)

    milestone = 0.0
    if entry <= max_entry_2x + 1e-6 and mult > 1.0:
        two_x = entry * (mult - 1.0)
        proj_slice = projected * proj_frac if projected > 0 else two_x
        milestone = min(two_x, proj_slice) if proj_slice > 0 else two_x
    elif projected > 0 or plan_tgt > 0:
        parts = [p for p in (projected * proj_frac if projected > 0 else 0.0, plan_tgt * 1.25 if plan_tgt > 0 else 0.0) if p > 0]
        milestone = min(parts) if parts else rung

    anchor = max(rung, milestone, stage_size * stage_frac if stage_size > 0 else 0.0)
    cap_frac = _cfg_float(s, "moment_capture_tp_anchor_max_projected_cap_frac", 0.85)
    if projected > 0:
        anchor = min(anchor, projected * cap_frac)
    return round(max(rung, anchor), 2)


def stamp_moment_capture_tp_anchor_on_context(
    ctx: dict[str, Any],
    *,
    entry_premium: float,
    settings: Any = None,
) -> Optional[float]:
    """Write momentCaptureTpAnchorPts (+ progress meta) on entry context / plan."""
    plan = ctx.get("exitPlan") if isinstance(ctx.get("exitPlan"), dict) else {}
    if not (
        ctx.get("maxProfitCapture")
        or ctx.get("momentStageLadder")
        or plan.get("momentStageLadder")
    ):
        return None
    projected = float(
        ctx.get("projectedMaxTp") or plan.get("projectedMaxTp") or 0.0
    )
    stage = float(ctx.get("stageSize") or plan.get("stageSize") or 0.0)
    plan_tgt = float(
        plan.get("entryTargetPoints") or plan.get("targetPoints") or 0.0
    )
    anchor = compute_moment_capture_tp_anchor_pts(
        entry_premium=entry_premium,
        projected_max_tp=projected,
        stage_size=stage,
        plan_target_pts=plan_tgt,
        settings=settings,
    )
    if anchor <= 0:
        return None
    ctx["momentCaptureTpAnchorPts"] = anchor
    ctx["momentCaptureTpAnchorMeta"] = {
        "entryPremium": round(entry_premium, 2),
        "projectedMaxTp": projected,
        "planTargetPts": plan_tgt,
        "twoXEligible": entry_premium <= _cfg_float(
            settings or get_settings(),
            "moment_capture_tp_anchor_2x_max_entry_premium_inr",
            150.0,
        ),
    }
    return anchor


def stamp_moment_capture_index_scope_on_context(
    ctx: dict[str, Any],
    *,
    symbol: str,
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    settings: Any = None,
) -> bool:
    """Stamp when entry hugged index session extreme — narrows marathon anchor hold."""
    if snap is None:
        return False
    from app.engines.index_lift_turn_guards import index_near_extreme_chase_active

    s = settings or get_settings()
    active, meta = index_near_extreme_chase_active(symbol, side, snap, settings=s)
    if not active:
        return False
    ctx["momentCaptureAnchorNearIndexExtreme"] = True
    ctx["momentCaptureAnchorNearIndexExtremeMeta"] = meta
    return True


def _scoped_anchor_hold_threshold(anchor: float, settings: Any) -> float:
    rung = _cfg_float(settings, "tp_rung_ladder_min_best_to_arm_exits", 28.0)
    min_prog_frac = _cfg_float(
        settings, "moment_capture_tp_anchor_scope_min_progress_pct", 20.0
    ) / 100.0
    min_best = _cfg_float(settings, "moment_capture_tp_anchor_scope_min_best_pts", 28.0)
    return max(rung, min_best, anchor * min_prog_frac)


def moment_capture_anchor_hold_active(
    trade: PaperTrade,
    best: float,
    settings: Any = None,
) -> bool:
    """True while best has not reached the entry TP anchor — suppress scratch exits."""
    s = settings or get_settings()
    if not bool(getattr(s, "moment_capture_tp_anchor_enabled", True)):
        return False
    from app.engines.moment_stage_trail import trade_uses_moment_stage_ladder

    ctx = trade.entryContext if trade.entryContext is not None else {}
    if trade.entryContext is None:
        trade.entryContext = ctx
    if not ctx.get("maxProfitCapture") or not trade_uses_moment_stage_ladder(trade):
        return False
    raw = ctx.get("momentCaptureTpAnchorPts")
    if raw is None:
        return False
    try:
        anchor = float(raw)
    except (TypeError, ValueError):
        return False
    if anchor <= 0:
        return False
    best_f = float(best or 0)
    ctx["momentCaptureTpAnchorProgressPct"] = round(min(100.0, (best_f / anchor) * 100.0), 1)
    trade.entryContext = ctx
    if best_f + 1e-6 >= float(anchor):
        return False
    if bool(
        getattr(s, "moment_capture_tp_anchor_scope_near_index_extreme_enabled", True)
    ) and ctx.get("momentCaptureAnchorNearIndexExtreme"):
        threshold = _scoped_anchor_hold_threshold(anchor, s)
        if best_f + 1e-6 < threshold:
            return False
    return True