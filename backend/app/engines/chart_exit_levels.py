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


def _cfg_bool(settings: Any, name: str, default: bool = True) -> bool:
    """Bool setting with MagicMock-safe fallback."""
    v = getattr(settings, name, default)
    if isinstance(v, bool):
        return v
    return bool(default)


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
        smart = (ich.get("smartBias") or "NEUTRAL").upper()
        if smart == target_bias:
            smart_score = float(ich.get("smartScore") or 50)
            # Stronger composite agreement → larger confidence bump.
            bump = 12 if abs(smart_score - 50) >= 20 else 9
            score += bump
            sources.append(f"smart_ichimoku_{smart.lower()}")
        elif smart != "NEUTRAL" and smart != target_bias:
            score -= 6
            sources.append("smart_ichimoku_oppose")
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
        chikou = (ich.get("chikouBias") or "NEUTRAL").upper()
        if chikou == target_bias:
            score += 4
            sources.append(f"ichimoku_chikou_{chikou.lower()}")
        elif chikou != "NEUTRAL" and chikou != target_bias:
            score -= 3

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
    """Freeze entry SL/TP/trail baselines so live tuning does not compound each cycle."""
    stamped = dict(plan_dict)
    if "entryTargetPoints" not in stamped and stamped.get("targetPoints") is not None:
        stamped["entryTargetPoints"] = float(stamped["targetPoints"])
    if "entryTargetPoints2" not in stamped and stamped.get("targetPoints2") is not None:
        stamped["entryTargetPoints2"] = float(stamped["targetPoints2"])
    if "entryStopPoints" not in stamped and stamped.get("stopPoints") is not None:
        stamped["entryStopPoints"] = float(stamped["stopPoints"])
    # Jul29 NIFTY 24100 CE: live high-conf retunes compounded trailArm 26→1.35
    # and scratched a +1.45pt winner while TP sat at 58pt.
    if "entryTrailArmPoints" not in stamped and stamped.get("trailArmPoints") is not None:
        stamped["entryTrailArmPoints"] = float(stamped["trailArmPoints"])
    if "entryTrailKeepRatio" not in stamped and stamped.get("trailKeepRatio") is not None:
        stamped["entryTrailKeepRatio"] = float(stamped["trailKeepRatio"])
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


def _local_support_min_pts(entry_premium: float) -> float:
    """Ignore structure closer than this — nearest noise pivots map to ~4pt toys."""
    settings = get_settings()
    min_pts = _cfg_float(settings, "exit_sl_local_support_min_points", 5.0)
    min_frac = _cfg_float(settings, "exit_sl_local_support_min_premium_frac", 0.06)
    return max(min_pts, entry_premium * min_frac)


def _pick_local_support_pts(candidates: list[float], entry_premium: float) -> Optional[float]:
    """Nearest *meaningful* support distance — ignore sub-min noise (Jul30 ~3pt toys)."""
    clean = [float(c) for c in candidates if c and c > 0]
    if not clean:
        return None
    floor = _local_support_min_pts(entry_premium)
    meaningful = [c for c in clean if c >= floor]
    if not meaningful:
        # No real support — do not invent a 3–4pt chart SL; caller falls back to premium %.
        return None
    return min(meaningful)


def _smc_support_index_dists(side_v: str, spot: float, analysis: ChartAnalysis) -> list[float]:
    """Index distances to SMC swing / liquidity support on the invalidating side."""
    inst = analysis.institutional or {}
    out: list[float] = []
    if side_v == "PUT":
        for key in ("lastSwingHigh",):
            lvl = inst.get(key)
            if lvl and float(lvl) > spot and _valid_index_structure_level(float(lvl), spot):
                out.append(float(lvl) - spot)
        for lvl in inst.get("liquidityPools") or []:
            try:
                p = float(lvl)
            except (TypeError, ValueError):
                continue
            if p > spot and _valid_index_structure_level(p, spot):
                out.append(p - spot)
    else:
        for key in ("lastSwingLow",):
            lvl = inst.get(key)
            if lvl and 0 < float(lvl) < spot and _valid_index_structure_level(float(lvl), spot):
                out.append(spot - float(lvl))
        for lvl in inst.get("liquidityPools") or []:
            try:
                p = float(lvl)
            except (TypeError, ValueError):
                continue
            if 0 < p < spot and _valid_index_structure_level(p, spot):
                out.append(spot - p)
    return out


