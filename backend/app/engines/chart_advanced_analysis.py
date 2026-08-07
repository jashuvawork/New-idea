"""Advanced chart analysis — MTF, Fibonacci, pivots, Gann, Ichimoku, SMC/ICT, patterns."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.engines.chart_indicators import compute_macd, compute_rsi
from app.engines.mtf_chart_analysis import SCALP_TIMEFRAMES, analyze_timeframe, resample_candles, resample_ohlc_bars
from app.engines.spot_direction import _candle_rows
from app.models.schemas import ChartAnalysis, MarketProfile, TimeframeChartRead

IST = ZoneInfo("Asia/Kolkata")

_FIB_RETRACEMENT = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
_FIB_EXTENSION = (1.272, 1.618, 2.0)


def _find_swings(
    highs: list[float],
    lows: list[float],
    *,
    lookback: int = 3,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []
    if len(highs) < lookback * 2 + 1:
        return swing_highs, swing_lows
    for i in range(lookback, len(highs) - lookback):
        window_h = highs[i - lookback : i + lookback + 1]
        window_l = lows[i - lookback : i + lookback + 1]
        if highs[i] >= max(window_h):
            swing_highs.append((i, highs[i]))
        if lows[i] <= min(window_l):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows


def compute_fibonacci_levels(
    swing_low: float,
    swing_high: float,
    spot: float,
    *,
    trend: str = "UP",
) -> dict[str, Any]:
    """Fibonacci retracement + extension from swing range."""
    if swing_high <= swing_low:
        return {"trend": trend, "zone": "NEUTRAL", "nearestLevel": None, "retracement": {}, "extension": {}}

    diff = swing_high - swing_low
    if trend == "DOWN":
        retracement = {
            f"{int(r * 1000) if r < 1 else 100}": round(swing_low + diff * r, 2) for r in _FIB_RETRACEMENT
        }
        extension = {str(r): round(swing_low - diff * (r - 1), 2) for r in _FIB_EXTENSION}
    else:
        retracement = {
            f"{int(r * 1000) if r < 1 else 100}": round(swing_high - diff * r, 2) for r in _FIB_RETRACEMENT
        }
        extension = {str(r): round(swing_high + diff * (r - 1), 2) for r in _FIB_EXTENSION}

    nearest_label = None
    nearest_dist = float("inf")
    for label, price in retracement.items():
        dist = abs(spot - price)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_label = label

    eq = (swing_high + swing_low) / 2
    zone = "PREMIUM" if spot > eq * 1.0002 else "DISCOUNT" if spot < eq * 0.9998 else "EQUILIBRIUM"
    return {
        "trend": trend,
        "swingLow": round(swing_low, 2),
        "swingHigh": round(swing_high, 2),
        "zone": zone,
        "nearestLevel": nearest_label,
        "nearestDistance": round(nearest_dist, 2),
        "retracement": retracement,
        "extension": extension,
    }


def compute_pivot_points(day_high: float, day_low: float, prev_close: float) -> dict[str, float]:
    """Classic floor pivot points."""
    if day_high <= 0 or day_low <= 0 or prev_close <= 0:
        return {}
    p = (day_high + day_low + prev_close) / 3
    r1 = 2 * p - day_low
    s1 = 2 * p - day_high
    r2 = p + (day_high - day_low)
    s2 = p - (day_high - day_low)
    r3 = day_high + 2 * (p - day_low)
    s3 = day_low - 2 * (day_high - p)
    return {
        "P": round(p, 2),
        "R1": round(r1, 2),
        "R2": round(r2, 2),
        "R3": round(r3, 2),
        "S1": round(s1, 2),
        "S2": round(s2, 2),
        "S3": round(s3, 2),
    }


def compute_gann_levels(low: float, high: float) -> dict[str, float]:
    """Gann 1/8 divisions between session range."""
    if high <= low:
        return {}
    diff = high - low
    return {f"G{i}/8": round(low + diff * (i / 8), 2) for i in range(9)}


def compute_andrews_pitchfork(
    swing_lows: list[tuple[int, float]],
    swing_highs: list[tuple[int, float]],
    spot: float,
) -> dict[str, Any]:
    """Andrews pitchfork from last three alternating pivots."""
    if len(swing_lows) < 2 or len(swing_highs) < 1:
        return {}
    p1 = swing_lows[-2] if len(swing_lows) >= 2 else swing_lows[-1]
    p2 = swing_highs[-1]
    p3 = swing_lows[-1]
    median_at_now = p1[1] + (p2[1] - p1[1]) + (p3[1] - p1[1]) * 0.5
    upper = median_at_now + (p2[1] - p1[1]) * 0.5
    lower = median_at_now - (p2[1] - p1[1]) * 0.5
    bias = "BULLISH" if spot > median_at_now else "BEARISH" if spot < median_at_now else "NEUTRAL"
    return {
        "median": round(median_at_now, 2),
        "upper": round(upper, 2),
        "lower": round(lower, 2),
        "bias": bias,
    }


def _ichimoku_mid(highs: list[float], lows: list[float], end: int, period: int, fallback: float) -> float:
    """Donchian mid over ``period`` bars ending at index ``end`` (inclusive)."""
    if end < 0 or not highs or not lows:
        return fallback
    start = max(0, end - period + 1)
    window_h = highs[start : end + 1]
    window_l = lows[start : end + 1]
    if not window_h or not window_l:
        return fallback
    return (max(window_h) + min(window_l)) / 2


def compute_ichimoku(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    spot: float,
) -> dict[str, Any]:
    """Smart Ichimoku — displaced cloud, chikou, twist, TK age, composite bias.

    Keeps classic fields (cloudBias / tkCross / priceVsCloud) for consumers and
    adds smartBias / smartScore / reasons for chart analysis + UI.
    """
    n = min(len(highs), len(lows), len(closes))
    if n <= 0:
        return {
            "tenkan": round(spot, 2),
            "kijun": round(spot, 2),
            "senkouA": round(spot, 2),
            "senkouB": round(spot, 2),
            "cloudTop": round(spot, 2),
            "cloudBottom": round(spot, 2),
            "cloudBias": "NEUTRAL",
            "tkCross": "NEUTRAL",
            "priceVsCloud": "INSIDE",
            "smartBias": "NEUTRAL",
            "smartScore": 50.0,
            "smartLabel": "Ichimoku neutral",
            "reasons": [],
        }

    highs = list(highs[-n:])
    lows = list(lows[-n:])
    closes = list(closes[-n:])
    last = n - 1
    px = float(spot or closes[last] or 0)

    tenkan = _ichimoku_mid(highs, lows, last, 9, px)
    kijun = _ichimoku_mid(highs, lows, last, 26, px)

    # Projected (future) cloud from current TK — classic span A/B at lag 0.
    future_a = (tenkan + kijun) / 2
    future_b = _ichimoku_mid(highs, lows, last, 52, px)

    # Cloud under current price = spans computed 26 bars ago (displacement).
    displace = 26
    if last >= displace:
        past = last - displace
        past_tenkan = _ichimoku_mid(highs, lows, past, 9, px)
        past_kijun = _ichimoku_mid(highs, lows, past, 26, px)
        senkou_a = (past_tenkan + past_kijun) / 2
        senkou_b = _ichimoku_mid(highs, lows, past, 52, px)
        cloud_displaced = True
    else:
        senkou_a = future_a
        senkou_b = future_b
        cloud_displaced = False

    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)
    cloud_thickness = max(cloud_top - cloud_bottom, 0.0)
    cloud_thickness_pct = (cloud_thickness / px * 100.0) if px > 0 else 0.0

    if px > cloud_top:
        cloud_bias = "BULLISH"
        price_vs = "ABOVE"
    elif px < cloud_bottom:
        cloud_bias = "BEARISH"
        price_vs = "BELOW"
    else:
        cloud_bias = "NEUTRAL"
        price_vs = "INSIDE"

    tk_cross = "BULLISH" if tenkan > kijun else "BEARISH" if tenkan < kijun else "NEUTRAL"

    # TK cross age — bars since tenkan/kijun relationship flipped.
    tk_cross_age = 0
    if tk_cross != "NEUTRAL" and n >= 3:
        for lookback in range(1, min(n, 40)):
            i = last - lookback
            t_i = _ichimoku_mid(highs, lows, i, 9, px)
            k_i = _ichimoku_mid(highs, lows, i, 26, px)
            state = "BULLISH" if t_i > k_i else "BEARISH" if t_i < k_i else "NEUTRAL"
            if state != tk_cross:
                break
            tk_cross_age = lookback
        tk_cross_age = max(1, tk_cross_age)

    # Chikou span — current close vs price 26 bars ago.
    chikou_bias = "NEUTRAL"
    chikou_vs = "FLAT"
    if last >= displace:
        lag_px = float(closes[last - displace] or 0)
        if lag_px > 0:
            if px > lag_px * 1.0005:
                chikou_bias = "BULLISH"
                chikou_vs = "ABOVE"
            elif px < lag_px * 0.9995:
                chikou_bias = "BEARISH"
                chikou_vs = "BELOW"

    # Cloud twist — Span A/B relationship flipped recently (kumo flip).
    cloud_twist = "NONE"
    if last >= displace + 3:
        states: list[str] = []
        for lookback in range(0, 6):
            i = last - displace - lookback
            if i < 0:
                break
            a_i = (
                _ichimoku_mid(highs, lows, i, 9, px) + _ichimoku_mid(highs, lows, i, 26, px)
            ) / 2
            b_i = _ichimoku_mid(highs, lows, i, 52, px)
            states.append("BULLISH" if a_i >= b_i else "BEARISH")
        if len(states) >= 2 and states[0] != states[1]:
            cloud_twist = states[0]

    # Future cloud bias (projected span).
    future_top = max(future_a, future_b)
    future_bottom = min(future_a, future_b)
    if future_a > future_b:
        future_cloud = "BULLISH"
    elif future_a < future_b:
        future_cloud = "BEARISH"
    else:
        future_cloud = "NEUTRAL"

    # Composite smart score (0–100). 50 = neutral.
    score = 50.0
    reasons: list[str] = []
    if price_vs == "ABOVE":
        score += 14
        reasons.append("price_above_cloud")
    elif price_vs == "BELOW":
        score -= 14
        reasons.append("price_below_cloud")
    else:
        reasons.append("price_inside_cloud")

    if tk_cross == "BULLISH":
        score += 10 if tk_cross_age <= 5 else 6
        reasons.append(f"tk_bullish_age_{tk_cross_age}")
    elif tk_cross == "BEARISH":
        score -= 10 if tk_cross_age <= 5 else 6
        reasons.append(f"tk_bearish_age_{tk_cross_age}")

    if chikou_bias == "BULLISH":
        score += 10
        reasons.append("chikou_above")
    elif chikou_bias == "BEARISH":
        score -= 10
        reasons.append("chikou_below")

    if cloud_twist == "BULLISH":
        score += 8
        reasons.append("cloud_twist_bullish")
    elif cloud_twist == "BEARISH":
        score -= 8
        reasons.append("cloud_twist_bearish")
    elif future_cloud == "BULLISH" and cloud_bias == "BULLISH":
        score += 4
        reasons.append("future_cloud_bullish")
    elif future_cloud == "BEARISH" and cloud_bias == "BEARISH":
        score -= 4
        reasons.append("future_cloud_bearish")

    # Thin cloud = weak conviction; thick aligned cloud reinforces.
    if cloud_thickness_pct >= 0.15 and cloud_bias == "BULLISH":
        score += 3
        reasons.append("thick_bull_cloud")
    elif cloud_thickness_pct >= 0.15 and cloud_bias == "BEARISH":
        score -= 3
        reasons.append("thick_bear_cloud")
    elif 0 < cloud_thickness_pct < 0.05:
        score += 0  # flat — no boost
        reasons.append("thin_cloud")

    # TK momentum vs kijun (price relative to baseline).
    if px > kijun * 1.001 and tenkan > kijun:
        score += 4
        reasons.append("price_above_kijun")
    elif px < kijun * 0.999 and tenkan < kijun:
        score -= 4
        reasons.append("price_below_kijun")

    score = max(0.0, min(100.0, score))
    if score >= 62:
        smart_bias = "BULLISH"
    elif score <= 38:
        smart_bias = "BEARISH"
    else:
        smart_bias = "NEUTRAL"

    if smart_bias == "BULLISH":
        smart_label = "Smart Ichimoku bullish"
    elif smart_bias == "BEARISH":
        smart_label = "Smart Ichimoku bearish"
    else:
        smart_label = "Smart Ichimoku mixed"

    return {
        "tenkan": round(tenkan, 2),
        "kijun": round(kijun, 2),
        "senkouA": round(senkou_a, 2),
        "senkouB": round(senkou_b, 2),
        "futureSenkouA": round(future_a, 2),
        "futureSenkouB": round(future_b, 2),
        "cloudTop": round(cloud_top, 2),
        "cloudBottom": round(cloud_bottom, 2),
        "cloudBias": cloud_bias,
        "tkCross": tk_cross,
        "tkCrossAge": int(tk_cross_age),
        "priceVsCloud": price_vs,
        "chikouBias": chikou_bias,
        "chikouVs": chikou_vs,
        "cloudTwist": cloud_twist,
        "cloudThickness": round(cloud_thickness, 2),
        "cloudThicknessPct": round(cloud_thickness_pct, 3),
        "futureCloud": future_cloud,
        "cloudDisplaced": cloud_displaced,
        "smartBias": smart_bias,
        "smartScore": round(score, 1),
        "smartLabel": smart_label,
        "reasons": reasons[:8],
    }


def _body_size(o: float, c: float) -> float:
    return abs(c - o)


def _candle_range(h: float, l: float) -> float:
    return max(h - l, 0.0001)


def detect_candlestick_patterns(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    timeframe: str = "5m",
) -> list[dict[str, Any]]:
    """Explosive-move candlestick patterns on the last few bars."""
    if len(closes) < 3:
        return []

    patterns: list[dict[str, Any]] = []
    o1, h1, l1, c1 = opens[-1], highs[-1], lows[-1], closes[-1]
    o2, h2, l2, c2 = opens[-2], highs[-2], lows[-2], closes[-2]

    def _add(name: str, bias: str, strength: float = 70.0) -> None:
        patterns.append({"name": name, "bias": bias, "strength": strength, "timeframe": timeframe})

    # Engulfing
    if c2 < o2 and c1 > o1 and c1 >= o2 and o1 <= c2:
        _add("Bullish Engulfing", "BULLISH", 78)
    if c2 > o2 and c1 < o1 and c1 <= o2 and o1 >= c2:
        _add("Bearish Engulfing", "BEARISH", 78)

    # Marubozu
    r1 = _candle_range(h1, l1)
    if _body_size(o1, c1) / r1 > 0.85:
        _add("Marubozu", "BULLISH" if c1 > o1 else "BEARISH", 72)

    # Pin bar at key level (long wick)
    upper_wick = h1 - max(o1, c1)
    lower_wick = min(o1, c1) - l1
    body = _body_size(o1, c1)
    if lower_wick > body * 2 and lower_wick > upper_wick * 1.5:
        _add("Pin Bar (bullish)", "BULLISH", 75)
    if upper_wick > body * 2 and upper_wick > lower_wick * 1.5:
        _add("Pin Bar (bearish)", "BEARISH", 75)

    # Inside / outside bar
    if h1 < h2 and l1 > l2:
        _add("Inside Bar", "NEUTRAL", 55)
    if h1 > h2 and l1 < l2:
        _add("Outside Bar", "BULLISH" if c1 > c2 else "BEARISH", 68)

    if len(closes) >= 3:
        o3, c3 = opens[-3], closes[-3]
        # Morning / evening star (simplified 3-candle)
        if c3 < o3 and abs(c2 - o2) < _body_size(o3, c3) * 0.35 and c1 > o1 and c1 > (o3 + c3) / 2:
            _add("Morning Star", "BULLISH", 80)
        if c3 > o3 and abs(c2 - o2) < _body_size(o3, c3) * 0.35 and c1 < o1 and c1 < (o3 + c3) / 2:
            _add("Evening Star", "BEARISH", 80)

    if len(closes) >= 5:
        last5_o = opens[-5:]
        last5_c = closes[-5:]
        greens = sum(1 for o, c in zip(last5_o, last5_c) if c > o)
        reds = sum(1 for o, c in zip(last5_o, last5_c) if c < o)
        if greens >= 4 and all(last5_c[i] > last5_c[i - 1] for i in range(1, 5)):
            _add("Three White Soldiers", "BULLISH", 82)
        if reds >= 4 and all(last5_c[i] < last5_c[i - 1] for i in range(1, 5)):
            _add("Three Black Crows", "BEARISH", 82)

    return patterns


def analyze_smc_ict(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    spot: float,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Smart Money / ICT concepts from OHLC."""
    swing_highs, swing_lows = _find_swings(highs, lows)
    session_high = max(highs) if highs else spot
    session_low = min(lows) if lows else spot
    eq = (session_high + session_low) / 2

    premium_discount = "PREMIUM" if spot > eq * 1.001 else "DISCOUNT" if spot < eq * 0.999 else "EQUILIBRIUM"

    tol = max((session_high - session_low) * 0.002, 1.0)
    equal_highs = len(swing_highs) >= 2 and abs(swing_highs[-1][1] - swing_highs[-2][1]) <= tol
    equal_lows = len(swing_lows) >= 2 and abs(swing_lows[-1][1] - swing_lows[-2][1]) <= tol

    stop_hunt = None
    if swing_highs and highs[-1] > swing_highs[-1][1] and closes[-1] < swing_highs[-1][1]:
        stop_hunt = "sell_side_liquidity_sweep"
    elif swing_lows and lows[-1] < swing_lows[-1][1] and closes[-1] > swing_lows[-1][1]:
        stop_hunt = "buy_side_liquidity_sweep"

    avg_body = sum(_body_size(o, c) for o, c in zip(opens[-10:], closes[-10:])) / max(1, min(10, len(closes)))
    displacement = _body_size(opens[-1], closes[-1]) > avg_body * 1.8

    structure = "NEUTRAL"
    bos = choch = None
    if len(swing_highs) >= 2 and closes[-1] > swing_highs[-2][1]:
        structure = "BULLISH"
        bos = "bullish_bos"
    elif len(swing_lows) >= 2 and closes[-1] < swing_lows[-2][1]:
        structure = "BEARISH"
        bos = "bearish_bos"
    if len(swing_highs) >= 1 and len(swing_lows) >= 1:
        if structure == "BEARISH" and closes[-1] > swing_highs[-1][1]:
            choch = "bullish_choch"
        elif structure == "BULLISH" and closes[-1] < swing_lows[-1][1]:
            choch = "bearish_choch"

    liquidity_pools: list[float] = []
    if swing_highs:
        liquidity_pools.append(round(swing_highs[-1][1], 2))
    if swing_lows:
        liquidity_pools.append(round(swing_lows[-1][1], 2))
    if equal_highs and swing_highs:
        liquidity_pools.append(round(swing_highs[-1][1], 2))
    if equal_lows and swing_lows:
        liquidity_pools.append(round(swing_lows[-1][1], 2))

    now = now or datetime.now(IST)
    hour, minute = now.hour, now.minute
    t_min = hour * 60 + minute
    # NSE kill zones (IST)
    in_kill_zone = False
    kill_zone = None
    if 9 * 60 + 15 <= t_min < 10 * 60:
        in_kill_zone, kill_zone = True, "open_kill_zone"
    elif 14 * 60 <= t_min < 15 * 60 + 15:
        in_kill_zone, kill_zone = True, "pm_kill_zone"

    judas_swing = False
    if in_kill_zone and stop_hunt:
        judas_swing = True

    return {
        "structure": structure,
        "premiumDiscount": premium_discount,
        "sessionHigh": round(session_high, 2),
        "sessionLow": round(session_low, 2),
        "equilibrium": round(eq, 2),
        "equalHighs": equal_highs,
        "equalLows": equal_lows,
        "liquidityPools": liquidity_pools,
        "stopHunt": stop_hunt,
        "displacement": displacement,
        "bos": bos,
        "choch": choch,
        "killZone": kill_zone,
        "inKillZone": in_kill_zone,
        "judasSwing": judas_swing,
        "lastSwingHigh": round(swing_highs[-1][1], 2) if swing_highs else None,
        "lastSwingLow": round(swing_lows[-1][1], 2) if swing_lows else None,
    }


