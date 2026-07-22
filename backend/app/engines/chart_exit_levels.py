"""Chart-driven SL/TP/trailing — fib, pivots, Ichimoku, SMC/ICT, MTF consensus for all trade types."""

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
class ChartTrailTuning:
    """Live confidence-driven trail/SL/TP adjustments for open trades."""
    liveConfidence: float
    entryConfidence: float
    confidenceDelta: float
    trailArmPoints: float
    trailKeepRatio: float
    stopPoints: float
    targetPoints: float
    targetPoints2: float = 0.0
    tighten: bool = False
    letRun: bool = False
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    confidenceRaw: float = 50.0
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
            confidenceRaw=float(data.get("confidenceRaw", data.get("confidence", 50.0))),
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


def _cfg_float(settings: Any, name: str, default: float) -> float:
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
    # MagicMock and other stubs implement __float__ → 1.0; ignore them.
    return float(default)


def rescale_chart_confidence(raw: float, settings: Any = None) -> float:
    """
    Map uncapped chart score → display confidence on [40, 100].

    Additive chart features routinely score 150–200 before the old min(95) clamp,
    which pinned ~88% of trades at 95. Linear map raw[lo, hi] → [dmin, dmax]
    restores spread while keeping threshold comparisons equivalent when cutovers
    are transformed with the same map.
    """
    settings = settings or get_settings()
    lo = _cfg_float(settings, "chart_confidence_scale_raw_lo", 40.0)
    hi = _cfg_float(settings, "chart_confidence_scale_raw_hi", 200.0)
    dmin = _cfg_float(settings, "chart_confidence_display_min", 40.0)
    dmax = _cfg_float(settings, "chart_confidence_display_max", 100.0)
    if hi <= lo:
        return round(dmin, 1)
    t = (float(raw) - lo) / (hi - lo)
    return round(max(dmin, min(dmax, dmin + t * (dmax - dmin))), 1)


def chart_trade_confidence(
    snap: SymbolSnapshot,
    side: Side | str,
) -> tuple[float, list[str]]:
    """Display chart confidence on 40–100 from MTF + fib/pivot/SMC/patterns."""
    settings = get_settings()
    if not settings.chart_exit_levels_enabled:
        return 50.0, []

    raw, sources = _chart_trade_confidence_raw(snap, side)
    return rescale_chart_confidence(raw, settings), sources


def chart_trade_confidence_with_raw(
    snap: SymbolSnapshot,
    side: Side | str,
) -> tuple[float, float, list[str]]:
    """Return (display_confidence, raw_uncapped, sources)."""
    settings = get_settings()
    if not settings.chart_exit_levels_enabled:
        return 50.0, 50.0, []
    raw, sources = _chart_trade_confidence_raw(snap, side)
    return rescale_chart_confidence(raw, settings), round(float(raw), 1), sources