def _structure_stop_pts(
    side_v: str,
    spot: float,
    analysis: ChartAnalysis,
    entry_premium: float,
) -> Optional[float]:
    """SL distance from local opposing support (pivot/fib/SMC), not nearest noise tick."""
    if spot <= 0:
        return None
    pivots = analysis.pivots or {}
    index_dists: list[float] = []

    if side_v == "PUT":
        for key in ("R1", "R2", "P"):
            lvl = pivots.get(key)
            if lvl and float(lvl) > spot and _valid_index_structure_level(float(lvl), spot):
                index_dists.append(float(lvl) - spot)
        fib = analysis.fibonacci or {}
        retr = fib.get("retracement") or {}
        for price in retr.values():
            p = float(price)
            if p > spot and _valid_index_structure_level(p, spot):
                index_dists.append(p - spot)
    else:
        for key in ("S1", "S2", "P"):
            lvl = pivots.get(key)
            if lvl and float(lvl) < spot and _valid_index_structure_level(float(lvl), spot):
                index_dists.append(spot - float(lvl))
        fib = analysis.fibonacci or {}
        retr = fib.get("retracement") or {}
        for price in retr.values():
            p = float(price)
            if p < spot and _valid_index_structure_level(p, spot):
                index_dists.append(spot - p)

    index_dists.extend(_smc_support_index_dists(side_v, spot, analysis))
    if not index_dists:
        return None
    prem_candidates = [
        _index_dist_to_premium_pts(spot, d, entry_premium) for d in index_dists
    ]
    return _pick_local_support_pts(prem_candidates, entry_premium)


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
    prem_candidates: list[float] = []

    if side_v == "PUT":
        for key in ("cloudTop", "kijun", "tenkan", "senkouA", "senkouB"):
            lvl = ich.get(key, 0)
            if lvl > spot and _valid_index_structure_level(lvl, spot):
                prem_candidates.append(
                    _index_dist_to_premium_pts(spot, lvl - spot, entry_premium)
                )
    else:
        for key in ("cloudBottom", "kijun", "tenkan", "senkouA", "senkouB"):
            lvl = ich.get(key, 0)
            if 0 < lvl < spot and _valid_index_structure_level(lvl, spot):
                prem_candidates.append(
                    _index_dist_to_premium_pts(spot, spot - lvl, entry_premium)
                )

    return _pick_local_support_pts(prem_candidates, entry_premium)


