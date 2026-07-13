"""Advanced chart analysis — MTF, Fibonacci, pivots, Gann, Ichimoku, SMC/ICT, patterns."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.engines.chart_indicators import compute_macd, compute_rsi
from app.engines.mtf_chart_analysis import SCALP_TIMEFRAMES, analyze_timeframe, resample_candles
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


def compute_ichimoku(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    spot: float,
) -> dict[str, Any]:
    """Ichimoku cloud — standard periods adapted when bars are limited."""

    def _mid(h: list[float], l: list[float], period: int) -> float:
        if not h or not l:
            return spot
        p = min(period, len(h))
        return (max(h[-p:]) + min(l[-p:])) / 2

    tenkan = _mid(highs, lows, 9)
    kijun = _mid(highs, lows, 26)
    senkou_a = (tenkan + kijun) / 2
    senkou_b = _mid(highs, lows, 52)
    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)

    if spot > cloud_top:
        cloud_bias = "BULLISH"
    elif spot < cloud_bottom:
        cloud_bias = "BEARISH"
    else:
        cloud_bias = "NEUTRAL"

    tk_cross = "BULLISH" if tenkan > kijun else "BEARISH" if tenkan < kijun else "NEUTRAL"
    return {
        "tenkan": round(tenkan, 2),
        "kijun": round(kijun, 2),
        "senkouA": round(senkou_a, 2),
        "senkouB": round(senkou_b, 2),
        "cloudTop": round(cloud_top, 2),
        "cloudBottom": round(cloud_bottom, 2),
        "cloudBias": cloud_bias,
        "tkCross": tk_cross,
        "priceVsCloud": "ABOVE" if spot > cloud_top else "BELOW" if spot < cloud_bottom else "INSIDE",
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


def build_mtf_reads(candles_1m: list, spot: float) -> dict[str, TimeframeChartRead]:
    """Build MTF chart reads from 1m candles (no extra API calls)."""
    reads: dict[str, TimeframeChartRead] = {}
    if not candles_1m:
        return reads
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
    mtf_reads = build_mtf_reads(candles_1m, spot)
    consensus = _consensus(mtf_reads)

    primary_candles = candles_5m or candles_1m
    opens, highs, lows, closes = _candle_rows(primary_candles)
    if not closes:
        return ChartAnalysis(consensus=consensus, timeframes={k: v.model_dump() for k, v in mtf_reads.items()})

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
    for label, resample in (("5m", 5), ("15m", 15)):
        if candles_1m:
            tf_candles = candles_1m if label == "1m" else resample_candles(candles_1m, resample)
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
    if ichimoku.get("cloudBias"):
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