def _chart_trade_confidence_raw(
    snap: SymbolSnapshot,
    side: Side | str,
) -> tuple[float, list[str]]:
    """Uncapped additive chart score (pre-rescale)."""
    side_v = _side_val(side)
    target_bias = "BULLISH" if side_v == "CALL" else "BEARISH"
    analysis = snap.chartAnalysis
    score = 42.0
    sources: list[str] = []

    if analysis:
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
        tk = (ich.get("tkCross") or "NEUTRAL").upper()
        if tk == target_bias:
            score += 5
            sources.append(f"ichimoku_tk_{tk.lower()}")
        elif tk != "NEUTRAL" and tk != target_bias:
            score -= 4
        price_vs = (ich.get("priceVsCloud") or "").upper()
        if (side_v == "CALL" and price_vs == "ABOVE") or (side_v == "PUT" and price_vs == "BELOW"):
            score += 4
            sources.append(f"ichimoku_{price_vs.lower()}")

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

        tf_bull = tf_bear = tf_rsi_ok = tf_macd_ok = 0
        for tf_name, tf in (analysis.timeframes or {}).items():
            if not isinstance(tf, dict):
                continue
            d = str(tf.get("direction") or "NEUTRAL").upper()
            if d == "BULLISH":
                tf_bull += 1
            elif d == "BEARISH":
                tf_bear += 1
            rsi_bias = str(tf.get("rsiBias") or "").upper()
            macd_bias = str(tf.get("macdBias") or "").upper()
            if side_v == "PUT" and rsi_bias == "OVERBOUGHT":
                tf_rsi_ok += 1
            elif side_v == "CALL" and rsi_bias == "OVERSOLD":
                tf_rsi_ok += 1
            if macd_bias == target_bias:
                tf_macd_ok += 1
        if side_v == "PUT" and tf_bear >= 2:
            score += min(12, tf_bear * 3)
            sources.append(f"tf_bear_{tf_bear}")
        elif side_v == "CALL" and tf_bull >= 2:
            score += min(12, tf_bull * 3)
            sources.append(f"tf_bull_{tf_bull}")
        if tf_rsi_ok >= 2:
            score += 6
            sources.append("tf_rsi_aligned")
        if tf_macd_ok >= 3:
            score += 8
            sources.append("tf_macd_aligned")

    tqs = float(snap.tradeQualityScore or 50)
    score += (tqs - 50) * 0.15

    # 5m spot chart — RSI, MACD, EMA, momentum (always used)
    spot = snap.spotChart
    if spot:
        if spot.direction == target_bias:
            score += 10
            sources.append(f"spot_{spot.direction.lower()}")
        elif spot.direction not in ("NEUTRAL", target_bias):
            score -= 6
        if side_v == "CALL":
            if spot.rsiBias == "OVERSOLD" and spot.momentum15Pct > 0:
                score += 6
                sources.append("spot_rsi_oversold_bounce")
            elif spot.rsiBias == "OVERBOUGHT":
                score -= 5
        else:
            if spot.rsiBias == "OVERBOUGHT" and spot.momentum15Pct < 0:
                score += 6
                sources.append("spot_rsi_overbought_fade")
            elif spot.rsiBias == "OVERSOLD":
                score -= 5
        if spot.macdBias == target_bias:
            score += 5
            sources.append(f"spot_macd_{spot.macdBias.lower()}")
        if spot.emaBias == target_bias:
            score += 4
            sources.append(f"spot_ema_{spot.emaBias.lower()}")
        mom5 = abs(float(spot.momentum5Pct or 0))
        trend = float(spot.trendStrength or 0)
        if mom5 >= 0.05 and spot.direction == target_bias:
            score += min(8, mom5 * 40)
            sources.append("spot_momentum")
        if trend >= 30 and spot.direction == target_bias:
            score += min(6, trend * 0.12)
            sources.append("spot_trend")

    # Session breadth
    breadth = snap.breadth
    if breadth:
        bb = (breadth.bias or "NEUTRAL").upper()
        if bb == target_bias:
            score += 10
            sources.append(f"breadth_{bb.lower()}")
        elif bb != "NEUTRAL" and bb != target_bias:
            score -= 8

    return float(score), sources[:16]


def _resolve_index_spot(snap: SymbolSnapshot) -> float:
    """Index spot for pivot/fib structure — reject option-premium scale values."""
    candidates: list[float] = []
    if snap.spotChart and float(snap.spotChart.spot or 0) > 500:
        candidates.append(float(snap.spotChart.spot))
    for raw in (snap.spot, snap.atmStrike):
        v = float(raw or 0)
        if v > 500:
            candidates.append(v)
    return max(candidates) if candidates else 0.0


def _valid_index_structure_level(level: float, index_spot: float) -> bool:
    """Pivot/fib levels must be index-scale and near current spot."""
    if level <= 0 or index_spot <= 0:
        return False
    if index_spot > 1000 and level < 500:
        return False
    settings = get_settings()
    max_pct = float(getattr(settings, "chart_exit_max_index_structure_pct", 0.04) or 0.04)
    max_move = max(250.0, index_spot * max_pct)
    return abs(level - index_spot) <= max_move


def _clamp_chart_target_pts(
    pts: float,
    entry_premium: float,
    *,
    is_tp2: bool = False,
) -> float:
    settings = get_settings()
    cap = float(getattr(settings, "chart_exit_max_target_points", 80.0) or 80.0)
    prem_cap = max(12.0, entry_premium * (0.90 if is_tp2 else 0.65))
    return round(min(pts, cap, prem_cap), 2)