def detect_smt_divergence(
    primary_closes: list[float],
    compare_closes: list[float],
    *,
    primary_symbol: str,
    compare_symbol: str,
) -> Optional[dict[str, Any]]:
    """SMT divergence — correlated index fails to confirm new high/low."""
    if len(primary_closes) < 20 or len(compare_closes) < 20:
        return None

    look = 15
    p_recent = primary_closes[-1]
    p_prior_high = max(primary_closes[-look:-1])
    p_prior_low = min(primary_closes[-look:-1])
    c_recent = compare_closes[-1]
    c_prior_high = max(compare_closes[-look:-1])
    c_prior_low = min(compare_closes[-look:-1])

    if p_recent > p_prior_high and c_recent <= c_prior_high:
        return {
            "type": "bearish_smt",
            "message": f"{primary_symbol} higher high, {compare_symbol} failed to confirm",
            "bias": "BEARISH",
        }
    if p_recent < p_prior_low and c_recent >= c_prior_low:
        return {
            "type": "bullish_smt",
            "message": f"{primary_symbol} lower low, {compare_symbol} failed to confirm",
            "bias": "BULLISH",
        }
    return None


def _consensus(reads: dict[str, TimeframeChartRead]) -> str:
    bull = sum(1 for r in reads.values() if r.direction == "BULLISH")
    bear = sum(1 for r in reads.values() if r.direction == "BEARISH")
    if bull >= bear + 2:
        return "BULLISH"
    if bear >= bull + 2:
        return "BEARISH"
    return "NEUTRAL"