def _premium_local_support_stop_pts(
    snap: SymbolSnapshot,
    side: Side | str,
    entry_premium: float,
    *,
    local_base_premium: Optional[float] = None,
) -> Optional[float]:
    """SL from option-premium local base / swing low (ICT), when available."""
    if entry_premium <= 0:
        return None
    side_v = _side_val(side)
    base = 0.0
    source = ""

    explicit = float(local_base_premium or 0)
    if 0 < explicit < entry_premium:
        base = explicit
        source = "ict_base_explicit"

    top = snap.topExplosion or {}
    if base <= 0 and str(top.get("side", "")).upper() in ("", side_v):
        ict_base = float(top.get("ictBasePremium") or 0)
        if 0 < ict_base < entry_premium:
            base = ict_base
            source = "ict_base"

    if base <= 0:
        for entry in snap.explosiveRunnerWatchlist or []:
            if str(entry.get("side", "")).upper() != side_v:
                continue
            ict_base = float(entry.get("ictBasePremium") or entry.get("basePremium") or 0)
            if 0 < ict_base < entry_premium:
                base = ict_base
                source = "watchlist_base"
                break

    if base <= 0 and snap.explosiveRunner and snap.explosiveRunner.side:
        runner_side = snap.explosiveRunner.side
        runner_v = runner_side.value if hasattr(runner_side, "value") else str(runner_side)
        if str(runner_v).upper() == side_v:
            ctx = getattr(snap.explosiveRunner, "signal", None)
            for attr in ("ictBasePremium", "basePremium"):
                raw = getattr(ctx, attr, None) if ctx is not None else None
                if raw is None and isinstance(getattr(snap.explosiveRunner, "meta", None), dict):
                    raw = snap.explosiveRunner.meta.get(attr)
                try:
                    ict_base = float(raw or 0)
                except (TypeError, ValueError):
                    ict_base = 0.0
                if 0 < ict_base < entry_premium:
                    base = ict_base
                    source = "runner_base"
                    break

    if base <= 0:
        return None

    # Distance from entry down through the local premium support (buffer applied by caller).
    stop = entry_premium - base
    stop = max(_local_support_min_pts(entry_premium), stop)
    _ = source
    return round(stop, 2)


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
    local_base_premium: Optional[float] = None,
) -> ChartExitLevels:
    """Multi-chart SL/TP/trail — SL from local support + chart structure confirmation."""
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
    chart_structure_sl: Optional[float] = None
    if analysis and spot > 0:
        struct_sl = _structure_stop_pts(side_v, spot, analysis, entry_premium)
        ich_sl = _ichimoku_stop_pts(side_v, spot, analysis.ichimoku or {}, entry_premium)
        sl_candidates = [x for x in (struct_sl, ich_sl) if x and x > 0]
        if sl_candidates:
            chart_structure_sl = _pick_local_support_pts(sl_candidates, entry_premium)
            if chart_structure_sl:
                if struct_sl and struct_sl >= _local_support_min_pts(entry_premium):
                    sources.append("chart_structure_sl")
                if ich_sl and ich_sl >= _local_support_min_pts(entry_premium):
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

    prem_sl = _premium_local_support_stop_pts(
        snap, side, entry_premium, local_base_premium=local_base_premium,
    )
    if prem_sl and prem_sl > 0:
        sources.append("premium_local_support_sl")

    # Combined: local premium support AND meaningful chart structure (never noise).
    local_support_sl: Optional[float] = None
    support_parts = [x for x in (prem_sl, chart_structure_sl) if x and x > 0]
    if support_parts:
        local_support_sl = max(support_parts)

    use_local = _cfg_bool(settings, "exit_sl_use_local_support", True)
    high_conf = confidence >= _cfg_float(settings, "exit_sl_chart_confirm_min_confidence", 70.0)
    if use_local and local_support_sl and local_support_sl > 0:
        buffer = entry_premium * _cfg_float(settings, "exit_sl_local_support_buffer_pct", 0.02)
        # High-conf chart confirmation: SL stays at combined support — setup is
        # expected to move up without retesting; do not tighten toward noise.
        stop = max(base_stop, local_support_sl + max(0.0, buffer))
        sources.append("sl_at_local_support")
        if high_conf and chart_structure_sl and prem_sl:
            sources.append("chart_confirmed_local_support_sl")
        elif high_conf and (chart_structure_sl or prem_sl):
            sources.append("chart_confirmed_sl")
    elif local_support_sl and local_support_sl > 0:
        stop = local_support_sl * 1.08

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
            trail_arm = max(trail_arm, base_trail_arm, 3.0)
            sources.append("spot_chart_tp")
        if not (use_local and local_support_sl):
            stop = max(stop, 3.0 + entry_premium * 0.06 * (1.0 + mom5 * 2))

    conf_factor = confidence / 100.0
    # Do not shrink local-support / chart-confirmed SL with high confidence.
    if not (use_local and local_support_sl):
        stop = stop * (1.05 - conf_factor * 0.12)
    target = target * (1.0 + conf_factor * 0.35)
    target2 = target2 * (1.0 + conf_factor * 0.25)
    # High confidence must HOLD winners — raise trail arm (delay trail), don't
    # shrink it (Jul29 24100 CE armed at 1.35pt vs 58pt TP).
    trail_arm = max(base_trail_arm, trail_arm * (1.0 + conf_factor * 0.25))
    trail_keep = max(0.45, trail_keep - conf_factor * 0.08)
    micro = max(1.5, micro * (1.0 + conf_factor * 0.15))

    promote = (
        confidence >= settings.quick_trail_promote_min_confidence
        or confidence >= settings.all_day_min_chart_confidence
    )

    stop_floor = _cfg_float(settings, "scalp_stop_min_points", 2.5)
    abs_max = _cfg_float(settings, "explosion_stop_abs_max_points", 40.0)
    pct_cap = _cfg_float(settings, "explosion_stop_max_pct_of_premium", 0.18)
    # Local-support stops need room through the support level (old ×12% erased structure).
    if use_local and local_support_sl:
        stop_cap = min(
            abs_max,
            max(12.0, entry_premium * pct_cap, float(stop)),
        )
    else:
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
    *,
    local_base_premium: Optional[float] = None,
) -> dict[str, Any]:
    """Merge chart levels into an adaptive exit plan dict.

    SL = max(premium floor, local support, meaningful chart structure).
    High-conf chart confirms — never blend down toward noise. TP/trail still blend.
    """
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
        local_base_premium=local_base_premium,
    )
    weight = min(0.72, 0.35 + levels.confidence / 200.0)

    merged = dict(plan_dict)
    blend_keys = (
        "targetPoints", "trailArmPoints", "trailKeepRatio",
        "trailStepPoints", "microTargetPoints",
    )
    for key in blend_keys:
        base_val = float(plan_dict.get(key, getattr(levels, key)))
        chart_val = float(getattr(levels, key))
        merged[key] = round(base_val * (1 - weight) + chart_val * weight, 2)

    base_stop = float(plan_dict.get("stopPoints", 3.0))
    chart_stop = float(levels.stopPoints)
    use_local = _cfg_bool(settings, "exit_sl_use_local_support", True)
    local_tagged = any(
        s in (levels.sources or [])
        for s in (
            "sl_at_local_support",
            "premium_local_support_sl",
            "chart_structure_sl",
            "chart_ichimoku_sl",
            "chart_confirmed_sl",
            "chart_confirmed_local_support_sl",
        )
    )
    if use_local and local_tagged and chart_stop > 0:
        # Combined local support + chart analysis — never blend down.
        merged["stopPoints"] = round(max(base_stop, chart_stop), 2)
        merged["localSupportStopPoints"] = round(chart_stop, 2)
        if "chart_structure_sl" in (levels.sources or []) or "chart_ichimoku_sl" in (levels.sources or []):
            merged["chartStructureStopPoints"] = round(chart_stop, 2)
        reasoning_pre = list(merged.get("reasoning") or [])
        reasoning_pre.append(
            f"SL local support+chart {chart_stop:.1f}pt (premium floor {base_stop:.1f}pt)"
        )
        merged["reasoning"] = reasoning_pre
    else:
        # No meaningful support — keep premium natural; never crush with noise blend.
        merged["stopPoints"] = round(max(base_stop, chart_stop), 2)

    merged["targetPoints"] = _clamp_chart_target_pts(float(merged["targetPoints"]), entry_premium)
    merged["targetPoints2"] = _clamp_chart_target_pts(levels.targetPoints2, entry_premium, is_tp2=True)
    # Natural floor for explosions + any plan that stamped naturalStopPoints.
    natural = float(merged.get("naturalStopPoints") or plan_dict.get("naturalStopPoints") or 0)
    # After local-support + chart SL, raise natural to the final calculated invalidation.
    if use_local and local_tagged:
        natural = max(natural, float(merged.get("stopPoints") or 0))
    elif natural <= 0:
        natural = float(merged.get("stopPoints") or 0)
    if natural > 0:
        preserve = float(
            getattr(settings, "explosion_chart_stop_min_natural_frac", 0.85) or 0.85
        )
        # MagicMock-safe preserve
        if not isinstance(preserve, (int, float)):
            preserve = 0.85
        floor = natural * max(0.0, min(1.0, float(preserve)))
        if float(merged.get("stopPoints") or 0) < floor:
            merged["stopPoints"] = round(floor, 2)
            reasoning_pre = list(merged.get("reasoning") or [])
            reasoning_pre.append(
                f"Natural SL floor {floor:.1f}pt ({float(preserve):.0%} of {natural:.1f}pt)"
            )
            merged["reasoning"] = reasoning_pre
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
    if natural > 0:
        merged["naturalStopPoints"] = round(natural, 2)
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
    # Always retune from entry baselines — never from last live arm (compounds down).
    base_arm = float(
        plan_dict.get("entryTrailArmPoints")
        or plan_dict.get("trailArmPoints", 3.0)
    )
    base_keep = float(
        plan_dict.get("entryTrailKeepRatio")
        or plan_dict.get("trailKeepRatio", 0.60)
    )

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

    # Confidence tier tuning — high conf holds for TP (higher arm), low conf protects.
    if live_confidence >= 78:
        let_run = True
        target *= 1.0 + conf * 0.25
        target2 *= 1.0 + conf * 0.20
        # Delay trail until a meaningful fraction of entry target is printed.
        min_arm_frac = float(
            getattr(settings, "high_conf_trail_arm_min_target_frac", 0.22) or 0.22
        )
        arm = max(base_arm * (1.0 + conf * 0.15), base_target * min_arm_frac, 4.0)
        keep = max(0.42, keep - conf * 0.10)
        sources.append("high_conf_let_run")
    elif live_confidence >= 62:
        target *= 1.0 + conf * 0.12
        keep = min(0.75, keep + conf * 0.04)
        arm = max(base_arm, 3.0)
        sources.append("mid_conf_balanced")
    else:
        tighten = True
        stop = max(settings.scalp_stop_min_points, stop * (0.88 - (0.62 - conf) * 0.05))
        arm = max(1.5, base_arm * 0.85)
        keep = min(0.82, keep + 0.12)
        target = max(base_target * 0.9, target * 0.94)
        sources.append("low_conf_tighten")

    # Confidence fade since entry — protect open profit
    if delta <= -12:
        tighten = True
        stop *= 0.88
        keep = min(0.85, keep + 0.10)
        arm = max(1.5, arm * 0.85)
        sources.append(f"conf_fade_{delta:.0f}")
    elif delta >= 10:
        let_run = True
        target *= 1.08
        keep = max(0.45, keep - 0.06)
        arm = max(arm, base_arm)
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

    stop_cap = max(
        8.0,
        entry_premium * float(
            getattr(settings, "explosion_stop_max_pct_of_premium", 0.18) or 0.18
        ),
    )
    # Never live-crush below the entry natural / local-support SL.
    natural = float(
        plan_dict.get("naturalStopPoints")
        or plan_dict.get("localSupportStopPoints")
        or 0
    )
    if natural > 0:
        preserve = float(
            getattr(settings, "explosion_sl_preserve_natural_frac", 0.85) or 0.85
        )
        floor = natural * max(0.0, min(1.0, preserve))
        if stop < floor:
            stop = floor
            sources.append(f"protect_natural_sl_{floor:.1f}")
        stop_cap = max(stop_cap, natural)
    stop_cap = min(
        stop_cap,
        float(getattr(settings, "explosion_stop_abs_max_points", 40.0) or 40.0),
    )
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
    # Jul30 77700 CE: live trail/refresh raised stop 13.7→40 then ×1.4 → −48pt.
    # Never widen SL after entry — entryStopPoints is the risk ceiling.
    entry_stop = float(plan_dict.get("entryStopPoints") or plan_dict.get("stopPoints") or 0)
    live_stop = float(tuning.stopPoints)
    if entry_stop > 0:
        live_stop = min(live_stop, entry_stop)
    merged["stopPoints"] = round(live_stop, 2)
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
        local_base_premium=(
            float(ctx.get("localBaseBasePremium") or 0) or None
        ),
    )
    # Freeze SL at entry risk — live structure refresh must not widen the stop
    # (Jul30 77700 CE: refresh grew 13.7→40 while the rip was already failing).
    entry_stop = float(plan_dict.get("entryStopPoints") or plan_dict.get("stopPoints") or 0)
    if entry_stop > 0 and float(merged.get("stopPoints") or 0) > entry_stop:
        merged["stopPoints"] = round(entry_stop, 2)
        reasons = list(merged.get("reasoning") or [])
        reasons.append(f"Freeze entry SL {entry_stop:.1f}pt — live chart cannot widen")
        merged["reasoning"] = reasons
    # Keep entry baselines intact across refresh.
    if plan_dict.get("entryStopPoints") is not None:
        merged["entryStopPoints"] = float(plan_dict["entryStopPoints"])
    if plan_dict.get("entryTargetPoints") is not None:
        merged["entryTargetPoints"] = float(plan_dict["entryTargetPoints"])
    if plan_dict.get("entryTrailArmPoints") is not None:
        merged["entryTrailArmPoints"] = float(plan_dict["entryTrailArmPoints"])
    if plan_dict.get("naturalStopPoints") is not None:
        merged["naturalStopPoints"] = float(plan_dict["naturalStopPoints"])

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