def _stamp_entry_baselines(plan_dict: dict[str, Any]) -> dict[str, Any]:
    """Freeze entry SL/TP baselines so live tuning does not compound each cycle."""
    stamped = dict(plan_dict)
    if "entryTargetPoints" not in stamped and stamped.get("targetPoints") is not None:
        stamped["entryTargetPoints"] = float(stamped["targetPoints"])
    if "entryTargetPoints2" not in stamped and stamped.get("targetPoints2") is not None:
        stamped["entryTargetPoints2"] = float(stamped["targetPoints2"])
    if "entryStopPoints" not in stamped and stamped.get("stopPoints") is not None:
        stamped["entryStopPoints"] = float(stamped["stopPoints"])
    return stamped


def _index_dist_to_premium_pts(
    index_spot: float,
    index_distance: float,
    entry_premium: float,
) -> float:
    """Rough ATM option sensitivity: index move → premium points."""
    if index_spot <= 0 or index_distance <= 0:
        return 0.0
    settings = get_settings()
    max_move = max(250.0, index_spot * float(getattr(settings, "chart_exit_max_index_structure_pct", 0.04) or 0.04))
    dist = min(index_distance, max_move)
    ratio = max(0.20, min(0.70, (entry_premium / max(index_spot, 1000.0)) * 8.0))
    return max(1.0, round(dist * ratio, 2))


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
            if lvl and float(lvl) > spot and _valid_index_structure_level(float(lvl), spot):
                candidates.append(float(lvl) - spot)
        fib = analysis.fibonacci or {}
        retr = fib.get("retracement") or {}
        for price in retr.values():
            p = float(price)
            if p > spot and _valid_index_structure_level(p, spot):
                candidates.append(p - spot)
    else:
        for key in ("S1", "S2", "P"):
            lvl = pivots.get(key)
            if lvl and float(lvl) < spot and _valid_index_structure_level(float(lvl), spot):
                candidates.append(spot - float(lvl))
        fib = analysis.fibonacci or {}
        retr = fib.get("retracement") or {}
        for price in retr.values():
            p = float(price)
            if p < spot and _valid_index_structure_level(p, spot):
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
            if lvl and float(lvl) < spot and _valid_index_structure_level(float(lvl), spot):
                t1_candidates.append(spot - float(lvl))
        for price in ext.values():
            p = float(price)
            if p < spot and _valid_index_structure_level(p, spot):
                t2_candidates.append(spot - p)
    else:
        for key in ("R1", "R2", "R3"):
            lvl = pivots.get(key)
            if lvl and float(lvl) > spot and _valid_index_structure_level(float(lvl), spot):
                t1_candidates.append(float(lvl) - spot)
        for price in ext.values():
            p = float(price)
            if p > spot and _valid_index_structure_level(p, spot):
                t2_candidates.append(p - spot)

    tp1 = _index_dist_to_premium_pts(spot, min(t1_candidates), entry_premium) if t1_candidates else 0.0
    tp2 = _index_dist_to_premium_pts(spot, min(t2_candidates), entry_premium) if t2_candidates else 0.0
    return tp1, tp2


def _ichimoku_levels(ichimoku: dict[str, Any]) -> dict[str, float]:
    """Normalize ichimoku dict values to floats."""
    out: dict[str, float] = {}
    for key in ("tenkan", "kijun", "senkouA", "senkouB", "cloudTop", "cloudBottom"):
        val = ichimoku.get(key)
        if val is not None:
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                continue
    return out


def _ichimoku_stop_pts(
    side_v: str,
    spot: float,
    ichimoku: dict[str, Any],
    entry_premium: float,
) -> Optional[float]:
    """SL from Ichimoku cloud edge / kijun / tenkan on the opposing side."""
    if spot <= 0:
        return None
    ich = _ichimoku_levels(ichimoku)
    if not ich:
        return None
    candidates: list[float] = []

    if side_v == "PUT":
        for key in ("cloudTop", "kijun", "tenkan", "senkouA", "senkouB"):
            lvl = ich.get(key, 0)
            if lvl > spot and _valid_index_structure_level(lvl, spot):
                candidates.append(lvl - spot)
    else:
        for key in ("cloudBottom", "kijun", "tenkan", "senkouA", "senkouB"):
            lvl = ich.get(key, 0)
            if 0 < lvl < spot and _valid_index_structure_level(lvl, spot):
                candidates.append(spot - lvl)

    if not candidates:
        return None
    return _index_dist_to_premium_pts(spot, min(candidates), entry_premium)