# When 1m history is missing, derive higher TFs from native 5m bars (3→15m, 12→1h, 48→4h).
_FALLBACK_5M_FRAMES: list[tuple[str, int]] = [
    ("5m", 1),
    ("15m", 3),
    ("1h", 12),
    ("4h", 48),
]


def build_mtf_reads(
    candles_1m: list,
    spot: float,
    *,
    candles_5m: list | None = None,
) -> dict[str, TimeframeChartRead]:
    """Build MTF chart reads from 1m candles (no extra API calls)."""
    reads: dict[str, TimeframeChartRead] = {}
    if candles_1m:
        for frame in SCALP_TIMEFRAMES:
            label = frame["label"]
            if label == "1m":
                candles = candles_1m
            else:
                candles = resample_candles(candles_1m, frame["resample"])
            reads[label] = analyze_timeframe(candles, spot, label) if candles else TimeframeChartRead(
                label=label, price=round(spot, 2),
            )
        return reads

    if not candles_5m:
        return reads

    from app.engines.mtf_chart_analysis import resample_ohlc_bars

    for label, bucket in _FALLBACK_5M_FRAMES:
        candles = candles_5m if bucket <= 1 else resample_ohlc_bars(candles_5m, bucket)
        reads[label] = analyze_timeframe(candles, spot, label) if candles else TimeframeChartRead(
            label=label, price=round(spot, 2),
        )
    return reads


