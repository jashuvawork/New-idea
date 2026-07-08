"""Chart-driven SL/TP/trailing — fib, pivots, SMC/ICT, MTF consensus for all trade types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import ChartAnalysis, PaperTrade, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

_BULLISH_PATTERNS = frozenset({
    "bullish_engulfing", "morning_star", "three_white_soldiers", "hammer", "marubozu_bull",
})
_BEARISH_PATTERNS = frozenset({
    "bearish_engulfing", "evening_star", "three_black_crows", "shooting_star", "marubozu_bear",
})


@dataclass
class ChartExitLevels:
    stopPoints: float
    targetPoints: float
    targetPoints2: float = 0.0
    trailArmPoints: float = 3.0
    trailKeepRatio: float = 0.60
    trailStepPoints: float = 2.0
    microTargetPoints: float = 2.0
    confidence: float = 50.0
    promoteToTrailing: bool = False
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChartExitLevels":
        return cls(
            stopPoints=float(data.get("stopPoints", 3.0)),
            targetPoints=float(data.get("targetPoints", 6.0)),
            targetPoints2=float(data.get("targetPoints2", 0.0)),
            trailArmPoints=float(data.get("trailArmPoints", 3.0)),
            trailKeepRatio=float(data.get("trailKeepRatio", 0.60)),
            trailStepPoints=float(data.get("trailStepPoints", 2.0)),
            microTargetPoints=float(data.get("microTargetPoints", 2.0)),
            confidence=float(data.get("confidence", 50.0)),
            promoteToTrailing=bool(data.get("promoteToTrailing", False)),
            sources=list(data.get("sources") or []),
        )


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _pattern_side(name: str) -> Optional[str]:
    n = (name or "").lower().replace(" ", "_")
    if any(p in n for p in _BULLISH_PATTERNS) or "bull" in n:
        return "CALL"
    if any(p in n for p in _BEARISH_PATTERNS) or "bear" in n:
        return "PUT"
    return None


def chart_trade_confidence(
    snap: SymbolSnapshot,
    side: Side | str,
) -> tuple[float, list[str]]:
    """0–100 confidence from MTF + fib/pivot/SMC/patterns on snapshot chartAnalysis."""
    settings = get_settings()
    if not settings.chart_exit_levels_enabled:
        return 50.0, []

    side_v = _side_val(side)
    target_bias = "BULLISH" if side_v == "CALL" else "BEARISH"
    analysis = snap.chartAnalysis
    if not analysis:
        return 50.0, []

    score = 42.0
    sources: list[str] = []

    consensus = (analysis.consensus or "NEUTRAL").upper()
    if consensus == target_bias:
        score += 18
        sources.append(f"mtf_{consensus.lower()}")
    elif consensus == "NEUTRAL":
        score += 6
    else:
        score -= 8

    total = max(analysis.totalTimeframes, 1)
    align_ratio = (analysis.alignedCount or 0) / total
    score += align_ratio * 12
    if align_ratio >= 0.6:
        sources.append(f"mtf_align_{analysis.alignedCount}/{total}")

    inst = analysis.institutional or {}
    structure = (inst.get("structure") or "NEUTRAL").upper()
    if structure == target_bias:
        score += 14
        sources.append(f"smc_{structure.lower()}")
    if inst.get("displacement"):
        score += 8
        sources.append("smc_displacement")
    if inst.get("bos") and target_bias in str(inst.get("bos", "")).upper():
        score += 10
        sources.append(str(inst["bos"]))
    stop_hunt = str(inst.get("stopHunt") or "")
    if side_v == "PUT" and "sell_side" in stop_hunt:
        score += 12
        sources.append("stop_hunt_sell_side")
    elif side_v == "CALL" and "buy_side" in stop_hunt:
        score += 12
        sources.append("stop_hunt_buy_side")

    ich = analysis.ichimoku or {}
    cloud = (ich.get("cloudBias") or "NEUTRAL").upper()
    if cloud == target_bias:
        score += 8
        sources.append(f"ichimoku_{cloud.lower()}")

    fib = analysis.fibonacci or {}
    zone = (fib.get("zone") or "NEUTRAL").upper()
    if side_v == "PUT" and zone in ("PREMIUM", "EQUILIBRIUM"):
        score += 6
        sources.append(f"fib_{zone.lower()}")
    elif side_v == "CALL" and zone in ("DISCOUNT", "EQUILIBRIUM"):
        score += 6
        sources.append(f"fib_{zone.lower()}")

    for pat in analysis.patterns or []:
        p_side = _pattern_side(str(pat.get("name", "")))
        strength = float(pat.get("strength") or 0)
        if p_side == side_v:
            score += min(10, 4 + strength * 4)
            sources.append(f"pattern_{pat.get('name')}")

    smt = analysis.smtDivergence or {}
    if smt.get("signal"):
        sig = str(smt["signal"]).upper()
        if (side_v == "PUT" and "BEARISH" in sig) or (side_v == "CALL" and "BULLISH" in sig):
            score += 10
            sources.append("smt_divergence")

    tqs = float(snap.tradeQualityScore or 50)
    score += (tqs - 50) * 0.15

    return round(min(95.0, max(20.0, score)), 1), sources[:12]


def _index_dist_to_premium_pts(
    spot: float,
    index_distance: float,
    entry_premium: float,
) -> float:
    """Rough ATM option sensitivity: index move → premium points."""
    if spot <= 0 or index_distance <= 0:
        return 0.0
    pct = index_distance / spot
    leverage = max(1.8, min(4.5, entry_premium / 40.0))
    return max(1.0, pct * spot * 0.45 * leverage / max(spot * 0.001, 1.0))


def _structure_stop_pts(
    side_v: str,
    spot: float,
    analysis: ChartAnalysis,
    entry_premium: float,
) -> Optional[float]:
    """SL distance from nearest opposing pivot/fib structure."""
    if spot <= 0:
        return None
    pivots = analysis.pivots or {}
    candidates: list[float] = []

    if side_v == "PUT":
        for key in ("R1", "R2", "P"):
            lvl = pivots.get(key)
            if lvl and float(lvl) > spot:
                candidates.append(float(lvl) - spot)
        fib = analysis.fibonacci or {}
        retr = fib.get("retracement") or {}
        for price in retr.values():
            p = float(price)
            if p > spot:
                candidates.append(p - spot)
    else:
        for key in ("S1", "S2", "P"):
            lvl = pivots.get(key)
            if lvl and float(lvl) < spot:
                candidates.append(spot - float(lvl))
        fib = analysis.fibonacci or {}
        retr = fib.get("retracement") or {}
        for price in retr.values():
            p = float(price)
            if p < spot:
                candidates.append(spot - p)

    if not candidates:
        return None
    return _index_dist_to_premium_pts(spot, min(candidates), entry_premium)


def _structure_target_pts(
    side_v: str,
    spot: float,
    analysis: ChartAnalysis,
    entry_premium: float,
) -> tuple[float, float]:
    """TP1/TP2 from fib extension + pivot targets in trade direction."""
    pivots = analysis.pivots or {}
    ext = analysis.fibExtension or {}
    t1_candidates: list[float] = []
    t2_candidates: list[float] = []

    if side_v == "PUT":
        for key in ("S1", "S2", "S3"):
            lvl = pivots.get(key)
            if lvl and float(lvl) < spot:
                t1_candidates.append(spot - float(lvl))
        for price in ext.values():
            p = float(price)
            if p < spot:
                t2_candidates.append(spot - p)
    else:
        for key in ("R1", "R2", "R3"):
            lvl = pivots.get(key)
            if lvl and float(lvl) > spot:
                t1_candidates.append(float(lvl) - spot)
        for price in ext.values():
            p = float(price)
            if p > spot:
                t2_candidates.append(p - spot)

    tp1 = _index_dist_to_premium_pts(spot, min(t1_candidates), entry_premium) if t1_candidates else 0.0
    tp2 = _index_dist_to_premium_pts(spot, min(t2_candidates), entry_premium) if t2_candidates else 0.0
    return tp1, tp2


def compute_chart_exit_levels(
    snap: SymbolSnapshot,
    side: Side | str,
    entry_premium: float,
    *,
    base_stop: float = 3.0,
    base_target: float = 6.0,
    base_trail_arm: float = 3.0,
    base_trail_keep: float = 0.60,
    base_micro: float = 2.0,
) -> ChartExitLevels:
    """Multi-chart SL/TP/trail with confidence-weighted blending."""
    settings = get_settings()
    confidence, sources = chart_trade_confidence(snap, side)
    side_v = _side_val(side)
    spot = float(snap.spot or snap.atmStrike or 0)

    stop = base_stop
    target = base_target
    target2 = base_target * 1.5
    trail_arm = base_trail_arm
    trail_keep = base_trail_keep
    trail_step = settings.scalp_trail_step_points
    micro = base_micro

    analysis = snap.chartAnalysis
    if analysis and spot > 0:
        struct_sl = _structure_stop_pts(side_v, spot, analysis, entry_premium)
        if struct_sl:
            stop = struct_sl * 1.08
            sources.append("chart_structure_sl")
        tp1, tp2 = _structure_target_pts(side_v, spot, analysis, entry_premium)
        if tp1 > 0:
            target = max(target, tp1 * 0.92)
            sources.append("chart_pivot_tp1")
        if tp2 > 0:
            target2 = max(target * 1.2, tp2 * 0.88)
            sources.append("chart_fib_tp2")

    conf_factor = confidence / 100.0
    stop = stop * (1.05 - conf_factor * 0.12)
    target = target * (1.0 + conf_factor * 0.35)
    target2 = target2 * (1.0 + conf_factor * 0.25)
    trail_arm = max(1.5, trail_arm * (1.0 - conf_factor * 0.2))
    trail_keep = min(0.78, trail_keep + conf_factor * 0.12)
    micro = max(1.5, micro * (1.0 + conf_factor * 0.15))

    promote = (
        confidence >= settings.quick_trail_promote_min_confidence
        or confidence >= settings.all_day_min_chart_confidence
    )

    stop_floor = settings.scalp_stop_min_points
    stop_cap = max(8.0, entry_premium * 0.12)
    return ChartExitLevels(
        stopPoints=round(min(stop_cap, max(stop_floor, stop)), 2),
        targetPoints=round(max(base_target * 0.9, target), 2),
        targetPoints2=round(max(target, target2), 2),
        trailArmPoints=round(trail_arm, 2),
        trailKeepRatio=round(trail_keep, 2),
        trailStepPoints=round(trail_step, 2),
        microTargetPoints=round(micro, 2),
        confidence=confidence,
        promoteToTrailing=promote,
        sources=sources,
    )


def merge_chart_into_exit_plan(
    plan_dict: dict[str, Any],
    snap: SymbolSnapshot,
    side: Side | str,
    entry_premium: float,
) -> dict[str, Any]:
    """Blend chart levels into an adaptive exit plan dict."""
    settings = get_settings()
    if not settings.chart_exit_levels_enabled or not snap.chartAnalysis:
        return plan_dict

    levels = compute_chart_exit_levels(
        snap,
        side,
        entry_premium,
        base_stop=float(plan_dict.get("stopPoints", 3.0)),
        base_target=float(plan_dict.get("targetPoints", 6.0)),
        base_trail_arm=float(plan_dict.get("trailArmPoints", 3.0)),
        base_trail_keep=float(plan_dict.get("trailKeepRatio", 0.60)),
        base_micro=float(plan_dict.get("microTargetPoints", 2.0)),
    )
    weight = min(0.72, 0.35 + levels.confidence / 200.0)

    merged = dict(plan_dict)
    for key in (
        "stopPoints", "targetPoints", "trailArmPoints", "trailKeepRatio",
        "trailStepPoints", "microTargetPoints",
    ):
        base_val = float(plan_dict.get(key, getattr(levels, key)))
        chart_val = float(getattr(levels, key))
        merged[key] = round(base_val * (1 - weight) + chart_val * weight, 2)

    merged["targetPoints2"] = levels.targetPoints2
    merged["chartConfidence"] = levels.confidence
    merged["chartExitSources"] = levels.sources
    merged["promoteToTrailing"] = levels.promoteToTrailing
    reasoning = list(merged.get("reasoning") or [])
    reasoning.append(f"Chart exit conf {levels.confidence:.0f}% — {', '.join(levels.sources[:4])}")
    merged["reasoning"] = reasoning
    merged["chartExitLevels"] = levels.to_dict()
    return merged


def high_quality_chart_entry(
    snap: SymbolSnapshot,
    side: Side | str,
    trade_score: float,
) -> tuple[bool, float]:
    """All-day entry when chart confidence + rank are high."""
    settings = get_settings()
    if not settings.all_day_high_quality_enabled:
        return False, 0.0
    conf, _ = chart_trade_confidence(snap, side)
    ok = conf >= settings.all_day_min_chart_confidence and trade_score >= settings.all_day_min_rank_score
    return ok, conf


def should_promote_quick_to_trailing(
    trade: PaperTrade,
    snap: Optional[SymbolSnapshot] = None,
    *,
    best_pts: float = 0.0,
    live_velocity: float = 0.0,
) -> bool:
    """Quick/slow_bounce → trailing when chart or momentum supports continuation."""
    settings = get_settings()
    ctx = trade.entryContext or {}
    chart_ctx = ctx.get("chartExitLevels") or {}
    conf = float(chart_ctx.get("confidence") or ctx.get("chartConfidence") or 0)

    if chart_ctx.get("promoteToTrailing") or ctx.get("promoteToTrailing"):
        return True
    if conf >= settings.quick_trail_promote_min_confidence:
        return True
    if best_pts >= settings.quick_trail_promote_min_best_points and live_velocity >= 0.8:
        return True
    if snap and snap.chartAnalysis:
        live_conf, _ = chart_trade_confidence(snap, trade.side)
        if live_conf >= settings.quick_trail_promote_min_confidence:
            return True
    return False


def refresh_open_trade_chart_plan(
    trade: PaperTrade,
    snap: SymbolSnapshot,
) -> dict[str, Any]:
    """Re-analyse open trade exits from live snapshot chartAnalysis."""
    settings = get_settings()
    if not settings.chart_exit_levels_enabled:
        return (trade.entryContext or {}).get("exitPlan") or {}

    ctx = trade.entryContext or {}
    last = ctx.get("chartExitRefreshedAt")
    if last:
        try:
            ts = datetime.fromisoformat(str(last))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            elapsed = (datetime.now(IST) - ts.astimezone(IST)).total_seconds()
            if elapsed < settings.chart_exit_refresh_seconds:
                return ctx.get("exitPlan") or {}
        except (TypeError, ValueError):
            pass

    plan_dict = dict(ctx.get("exitPlan") or {})
    if not plan_dict:
        plan_dict = {
            "stopPoints": settings.scalp_stop_points,
            "targetPoints": settings.scalp_target_points,
            "trailArmPoints": settings.scalp_trail_arm_points,
            "trailKeepRatio": settings.scalp_trail_keep_ratio,
            "trailStepPoints": settings.scalp_trail_step_points,
            "microTargetPoints": settings.enhanced_micro_target_points,
        }

    merged = merge_chart_into_exit_plan(
        plan_dict, snap, trade.side, float(trade.entryPremium or 50),
    )
    if trade.entryContext is None:
        trade.entryContext = {}
    trade.entryContext["exitPlan"] = merged
    trade.entryContext["chartExitLevels"] = merged.get("chartExitLevels")
    trade.entryContext["chartConfidence"] = merged.get("chartConfidence")
    trade.entryContext["promoteToTrailing"] = merged.get("promoteToTrailing")
    trade.entryContext["chartExitRefreshedAt"] = datetime.now(IST).isoformat()
    return merged