def _ichimoku_target_pts(
    side_v: str,
    spot: float,
    ichimoku: dict[str, Any],
    entry_premium: float,
) -> tuple[float, float]:
    """TP1/TP2 from Ichimoku support-resistance in trade direction."""
    if spot <= 0:
        return 0.0, 0.0
    ich = _ichimoku_levels(ichimoku)
    if not ich:
        return 0.0, 0.0

    near: list[float] = []
    far: list[float] = []

    if side_v == "PUT":
        for key in ("tenkan", "kijun", "cloudBottom"):
            lvl = ich.get(key, 0)
            if 0 < lvl < spot and _valid_index_structure_level(lvl, spot):
                near.append(spot - lvl)
        cloud_bottom = ich.get("cloudBottom", 0)
        kijun = ich.get("kijun", 0)
        if cloud_bottom > 0 and kijun > 0 and cloud_bottom < spot:
            span = max(0.0, kijun - cloud_bottom)
            proj = spot - (cloud_bottom - span)
            if proj > 0 and _valid_index_structure_level(spot - proj, spot):
                far.append(proj)
        for key in ("cloudBottom", "kijun", "tenkan"):
            lvl = ich.get(key, 0)
            if 0 < lvl < spot and _valid_index_structure_level(lvl, spot):
                far.append(spot - lvl)
    else:
        for key in ("tenkan", "kijun", "cloudTop"):
            lvl = ich.get(key, 0)
            if lvl > spot and _valid_index_structure_level(lvl, spot):
                near.append(lvl - spot)
        cloud_top = ich.get("cloudTop", 0)
        kijun = ich.get("kijun", 0)
        if cloud_top > spot and kijun > spot:
            span = max(0.0, cloud_top - kijun)
            proj = (cloud_top + span) - spot
            if _valid_index_structure_level(spot + proj, spot):
                far.append(proj)
        for key in ("cloudTop", "kijun", "tenkan"):
            lvl = ich.get(key, 0)
            if lvl > spot and _valid_index_structure_level(lvl, spot):
                far.append(lvl - spot)

    tp1 = _index_dist_to_premium_pts(spot, min(near), entry_premium) if near else 0.0
    tp2 = _index_dist_to_premium_pts(spot, max(far), entry_premium) if far else 0.0
    if tp2 > 0 and tp2 < tp1:
        tp2 = tp1 * 1.35
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
    confidence, confidence_raw, sources = chart_trade_confidence_with_raw(snap, side)
    side_v = _side_val(side)
    spot = _resolve_index_spot(snap)

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
        ich_sl = _ichimoku_stop_pts(side_v, spot, analysis.ichimoku or {}, entry_premium)
        sl_candidates = [x for x in (struct_sl, ich_sl) if x and x > 0]
        if sl_candidates:
            stop = min(sl_candidates) * 1.08
            if struct_sl:
                sources.append("chart_structure_sl")
            if ich_sl:
                sources.append("chart_ichimoku_sl")
        tp1, tp2 = _structure_target_pts(side_v, spot, analysis, entry_premium)
        ich_tp1, ich_tp2 = _ichimoku_target_pts(side_v, spot, analysis.ichimoku or {}, entry_premium)
        if ich_tp1 > 0:
            tp1 = max(tp1, ich_tp1)
            sources.append("chart_ichimoku_tp1")
        if ich_tp2 > 0:
            tp2 = max(tp2, ich_tp2)
            sources.append("chart_ichimoku_tp2")
        if tp1 > 0:
            target = max(target, tp1 * 0.92)
            if not ich_tp1:
                sources.append("chart_pivot_tp1")
        if tp2 > 0:
            target2 = max(target * 1.2, tp2 * 0.88)
            if not ich_tp2:
                sources.append("chart_fib_tp2")

    spot_chart = snap.spotChart
    if spot_chart and spot > 0 and not analysis:
        mom5 = abs(float(spot_chart.momentum5Pct or 0))
        trend = float(spot_chart.trendStrength or 0)
        aligned = (
            (side_v == "CALL" and spot_chart.direction == "BULLISH")
            or (side_v == "PUT" and spot_chart.direction == "BEARISH")
        )
        if aligned:
            target = max(target, 6.0 + mom5 * 80 + trend * 0.08)
            target2 = max(target2, target * 1.35)
            trail_arm = max(2.0, trail_arm * 0.85)
            sources.append("spot_chart_tp")
        stop = max(stop, 3.0 + entry_premium * 0.06 * (1.0 + mom5 * 2))

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
        targetPoints=_clamp_chart_target_pts(max(base_target * 0.9, target), entry_premium),
        targetPoints2=_clamp_chart_target_pts(max(target, target2), entry_premium, is_tp2=True),
        trailArmPoints=round(trail_arm, 2),
        trailKeepRatio=round(trail_keep, 2),
        trailStepPoints=round(trail_step, 2),
        microTargetPoints=round(micro, 2),
        confidence=confidence,
        confidenceRaw=confidence_raw,
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
    if not settings.chart_exit_levels_enabled:
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

    merged["targetPoints"] = _clamp_chart_target_pts(float(merged["targetPoints"]), entry_premium)
    merged["targetPoints2"] = _clamp_chart_target_pts(levels.targetPoints2, entry_premium, is_tp2=True)
    settings = get_settings()
    merged["targetPointsHalf"] = round(
        float(merged["targetPoints"]) * settings.chart_confidence_half_tp_lock_pct,
        2,
    )
    merged = _stamp_entry_baselines(merged)
    merged["chartConfidence"] = levels.confidence
    merged["chartConfidenceRaw"] = levels.confidenceRaw
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