def build_chart_analysis(
    candles_1m: list,
    candles_5m: list,
    spot: float,
    profile: MarketProfile,
    *,
    prev_close: float = 0.0,
    day_high: float = 0.0,
    day_low: float = 0.0,
    compare_closes: Optional[list[float]] = None,
    compare_symbol: Optional[str] = None,
    symbol: str = "",
) -> ChartAnalysis:
    """Full chart analysis for snapshot — MTF + levels + patterns + SMC/ICT."""
    mtf_reads = build_mtf_reads(candles_1m, spot, candles_5m=candles_5m)
    consensus = _consensus(mtf_reads)

    primary_candles = candles_5m or candles_1m
    opens, highs, lows, closes = _candle_rows(primary_candles)
    if not closes:
        return ChartAnalysis(consensus=consensus, timeframes={k: v.model_dump() for k, v in mtf_reads.items()})

    from app.engines.spot_direction import _patch_live_close

    closes = _patch_live_close(closes, spot)
    if highs:
        highs = list(highs)
        highs[-1] = max(highs[-1], spot)
    if lows:
        lows = list(lows)
        lows[-1] = min(lows[-1], spot)

    swing_highs, swing_lows = _find_swings(highs, lows)
    sh = swing_highs[-1][1] if swing_highs else max(highs)
    sl = swing_lows[-1][1] if swing_lows else min(lows)
    trend = "UP" if closes[-1] >= closes[min(5, len(closes) - 1)] else "DOWN"

    dh = day_high or (max(highs) if highs else spot)
    dl = day_low or (min(lows) if lows else spot)
    pc = prev_close or (closes[0] if closes else spot)

    fib = compute_fibonacci_levels(sl, sh, spot, trend=trend)
    pivots = compute_pivot_points(dh, dl, pc)
    gann = compute_gann_levels(dl, dh)
    pitchfork = compute_andrews_pitchfork(swing_lows, swing_highs, spot)
    ichimoku = compute_ichimoku(highs, lows, closes, spot)
    smc = analyze_smc_ict(opens, highs, lows, closes, spot)

    patterns: list[dict[str, Any]] = []
    pattern_sources: list[tuple[str, list]] = []
    if candles_1m:
        pattern_sources.append(("5m", resample_candles(candles_1m, 5)))
        pattern_sources.append(("15m", resample_candles(candles_1m, 15)))
    elif candles_5m:
        pattern_sources.append(("5m", candles_5m))
        pattern_sources.append(("15m", resample_ohlc_bars(candles_5m, 3)))
    for label, tf_candles in pattern_sources:
        o, h, l, c = _candle_rows(tf_candles)
        patterns.extend(detect_candlestick_patterns(o, h, l, c, timeframe=label))

    # Deduplicate pattern names — keep strongest
    seen: dict[str, dict[str, Any]] = {}
    for p in patterns:
        key = f"{p['name']}_{p['timeframe']}"
        if key not in seen or p["strength"] > seen[key]["strength"]:
            seen[key] = p
    patterns = sorted(seen.values(), key=lambda x: -x["strength"])[:12]

    smt = None
    if compare_closes and compare_symbol:
        smt = detect_smt_divergence(closes, compare_closes, primary_symbol=symbol, compare_symbol=compare_symbol)

    aligned = sum(1 for r in mtf_reads.values() if r.direction == consensus or r.direction == "NEUTRAL")
    recent_closes = [round(c, 2) for c in closes[-30:]]

    return ChartAnalysis(
        consensus=consensus,
        alignedCount=aligned,
        totalTimeframes=len(mtf_reads),
        timeframes={k: v.model_dump() for k, v in mtf_reads.items()},
        recentCloses=recent_closes,
        fibonacci=fib,
        fibExtension=fib.get("extension", {}),
        pivots=pivots,
        gann=gann,
        pitchfork=pitchfork,
        ichimoku=ichimoku,
        patterns=patterns,
        institutional=smc,
        smtDivergence=smt,
        keySignals=_build_key_signals(fib, pivots, ichimoku, smc, patterns, consensus),
    )


