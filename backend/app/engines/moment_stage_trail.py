"""Moment stage trail ladder — divide flat→vertical projections into staged SL trails.

Example (SENSEX PE flat~200 → vertical toward ~440–500):
  projectedMaxTp ≈ 440, stageSize ≈ 50
  best hits +250 → trail floor ~+225
  best hits +400 → trail floor ~+350
  hold toward +440 while above the stage floor

Uses FVG / fib TP2 / base→entry extension / velocity·volume to project max TP.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Optional

from app.config import Settings, get_settings
from app.models.schemas import PaperTrade, Side, StrategyType


def _trade_side_value(trade: PaperTrade) -> str:
    side = trade.side
    return str(getattr(side, "value", side) or "").upper()


def _local_observed_best(trade: PaperTrade, pnl_pts: float = 0.0) -> float:
    entry = _safe_float(getattr(trade, "entryPremium", 0))
    max_ltp = _safe_float(getattr(trade, "maxLtp", 0))
    observed = max(0.0, max_ltp - entry) if max_ltp > 0 and entry > 0 else 0.0
    return max(_safe_float(getattr(trade, "bestPnlPoints", 0)), _safe_float(pnl_pts), observed)


def _best_gain_pct(trade: PaperTrade, best_pts: float) -> float:
    entry = _safe_float(getattr(trade, "entryPremium", 0))
    best_pts = _safe_float(best_pts)
    if entry <= 0 or best_pts <= 0:
        return 0.0
    return best_pts / entry * 100.0


def _best_pts_from_gain_pct(trade: PaperTrade, gain_pct: float) -> float:
    entry = _safe_float(getattr(trade, "entryPremium", 0))
    gain_pct = _safe_float(gain_pct)
    if entry <= 0 or gain_pct <= 0:
        return 0.0
    return entry * gain_pct / 100.0


def cycle_moment_group_key(trade: PaperTrade) -> tuple[str, str, str] | None:
    ctx = trade.entryContext or {}
    cycle_id = str(ctx.get("entryCycleId") or "").strip()
    if not cycle_id:
        return None
    symbol = str(trade.symbol or "").upper()
    side = _trade_side_value(trade)
    if not symbol or not side:
        return None
    return cycle_id, symbol, side


def sync_cycle_moment_peaks(trades: Iterable[PaperTrade], *, settings: Settings | None = None) -> None:
    """Share the best observed peak across same-cycle max-profit explosion legs."""
    s = settings or get_settings()
    if not bool(getattr(s, "cycle_moment_peak_sync_enabled", True)):
        return

    groups: dict[tuple[str, str, str], list[PaperTrade]] = {}
    for trade in trades:
        if getattr(trade, "status", "OPEN") != "OPEN":
            continue
        if trade.strategyType != StrategyType.EXPLOSIVE:
            continue
        key = cycle_moment_group_key(trade)
        if key is None:
            continue
        ctx = trade.entryContext or {}
        if not (
            ctx.get("maxProfitCapture")
            or trade_uses_moment_stage_ladder(trade)
        ):
            continue
        groups.setdefault(key, []).append(trade)

    for group in groups.values():
        peak_pct = max(
            _best_gain_pct(trade, _local_observed_best(trade)) for trade in group
        )
        min_sync = _cfg_float(s, "cycle_moment_peak_sync_min_gain_pct", 50.0)
        if peak_pct < min_sync:
            continue
        for trade in group:
            ctx = dict(trade.entryContext or {})
            prev = _safe_float(ctx.get("cycleMomentBestGainPct"))
            if peak_pct + 1e-9 >= prev:
                ctx["cycleMomentBestGainPct"] = round(peak_pct, 3)
                trade.entryContext = ctx


def effective_best_pnl(trade: PaperTrade, pnl_pts: float = 0.0) -> float:
    """Best gain for exit floors — local peak plus same-cycle sibling %-gain peak."""
    ctx = trade.entryContext or {}
    cycle_pts = _best_pts_from_gain_pct(
        trade, _safe_float(ctx.get("cycleMomentBestGainPct"))
    )
    return max(_local_observed_best(trade, pnl_pts), cycle_pts)


def moment_stage_near_complete(
    trade: PaperTrade,
    best: float,
    stage_size: float,
    *,
    settings: Settings | None = None,
) -> bool:
    """True when a max-profit leg reached most of stage 1 without clearing absolute stageSize."""
    s = settings or get_settings()
    stage = _safe_float(stage_size)
    best = _safe_float(best)
    if stage <= 0 or best <= 0:
        return False
    ctx = trade.entryContext or {}
    if not bool(ctx.get("maxProfitCapture")):
        return False
    frac = _cfg_float(s, "moment_stage_near_complete_frac", 0.82)
    return best < stage and best >= stage * max(0.0, min(1.0, frac))


def trade_uses_moment_stage_ladder(trade: PaperTrade) -> bool:
    ctx = trade.entryContext or {}
    if ctx.get("momentStageLadder") or (ctx.get("exitPlan") or {}).get("momentStageLadder"):
        return True
    moment = str(ctx.get("momentType") or "").lower()
    if moment in (
        "first_lift_local_base",
        "flat_then_vertical",
        "mega_rip",
        "premium_fvg",
    ):
        return True
    return bool(
        ctx.get("ictFirstLift")
        or ctx.get("firstLiftCapture")
        or ctx.get("ictFlatThenVertical")
        or ctx.get("ictMegaRip")
        or ctx.get("maxProfitCapture")
        or ctx.get("defensiveBaseRip")
    )


def _cfg_float(settings: Any, name: str, default: float) -> float:
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


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    return x


def compute_projected_max_tp(
    *,
    entry_premium: float,
    base_premium: float = 0.0,
    exit_plan: Optional[dict] = None,
    velocity_3s: float = 0.0,
    volume_surge: float = 1.0,
    session_move_pct: float = 0.0,
    premium_fvg: bool = False,
    flat_then_vertical: bool = False,
    mega_rip: bool = False,
    max_profit: bool = False,
    settings: Optional[Settings] = None,
) -> float:
    """Project max take-profit points for this moment from structure + heat."""
    s = settings or get_settings()
    plan = exit_plan or {}
    entry = max(_safe_float(entry_premium), 1e-6)
    base = _safe_float(base_premium)
    already_from_base = max(0.0, entry - base) if base > 0 else 0.0

    fib_tp2 = max(
        _safe_float(plan.get("entryTargetPoints2") or plan.get("targetPoints2")),
        _safe_float(plan.get("entryTargetPoints") or plan.get("targetPoints")),
    )

    # Flat→vertical: extend the base→entry leg (ICT displacement projection).
    ext_mult = _cfg_float(s, "moment_stage_base_extension_mult", 3.0)
    if mega_rip:
        ext_mult = max(ext_mult, _cfg_float(s, "moment_stage_mega_extension_mult", 4.0))
    if premium_fvg:
        ext_mult = max(ext_mult, ext_mult * 1.1)
    structure_proj = already_from_base * ext_mult if already_from_base > 0 else 0.0

    # Velocity / volume heat can stretch the ceiling on confirmed awakenings.
    heat = 1.0
    v3 = _safe_float(velocity_3s)
    vol = max(_safe_float(volume_surge, 1.0), 1.0)
    if v3 >= _cfg_float(s, "moment_stage_heat_velocity_3s", 3.0):
        heat += min(0.35, (v3 - 3.0) * 0.04)
    if vol >= _cfg_float(s, "moment_stage_heat_volume_surge", 1.8):
        heat += min(0.25, (vol - 1.8) * 0.08)
    if session_move_pct >= 80:
        heat += 0.1
    elif session_move_pct >= 40:
        heat += 0.05
    structure_proj *= heat

    projected = max(fib_tp2, structure_proj)

    # Early flat→vertical (entry ~50 from base ~40): already_from_base is tiny, so
    # leg-extension alone under-projects (~30–80). Project absolute premium targets
    # from base/entry multipliers so we can hold toward ~210 — and rarely ~650 LTP.
    vertical_moment = flat_then_vertical or mega_rip or premium_fvg
    parabolic = (
        v3 >= _cfg_float(s, "moment_stage_parabolic_min_velocity_3s", 8.0)
        and vol >= _cfg_float(s, "moment_stage_parabolic_min_volume_surge", 2.5)
    )
    if vertical_moment:
        base_prem_mult = _cfg_float(s, "moment_stage_base_premium_mult", 5.5)
        entry_prem_mult = _cfg_float(s, "moment_stage_entry_premium_mult", 4.2)
        if mega_rip or parabolic:
            base_prem_mult = max(
                base_prem_mult, _cfg_float(s, "moment_stage_mega_base_premium_mult", 16.0)
            )
            entry_prem_mult = max(
                entry_prem_mult, _cfg_float(s, "moment_stage_mega_entry_premium_mult", 14.0)
            )
        if parabolic:
            entry_prem_mult = max(
                entry_prem_mult,
                _cfg_float(s, "moment_stage_parabolic_entry_premium_mult", 13.0),
            )
        if premium_fvg:
            base_prem_mult *= 1.05
            entry_prem_mult *= 1.05

        abs_candidates: list[float] = []
        if base > 0:
            target_prem = base * base_prem_mult * heat
            abs_candidates.append(max(0.0, target_prem - entry))
        abs_candidates.append(max(0.0, entry * entry_prem_mult * heat - entry))

        early_frac = _cfg_float(s, "moment_stage_early_base_frac", 0.40)
        early_pts = _cfg_float(s, "moment_stage_early_max_already_points", 30.0)
        is_early = (base <= 0) or (
            already_from_base <= max(entry * early_frac, early_pts)
        )
        if is_early and (flat_then_vertical or mega_rip or parabolic):
            early_min = _cfg_float(s, "moment_stage_early_vertical_min_tp", 160.0)
            abs_candidates.append(early_min * heat)

        if abs_candidates:
            projected = max(projected, max(abs_candidates))

    if max_profit or flat_then_vertical or mega_rip:
        floor_tp = _cfg_float(s, "moment_stage_min_projected_tp", 40.0)
        if max_profit or flat_then_vertical or mega_rip:
            # Hold room for ICT runners — not a tiny 35% slice of max-profit TP.
            ict_frac = _cfg_float(s, "moment_stage_ict_target_floor_frac", 0.90)
            floor_tp = max(
                floor_tp,
                _cfg_float(s, "ict_max_profit_target_points", 180.0) * ict_frac,
            )
        projected = max(projected, floor_tp)

    # Caps: normal verticals vs mega/parabolic (50→650 needs ~12–16× entry).
    max_frac = _cfg_float(s, "moment_stage_max_tp_frac_of_premium", 12.0)
    if mega_rip or parabolic:
        max_frac = max(
            max_frac,
            _cfg_float(s, "moment_stage_mega_max_tp_frac_of_premium", 16.0),
        )
    abs_cap = _cfg_float(s, "moment_stage_max_projected_tp", 800.0)
    projected = min(projected, entry * max_frac, abs_cap)
    projected = max(projected, _cfg_float(s, "moment_stage_min_projected_tp", 40.0))
    return round(projected, 1)


def compute_stage_size(projected_max_tp: float, settings: Optional[Settings] = None) -> float:
    s = settings or get_settings()
    stages = max(4, int(_cfg_float(s, "moment_stage_count", 8)))
    min_stage = _cfg_float(s, "moment_stage_min_size", 5.0)
    max_stage = _cfg_float(s, "moment_stage_max_size", 55.0)
    raw = float(projected_max_tp) / stages
    # Prefer ~50pt stages on large projections; larger steps on mega 50→650 paths.
    if projected_max_tp >= 160:
        raw = max(raw, 40.0)
    if projected_max_tp >= 200:
        raw = max(raw, 45.0)
    if projected_max_tp >= 400:
        raw = max(raw, 50.0)
        max_stage = max(max_stage, 75.0)
    return round(min(max_stage, max(min_stage, raw)), 1)


def build_moment_stage_plan(
    *,
    entry_premium: float,
    base_premium: float = 0.0,
    exit_plan: Optional[dict] = None,
    velocity_3s: float = 0.0,
    volume_surge: float = 1.0,
    session_move_pct: float = 0.0,
    premium_fvg: bool = False,
    flat_then_vertical: bool = False,
    mega_rip: bool = False,
    max_profit: bool = False,
    settings: Optional[Settings] = None,
) -> Optional[dict[str, Any]]:
    """Build entry stamp for the stage ladder, or None if disabled / too small."""
    s = settings or get_settings()
    if not bool(getattr(s, "moment_stage_trail_enabled", True)):
        return None
    if not (flat_then_vertical or mega_rip or premium_fvg or max_profit):
        return None

    projected = compute_projected_max_tp(
        entry_premium=entry_premium,
        base_premium=base_premium,
        exit_plan=exit_plan,
        velocity_3s=velocity_3s,
        volume_surge=volume_surge,
        session_move_pct=session_move_pct,
        premium_fvg=premium_fvg,
        flat_then_vertical=flat_then_vertical,
        mega_rip=mega_rip,
        max_profit=max_profit,
        settings=s,
    )
    min_proj = _cfg_float(s, "moment_stage_min_projected_tp", 40.0)
    if projected < min_proj:
        return None

    stage_size = compute_stage_size(projected, s)
    return {
        "momentStageLadder": True,
        "projectedMaxTp": projected,
        "stageSize": stage_size,
        "stageGivebackRatio": round(_cfg_float(s, "moment_stage_giveback_ratio", 0.50), 3),
        "stageLateGivebackRatio": round(
            _cfg_float(s, "moment_stage_late_giveback_ratio", 1.0), 3
        ),
        "stageLateProgress": round(_cfg_float(s, "moment_stage_late_progress", 0.70), 3),
    }


def _ladder_fields(trade: PaperTrade) -> dict[str, Any]:
    ctx = trade.entryContext or {}
    plan = ctx.get("exitPlan") or {}
    out: dict[str, Any] = {}
    for key in (
        "momentStageLadder",
        "projectedMaxTp",
        "stageSize",
        "stageGivebackRatio",
        "stageLateGivebackRatio",
        "stageLateProgress",
        "stageTrailFloorPts",
        "stageLevelPts",
    ):
        if key in ctx and ctx[key] is not None:
            out[key] = ctx[key]
        elif key in plan and plan[key] is not None:
            out[key] = plan[key]
    return out


def _live_velocity_3s(trade: PaperTrade) -> float:
    ctx = trade.entryContext or {}
    return _safe_float(ctx.get("liveVelocity3s") or ctx.get("velocity3s"))


def maybe_extend_projected_max(trade: PaperTrade, best: float, settings: Optional[Settings] = None) -> float:
    """If the rip exceeds the projection, ratchet the ceiling so stages continue.

    Hot mega rips (50→650) keep more headroom so hard-TP / late squeeze cannot
    cut a still-expanding vertical at a stale ~200–500 ceiling.
    """
    s = settings or get_settings()
    fields = _ladder_fields(trade)
    projected = _safe_float(fields.get("projectedMaxTp"))
    if projected <= 0:
        return 0.0
    best = _safe_float(best)
    if best <= projected * _cfg_float(s, "moment_stage_extend_trigger_frac", 0.92):
        from app.engines.peak_prediction import ratchet_toward_predicted_peak

        peak_pts = ratchet_toward_predicted_peak(trade, best, settings=s)
        return max(projected, peak_pts)

    stage = max(_safe_float(fields.get("stageSize")), _cfg_float(s, "moment_stage_min_size", 5.0))
    # Grow stage size as the runner becomes a mega path.
    if best >= 400:
        stage = max(stage, 50.0)
    headroom_stages = _cfg_float(s, "moment_stage_extend_stages", 2.0)
    live_v = _live_velocity_3s(trade)
    hot = live_v >= _cfg_float(s, "moment_stage_extend_hot_velocity_3s", 2.5)
    ctx = trade.entryContext or {}
    mega = bool(ctx.get("ictMegaRip") or ctx.get("momentType") == "mega_rip")
    if hot or mega or best >= 300:
        headroom_stages = max(
            headroom_stages, _cfg_float(s, "moment_stage_extend_hot_stages", 4.0)
        )
    extended = round(max(projected, best + stage * headroom_stages), 1)
    abs_cap = _cfg_float(s, "moment_stage_max_projected_tp", 800.0)
    extended = min(extended, abs_cap)
    if trade.entryContext is None:
        trade.entryContext = {}
    trade.entryContext["projectedMaxTp"] = extended
    if stage > _safe_float(fields.get("stageSize")):
        trade.entryContext["stageSize"] = round(stage, 1)
    plan = dict(trade.entryContext.get("exitPlan") or {})
    plan["projectedMaxTp"] = extended
    if stage > _safe_float(fields.get("stageSize")):
        plan["stageSize"] = round(stage, 1)
    trade.entryContext["exitPlan"] = plan
    from app.engines.peak_prediction import ratchet_toward_predicted_peak

    peak_pts = ratchet_toward_predicted_peak(trade, best, settings=s)
    return max(extended, peak_pts)


def stage_trail_floor_pts(
    trade: PaperTrade,
    best: float,
    *,
    settings: Optional[Settings] = None,
) -> Optional[float]:
    """Ratcheting stage trail floor from completed stages of the projected move."""
    s = settings or get_settings()
    if not bool(getattr(s, "moment_stage_trail_enabled", True)):
        return None
    if not trade_uses_moment_stage_ladder(trade):
        return None

    fields = _ladder_fields(trade)
    projected = maybe_extend_projected_max(trade, best, s)
    if projected <= 0:
        projected = _safe_float(fields.get("projectedMaxTp"))
    stage = _safe_float(fields.get("stageSize"))
    if projected <= 0 or stage <= 0:
        return None

    best = _safe_float(best)
    ctx = trade.entryContext or {}
    if best < stage:
        if moment_stage_near_complete(trade, best, stage, settings=s):
            keep = _cfg_float(s, "ftv_runner_pct_trail_keep_ratio", 0.75)
            floor_pts = round(max(_cfg_float(s, "moment_stage_min_remain_points", 1.0), best * keep), 2)
            prev = _safe_float(ctx.get("stageTrailFloorPts"))
            if prev > 0:
                floor_pts = max(floor_pts, prev)
            ctx = dict(ctx)
            ctx["stageTrailFloorPts"] = floor_pts
            ctx["stageLevelPts"] = round(stage, 2)
            ctx["projectedMaxTp"] = round(projected, 1)
            plan = dict(ctx.get("exitPlan") or {})
            plan["stageTrailFloorPts"] = floor_pts
            plan["stageLevelPts"] = round(stage, 2)
            plan["projectedMaxTp"] = round(projected, 1)
            ctx["exitPlan"] = plan
            trade.entryContext = ctx
            return floor_pts
        return None

    stages_hit = int(best // stage)
    stage_level = stages_hit * stage
    # Never trail past the projected max — leave room to tag the ceiling.
    stage_level = min(stage_level, projected)

    giveback_ratio = _safe_float(
        fields.get("stageGivebackRatio"),
        _cfg_float(s, "moment_stage_giveback_ratio", 0.50),
    )
    late_ratio = _safe_float(
        fields.get("stageLateGivebackRatio"),
        _cfg_float(s, "moment_stage_late_giveback_ratio", 1.0),
    )
    late_progress = _safe_float(
        fields.get("stageLateProgress"),
        _cfg_float(s, "moment_stage_late_progress", 0.70),
    )
    progress = stage_level / max(projected, 1e-9)
    live_v = _live_velocity_3s(trade)
    hot_hold = live_v >= _cfg_float(s, "moment_stage_hot_hold_velocity_3s", 2.5)
    # Still expanding (50→650 path) — do not squeeze; keep normal stage giveback.
    # When heat dies, late progress can widen giveback / lock the stage.
    if progress >= late_progress and not hot_hold:
        giveback_ratio = max(giveback_ratio, late_ratio)
    elif hot_hold and best >= 200:
        # Hot mega: allow a full stage of pullback room so we don't trail out mid-rip.
        giveback_ratio = max(giveback_ratio, late_ratio)

    giveback = stage * giveback_ratio
    floor_pts = stage_level - giveback
    # Keep a small green cushion after the first stage.
    min_remain = _cfg_float(s, "moment_stage_min_remain_points", 1.0)
    floor_pts = max(floor_pts, min_remain)

    # Ratchet only upward.
    ctx = dict(trade.entryContext or {})
    prev = ctx.get("stageTrailFloorPts")
    if prev is not None:
        floor_pts = max(floor_pts, _safe_float(prev))
    floor_pts = round(floor_pts, 2)
    ctx["stageTrailFloorPts"] = floor_pts
    ctx["stageLevelPts"] = round(stage_level, 2)
    ctx["projectedMaxTp"] = round(projected, 1)
    plan = dict(ctx.get("exitPlan") or {})
    plan["stageTrailFloorPts"] = floor_pts
    plan["stageLevelPts"] = round(stage_level, 2)
    plan["projectedMaxTp"] = round(projected, 1)
    ctx["exitPlan"] = plan
    trade.entryContext = ctx
    return floor_pts


def pre_stage_hold_floor_pts(
    trade: PaperTrade,
    best: float,
    *,
    settings: Optional[Settings] = None,
) -> Optional[float]:
    """Wide provisional floor before the first stage completes.

    Without this, the best−3.5pt step trail owns the 0→stageSize window and
    cuts continuing ICT rips on normal dips (SENSEX PUT 392 best+43 → exit+37
    while LTP ran to ~500).
    """
    s = settings or get_settings()
    if not bool(getattr(s, "moment_stage_trail_enabled", True)):
        return None
    if not bool(getattr(s, "explosion_trail_pre_stage_suppress_step", True)):
        return None
    if not trade_uses_moment_stage_ladder(trade):
        return None

    from app.engines.modest_peak_mode import trade_uses_modest_peak_mode

    if (
        trade_uses_modest_peak_mode(trade)
        and bool(getattr(s, "modest_peak_suppress_pre_stage_wide_floor", True))
    ):
        return None

    fields = _ladder_fields(trade)
    stage = _safe_float(fields.get("stageSize"))
    if stage <= 0:
        return None

    best = _safe_float(best)
    arm = _cfg_float(s, "explosion_trail_arm_points", 4.0)
    if best < arm:
        return None
    # First stage completed — real stage floors take over.
    if best >= stage:
        return None

    giveback_ratio = _safe_float(
        fields.get("stageGivebackRatio"),
        _cfg_float(s, "moment_stage_giveback_ratio", 0.50),
    )
    live_v = _live_velocity_3s(trade)
    hot = live_v >= _cfg_float(s, "moment_stage_hot_hold_velocity_3s", 2.5)
    if hot:
        # Still expanding — allow a full stage of pullback room.
        giveback_ratio = max(
            giveback_ratio, _cfg_float(s, "moment_stage_late_giveback_ratio", 1.0)
        )

    giveback = stage * giveback_ratio
    min_remain = _cfg_float(s, "moment_stage_min_remain_points", 1.0)
    floor_pts = max(min_remain, best - giveback)
    return round(floor_pts, 2)


def ftv_runner_pct_floor(
    trade: PaperTrade,
    best: float,
    *,
    settings: Optional[Settings] = None,
) -> Optional[float]:
    """Trail a consistent fraction BEHIND the peak GAIN for V/FTV runners.

    V/FTV moments run in large % off the local base. The absolute stage ladder is tuned for
    mega POINT moves and under-protects modest-but-real % moves (a +40% peak can give back to
    +4%). This locks in a fixed fraction of whatever peak the move reached (keep 72% => exit
    ~28% off the top), so every real % move banks close to its best TP. Arms only after a
    real move so it never clips the initial base pad.
    """
    s = settings or get_settings()
    if not bool(getattr(s, "ftv_runner_pct_trail_enabled", True)):
        return None
    if not trade_uses_moment_stage_ladder(trade):
        return None
    entry = _safe_float(getattr(trade, "entryPremium", 0))
    best = _safe_float(best)
    if entry <= 0 or best <= 0:
        return None
    arm_pct = _cfg_float(s, "ftv_runner_pct_trail_arm_pct", 25.0)
    gain_pct = best / entry * 100.0
    ctx = getattr(trade, "entryContext", None) or {}
    arm_min_pts = _cfg_float(s, "ftv_runner_pct_trail_arm_min_best_points", 20.0)
    max_profit = bool(ctx.get("maxProfitCapture"))
    keep = _cfg_float(s, "ftv_runner_pct_trail_keep_ratio", 0.75)
    from app.engines.modest_peak_mode import modest_peak_pct_arm_thresholds

    modest = modest_peak_pct_arm_thresholds(trade, settings=s)
    if modest is not None:
        arm_pct, arm_min_pts, keep = modest
        armed = gain_pct >= arm_pct or best >= arm_min_pts
    else:
        armed = gain_pct >= arm_pct or (max_profit and best >= arm_min_pts)
    if not armed:
        return None
    # Closed loop: prefer the LEARNED per-moment keep-ratio when EOD learning stamped one
    # (ride high-hit movers harder, tighten low-hit buckets). Bounded to a safe band.
    learned = _safe_float(ctx.get("learnedTrailKeepRatio"))
    if learned > 0 and bool(getattr(s, "eod_learning_apply_enabled", False)):
        keep = learned
    keep = min(0.95, max(0.5, keep))
    return round(best * keep, 2)


def compose_trail_floor_with_stages(
    trade: PaperTrade,
    best: float,
    base_floor: Optional[float],
    *,
    settings: Optional[Settings] = None,
) -> tuple[Optional[float], Optional[float]]:
    """Return (composed_floor, stage_floor).

    While the stage ladder is active, the stage floor *owns* the trail.
    Otherwise a best−step ratchet (~3.5pt) would stop a 250→400 rip on a
    normal pullback long before the 225/350 stage floors.

    Before the first stage completes, a provisional pre-stage floor owns the
    trail so the micro step cannot cut a still-projecting vertical.

    A %-of-peak-gain floor is max'd in so V/FTV % moves that fall between coarse
    absolute stages still bank close to their best TP (the stage ladder keeps mega
    runners riding; the pct floor locks modest-but-real moves).
    """
    s = settings or get_settings()
    pct_floor = ftv_runner_pct_floor(trade, best, settings=s)
    stage_floor = stage_trail_floor_pts(trade, best, settings=s)
    if stage_floor is not None:
        composed = stage_floor if pct_floor is None else max(stage_floor, pct_floor)
        return composed, composed
    pre_floor = pre_stage_hold_floor_pts(trade, best, settings=s)
    if pre_floor is not None:
        composed = pre_floor if pct_floor is None else max(pre_floor, pct_floor)
        return composed, composed
    if pct_floor is not None:
        composed = pct_floor if base_floor is None else max(base_floor, pct_floor)
        return composed, pct_floor
    return base_floor, None