def compute_live_chart_trail_tuning(
    plan_dict: dict[str, Any],
    snap: SymbolSnapshot,
    side: Side | str,
    *,
    entry_confidence: float,
    live_confidence: float,
    entry_premium: float = 50.0,
) -> ChartTrailTuning:
    """
    Continuously tune SL/TP/trail from live multi-indicator chart confidence.
    High confidence → wider targets, looser trail (let runners run).
    Low / fading confidence → tighter SL, earlier trail arm, higher keep ratio.
    """
    settings = get_settings()
    plan_dict = _stamp_entry_baselines(plan_dict)
    base_stop, base_target, base_target2 = (
        float(plan_dict.get("entryStopPoints") or plan_dict.get("stopPoints", 3.0)),
        float(plan_dict.get("entryTargetPoints") or plan_dict.get("targetPoints", 6.0)),
        float(plan_dict.get("entryTargetPoints2") or plan_dict.get("targetPoints2", 0) or 0),
    )
    if base_target2 <= 0:
        base_target2 = base_target * 1.5
    base_arm = float(plan_dict.get("trailArmPoints", 3.0))
    base_keep = float(plan_dict.get("trailKeepRatio", 0.60))

    delta = live_confidence - entry_confidence
    conf = live_confidence / 100.0
    sources: list[str] = []

    stop = base_stop
    target = base_target
    target2 = base_target2
    arm = base_arm
    keep = base_keep
    tighten = False
    let_run = False

    # Confidence tier tuning
    if live_confidence >= 78:
        let_run = True
        target *= 1.0 + conf * 0.25
        target2 *= 1.0 + conf * 0.20
        arm = max(1.5, arm * (1.0 - conf * 0.15))
        keep = max(0.48, keep - conf * 0.10)
        sources.append("high_conf_let_run")
    elif live_confidence >= 62:
        target *= 1.0 + conf * 0.12
        keep = min(0.75, keep + conf * 0.04)
        sources.append("mid_conf_balanced")
    else:
        tighten = True
        stop = max(settings.scalp_stop_min_points, stop * (0.88 - (0.62 - conf) * 0.05))
        arm = max(1.2, arm * 0.85)
        keep = min(0.82, keep + 0.12)
        target = max(base_target * 0.9, target * 0.94)
        sources.append("low_conf_tighten")

    # Confidence fade since entry — protect open profit
    if delta <= -12:
        tighten = True
        stop *= 0.88
        keep = min(0.85, keep + 0.10)
        arm = max(1.0, arm * 0.80)
        sources.append(f"conf_fade_{delta:.0f}")
    elif delta >= 10:
        let_run = True
        target *= 1.08
        keep = max(0.50, keep - 0.06)
        sources.append(f"conf_rise_{delta:.0f}")

    # Live structure check — opposing MTF consensus forces tighten
    analysis = snap.chartAnalysis
    side_v = _side_val(side)
    target_bias = "BULLISH" if side_v == "CALL" else "BEARISH"
    if analysis:
        consensus = (analysis.consensus or "NEUTRAL").upper()
        if consensus not in ("NEUTRAL", target_bias):
            tighten = True
            stop *= 0.90
            keep = min(0.88, keep + 0.08)
            sources.append(f"mtf_oppose_{consensus.lower()}")

        ich = analysis.ichimoku or {}
        cloud = (ich.get("cloudBias") or "NEUTRAL").upper()
        tk = (ich.get("tkCross") or "NEUTRAL").upper()
        if cloud not in ("NEUTRAL", target_bias):
            tighten = True
            stop *= 0.92
            keep = min(0.86, keep + 0.06)
            sources.append(f"ichimoku_cloud_oppose_{cloud.lower()}")
        elif cloud == target_bias and live_confidence >= 62:
            target *= 1.04
            sources.append(f"ichimoku_cloud_{cloud.lower()}")
        if tk not in ("NEUTRAL", target_bias):
            tighten = True
            arm = max(1.0, arm * 0.90)
            sources.append(f"ichimoku_tk_oppose_{tk.lower()}")
        elif tk == target_bias:
            target *= 1.03
            sources.append(f"ichimoku_tk_{tk.lower()}")

    stop_cap = max(8.0, entry_premium * 0.12)
    return ChartTrailTuning(
        liveConfidence=round(live_confidence, 1),
        entryConfidence=round(entry_confidence, 1),
        confidenceDelta=round(delta, 1),
        trailArmPoints=round(max(1.0, arm), 2),
        trailKeepRatio=round(min(0.88, max(0.45, keep)), 3),
        stopPoints=round(min(stop_cap, max(settings.scalp_stop_min_points, stop)), 2),
        targetPoints=_clamp_chart_target_pts(max(base_target * 0.85, target), entry_premium),
        targetPoints2=_clamp_chart_target_pts(max(target, target2), entry_premium, is_tp2=True),
        tighten=tighten,
        letRun=let_run,
        sources=sources,
    )