def _build_key_signals(
    fib: dict[str, Any],
    pivots: dict[str, float],
    ichimoku: dict[str, Any],
    smc: dict[str, Any],
    patterns: list[dict[str, Any]],
    consensus: str,
) -> list[str]:
    signals: list[str] = []
    if fib.get("nearestLevel"):
        signals.append(f"Fib {fib['nearestLevel']} ({fib.get('zone', '')})")
    if pivots.get("P"):
        signals.append(f"Pivot P {pivots['P']}")
    smart = str(ichimoku.get("smartBias") or ichimoku.get("cloudBias") or "")
    if smart:
        score = ichimoku.get("smartScore")
        score_bit = f" {score:.0f}" if isinstance(score, (int, float)) else ""
        signals.append(
            f"Smart Ichimoku {smart}{score_bit} ({ichimoku.get('priceVsCloud', '')})"
        )
    elif ichimoku.get("cloudBias"):
        signals.append(f"Ichimoku {ichimoku['cloudBias']} ({ichimoku.get('priceVsCloud', '')})")
    if smc.get("stopHunt"):
        signals.append(f"Stop hunt: {smc['stopHunt']}")
    if smc.get("displacement"):
        signals.append("Displacement candle")
    if smc.get("judasSwing"):
        signals.append("Judas swing (kill zone)")
    if smc.get("bos"):
        signals.append(smc["bos"])
    for p in patterns[:3]:
        signals.append(f"{p['name']} ({p['timeframe']})")
    signals.append(f"MTF {consensus}")
    return signals[:10]