def update_live_chart_trail(
    trade: PaperTrade,
    snap: SymbolSnapshot,
) -> dict[str, Any]:
    """
    Lightweight per-exit-cycle chart re-analysis — tune trail/SL/TP from live confidence.
    Full structure merge runs on chart_exit_refresh_seconds; this runs every trail tune interval.
    """
    settings = get_settings()
    if not settings.chart_exit_levels_enabled or not settings.chart_confidence_trail_enabled:
        return (trade.entryContext or {}).get("exitPlan") or {}

    ctx = trade.entryContext or {}
    last_tune = ctx.get("chartTrailTunedAt")
    if last_tune:
        try:
            ts = datetime.fromisoformat(str(last_tune))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            elapsed = (datetime.now(IST) - ts.astimezone(IST)).total_seconds()
            if elapsed < settings.chart_trail_tune_seconds:
                return ctx.get("exitPlan") or {}
        except (TypeError, ValueError):
            pass

    plan_dict = _stamp_entry_baselines(dict(ctx.get("exitPlan") or {}))
    if not plan_dict:
        plan_dict = _stamp_entry_baselines({
            "stopPoints": settings.scalp_stop_points,
            "targetPoints": settings.scalp_target_points,
            "trailArmPoints": settings.scalp_trail_arm_points,
            "trailKeepRatio": settings.scalp_trail_keep_ratio,
            "trailStepPoints": settings.scalp_trail_step_points,
            "microTargetPoints": settings.enhanced_micro_target_points,
        })

    entry_conf = float(
        ctx.get("entryChartConfidence")
        or plan_dict.get("chartConfidence")
        or ctx.get("chartConfidence")
        or 50.0,
    )
    live_conf, live_sources = chart_trade_confidence(snap, trade.side)
    tuning = compute_live_chart_trail_tuning(
        plan_dict,
        snap,
        trade.side,
        entry_confidence=entry_conf,
        live_confidence=live_conf,
        entry_premium=float(trade.entryPremium or 50),
    )

    from app.engines.bullish_hold import direction_aligned_with_breadth
    from app.models.schemas import StrategyType

    best_pts = max(trade.bestPnlPoints, trade.pnlPoints or 0)
    entry_vel = float(ctx.get("entryVelocity3s") or ctx.get("velocity3s") or 0)
    is_explosion = trade.strategyType == StrategyType.EXPLOSIVE
    breadth_aligned = direction_aligned_with_breadth(trade)

    # Breadth-aligned explosions: don't tighten exits on brief chart noise before +5pt
    if is_explosion and breadth_aligned and best_pts < 5.0:
        tuning.tighten = False
        tuning.letRun = True
        tuning.trailArmPoints = max(
            tuning.trailArmPoints,
            float(plan_dict.get("trailArmPoints") or settings.explosion_trail_arm_points),
        )
        tuning.trailKeepRatio = min(
            tuning.trailKeepRatio,
            float(plan_dict.get("trailKeepRatio") or settings.explosion_trail_keep_ratio),
        )
        plan_dict = dict(plan_dict)
        plan_dict["microTargetPoints"] = max(
            float(plan_dict.get("microTargetPoints") or settings.explosion_micro_target_points),
            settings.explosion_micro_target_points,
        )
        tuning.sources.append("explosion_breadth_hold")
    elif is_explosion and entry_vel >= 3.0 and best_pts < 4.0 and tuning.tighten:
        tuning.tighten = False
        tuning.trailArmPoints = max(tuning.trailArmPoints, settings.explosion_trail_arm_points)
        tuning.sources.append("explosion_velocity_hold")

    merged = dict(plan_dict)
    merged["stopPoints"] = tuning.stopPoints
    merged["targetPoints"] = tuning.targetPoints
    merged["targetPoints2"] = tuning.targetPoints2
    merged["targetPointsHalf"] = round(
        float(plan_dict.get("entryTargetPoints") or tuning.targetPoints)
        * settings.chart_confidence_half_tp_lock_pct,
        2,
    )
    merged["trailArmPoints"] = tuning.trailArmPoints
    merged["trailKeepRatio"] = tuning.trailKeepRatio
    merged["entryTargetPoints"] = plan_dict.get("entryTargetPoints", tuning.targetPoints)
    merged["entryTargetPoints2"] = plan_dict.get("entryTargetPoints2", tuning.targetPoints2)
    merged["entryStopPoints"] = plan_dict.get("entryStopPoints", tuning.stopPoints)
    merged["chartConfidence"] = live_conf
    merged["chartConfidenceLive"] = live_conf
    merged["chartConfidenceEntry"] = entry_conf
    merged["chartConfidenceDelta"] = tuning.confidenceDelta
    merged["chartTrailTighten"] = tuning.tighten
    merged["chartTrailLetRun"] = tuning.letRun

    if trade.entryContext is None:
        trade.entryContext = {}
    trade.entryContext["exitPlan"] = merged
    trade.entryContext["chartConfidence"] = live_conf
    trade.entryContext["chartExitLive"] = tuning.to_dict()
    trade.entryContext["chartExitLiveSources"] = live_sources[:8] + tuning.sources
    trade.entryContext["chartTrailTunedAt"] = datetime.now(IST).isoformat()
    if "entryChartConfidence" not in trade.entryContext:
        trade.entryContext["entryChartConfidence"] = entry_conf
    return merged


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

    plan_dict = _stamp_entry_baselines(dict(ctx.get("exitPlan") or {}))
    if not plan_dict:
        plan_dict = _stamp_entry_baselines({
            "stopPoints": settings.scalp_stop_points,
            "targetPoints": settings.scalp_target_points,
            "trailArmPoints": settings.scalp_trail_arm_points,
            "trailKeepRatio": settings.scalp_trail_keep_ratio,
            "trailStepPoints": settings.scalp_trail_step_points,
            "microTargetPoints": settings.enhanced_micro_target_points,
        })

    merged = merge_chart_into_exit_plan(
        plan_dict, snap, trade.side, float(trade.entryPremium or 50),
    )
    entry_conf = float(merged.get("chartConfidence") or 50.0)
    if trade.entryContext is None:
        trade.entryContext = {}
    trade.entryContext["entryChartConfidence"] = entry_conf
    trade.entryContext["exitPlan"] = merged
    trade.entryContext["chartExitLevels"] = merged.get("chartExitLevels")
    trade.entryContext["chartConfidence"] = merged.get("chartConfidence")
    trade.entryContext["promoteToTrailing"] = merged.get("promoteToTrailing")
    trade.entryContext["chartExitRefreshedAt"] = datetime.now(IST).isoformat()
    # Apply live trail tuning immediately after full refresh
    update_live_chart_trail(trade, snap)
    return trade.entryContext.get("exitPlan") or merged
