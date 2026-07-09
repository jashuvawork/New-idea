"""Index chart analysis — signed spot momentum and CE/PE alignment."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.chart_indicators import _ema_series, compute_macd, compute_rsi
from app.models.schemas import MarketProfile, Side, SpotChart


def _candle_rows(candles: list) -> tuple[list[float], list[float], list[float], list[float]]:
    opens, highs, lows, closes = [], [], [], []
    for c in candles or []:
        if isinstance(c, list) and len(c) >= 5:
            opens.append(float(c[1]))
            highs.append(float(c[2]))
            lows.append(float(c[3]))
            closes.append(float(c[4]))
        elif isinstance(c, dict):
            opens.append(float(c.get("open", 0) or 0))
            highs.append(float(c.get("high", 0) or 0))
            lows.append(float(c.get("low", 0) or 0))
            closes.append(float(c.get("close", 0) or 0))
    return opens, highs, lows, closes


def _pct_change(closes: list[float], bars: int) -> float:
    if len(closes) <= bars or closes[-bars - 1] == 0:
        return 0.0
    return ((closes[-1] - closes[-bars - 1]) / closes[-bars - 1]) * 100


def _ema(closes: list[float], period: int) -> float:
    if not closes:
        return 0.0
    window = closes[-period:] if len(closes) >= period else closes
    return sum(window) / len(window)


def _ema(closes: list[float], period: int) -> float:
    if not closes:
        return 0.0
    series = _ema_series(closes, period)
    return series[-1] if series else 0.0


def _indicator_closes(candles_5m: list, candles_1m: list | None) -> list[float]:
    """RSI/MACD input — prefer extended 5m; fall back to 1m when session is still thin."""
    if candles_1m:
        from app.engines.mtf_chart_analysis import resample_candles

        settings = get_settings()
        extended_5m = resample_candles(candles_1m, settings.spot_chart_timeframe_minutes)
        closes_5m_ext = _candle_rows(extended_5m)[3]
        if len(closes_5m_ext) >= 35:
            return closes_5m_ext
        _, _, _, closes_1m = _candle_rows(candles_1m)
        if len(closes_1m) >= 15:
            return closes_1m
    _, _, _, closes_5m = _candle_rows(candles_5m)
    return closes_5m


def build_spot_chart(
    candles_5m: list,
    spot: float,
    profile: MarketProfile,
    *,
    indicator_candles_1m: list | None = None,
) -> SpotChart:
    """
    Index chart read from 5m candles: direction, EMA9/21, RSI, MACD.
    RSI/MACD use extended 5m series resampled from 1m when available (MACD warmup).
    """
    opens, _, _, closes = _candle_rows(candles_5m)
    ind_closes = _indicator_closes(candles_5m, indicator_candles_1m)

    if not closes or spot <= 0:
        return SpotChart(direction="NEUTRAL", spot=spot, timeframe="5m")

    # On 5m: 1 bar = 5min, 3 bars = 15min, 6 = 30min, 12 = 60min
    mom5 = _pct_change(closes, 1)
    mom10 = _pct_change(closes, 2)
    mom15 = _pct_change(closes, 3) if len(closes) > 3 else mom10
    mom30 = _pct_change(closes, 6) if len(closes) > 6 else mom15

    ema9 = _ema(closes, min(9, len(closes)))
    ema21 = _ema(closes, min(21, len(closes)))
    if ema9 > ema21 * 1.00015:
        ema_bias = "BULLISH"
    elif ema9 < ema21 * 0.99985:
        ema_bias = "BEARISH"
    else:
        ema_bias = "NEUTRAL"

    green = red = 0
    for o, c in zip(opens[-8:], closes[-8:]):
        if c > o:
            green += 1
        elif c < o:
            red += 1
    if green >= red + 2:
        candle_bias = "BULLISH"
    elif red >= green + 2:
        candle_bias = "BEARISH"
    else:
        candle_bias = "NEUTRAL"

    poc = profile.poc or spot
    orh = profile.openingRangeHigh or profile.vah or spot
    orl = profile.openingRangeLow or profile.val or spot
    if spot > orh:
        or_pos = "ABOVE"
    elif spot < orl:
        or_pos = "BELOW"
    else:
        or_pos = "INSIDE"

    above_poc = spot > poc * 1.0001
    below_poc = spot < poc * 0.9999

    rsi_read = compute_rsi(ind_closes)
    macd_read = compute_macd(ind_closes)

    bullish = bearish = 0
    if mom5 > 0.04:
        bullish += 2
    elif mom5 < -0.04:
        bearish += 2
    if mom15 > 0.06:
        bullish += 2
    elif mom15 < -0.06:
        bearish += 2
    if ema_bias == "BULLISH":
        bullish += 2
    elif ema_bias == "BEARISH":
        bearish += 2
    if candle_bias == "BULLISH":
        bullish += 1
    elif candle_bias == "BEARISH":
        bearish += 1
    if above_poc:
        bullish += 1
    elif below_poc:
        bearish += 1
    if or_pos == "ABOVE":
        bullish += 1
    elif or_pos == "BELOW":
        bearish += 1
    if rsi_read.bias == "OVERSOLD":
        if mom15 > 0 and mom30 > -0.05:
            bullish += 1
    elif rsi_read.bias == "OVERBOUGHT":
        bearish += 1
    elif rsi_read.value > 55:
        bullish += 1
    elif rsi_read.value < 45:
        bearish += 1
    if macd_read.bias == "BULLISH":
        bullish += 2
    elif macd_read.bias == "BEARISH":
        bearish += 2

    if bullish >= bearish + 3:
        direction = "BULLISH"
    elif bearish >= bullish + 3:
        direction = "BEARISH"
    elif mom30 < -0.08 and mom15 <= 0:
        direction = "BEARISH"
    elif mom30 > 0.08 and mom15 >= 0:
        direction = "BULLISH"
    elif mom5 > 0.02 and mom15 > 0.05 and mom30 > 0:
        direction = "BULLISH"
    elif mom5 < -0.02 and mom15 < -0.05 and mom30 < 0:
        direction = "BEARISH"
    elif mom15 < 0 and mom30 < 0:
        direction = "BEARISH"
    elif mom15 > 0 and mom30 > 0:
        direction = "BULLISH"
    else:
        direction = "NEUTRAL"

    trend_strength = min(
        100.0,
        abs(mom15) * 15 + abs(mom5) * 25 + abs(bullish - bearish) * 8
        + abs(rsi_read.value - 50) * 0.15 + abs(macd_read.histogram) * 2,
    )

    return SpotChart(
        direction=direction,
        spot=round(spot, 2),
        timeframe="5m",
        barCount=len(closes),
        momentum5Pct=round(mom5, 3),
        momentum10Pct=round(mom10, 3),
        momentum15Pct=round(mom15, 3),
        momentum30Pct=round(mom30, 3),
        trendStrength=round(trend_strength, 1),
        emaBias=ema_bias,
        ema9=round(ema9, 2),
        ema21=round(ema21, 2),
        candleBias=candle_bias,
        orPosition=or_pos,
        abovePoc=above_poc,
        belowPoc=below_poc,
        poc=round(poc, 2),
        rsi=rsi_read.value,
        rsiBias=rsi_read.bias,
        macd=macd_read.line,
        macdSignal=macd_read.signal,
        macdHistogram=macd_read.histogram,
        macdBias=macd_read.bias,
    )


def reconcile_spot_chart_with_mtf(
    spot_chart: SpotChart,
    chart_analysis: Optional[Any],
    breadth_bias: str = "NEUTRAL",
    *,
    from_open_pct: float = 0.0,
) -> SpotChart:
    """
    Align primary spotChart with MTF consensus when a lone 5m flicker disagrees
    with session + multi-timeframe bearish/bullish read.
    """
    if not chart_analysis:
        return spot_chart

    consensus = str(getattr(chart_analysis, "consensus", None) or "NEUTRAL").upper()
    spot_dir = (spot_chart.direction or "NEUTRAL").upper()
    if consensus not in ("BULLISH", "BEARISH"):
        return spot_chart
    if spot_dir == consensus:
        return spot_chart

    tfs = getattr(chart_analysis, "timeframes", None) or {}
    bull = bear = 0
    for tf in tfs.values():
        d = tf.get("direction") if isinstance(tf, dict) else getattr(tf, "direction", "NEUTRAL")
        d = str(d or "NEUTRAL").upper()
        if d == "BULLISH":
            bull += 1
        elif d == "BEARISH":
            bear += 1

    consensus_ct = bear if consensus == "BEARISH" else bull
    breadth = (breadth_bias or "NEUTRAL").upper()
    total = int(getattr(chart_analysis, "totalTimeframes", 0) or len(tfs) or 0)

    # MTF + breadth agree — always trust over lone 5m oversold bounce
    if consensus == "BEARISH" and bear >= 2 and breadth == "BEARISH":
        return spot_chart.model_copy(update={"direction": "BEARISH"})
    if consensus == "BULLISH" and bull >= 2 and breadth == "BULLISH":
        return spot_chart.model_copy(update={"direction": "BULLISH"})

    # Tiny 5m flicker vs 3+ bearish/bullish TFs
    if consensus == "BEARISH" and spot_dir == "BULLISH" and bear >= 2:
        if abs(spot_chart.momentum5Pct) < 0.5 or spot_chart.momentum30Pct < 0:
            return spot_chart.model_copy(update={"direction": "BEARISH"})
    if consensus == "BULLISH" and spot_dir == "BEARISH" and bull >= 2:
        if abs(spot_chart.momentum5Pct) < 0.5 or spot_chart.momentum30Pct > 0:
            return spot_chart.model_copy(update={"direction": "BULLISH"})

    override = consensus_ct >= 3
    if total >= 4 and consensus_ct >= total - 1:
        override = True
    if breadth == consensus and consensus_ct >= 2:
        override = True
    if consensus == "BEARISH" and from_open_pct <= -0.08 and consensus_ct >= 2:
        override = True
    if consensus == "BULLISH" and from_open_pct >= 0.08 and consensus_ct >= 2:
        override = True

    if override:
        return spot_chart.model_copy(update={"direction": consensus})
    return spot_chart


def analyze_spot_chart(
    candles: list,
    spot: float,
    profile: MarketProfile,
) -> SpotChart:
    """
    Back-compat wrapper — resamples 1m input to 5m and builds spot chart.
    """
    from app.engines.mtf_chart_analysis import resample_candles

    settings = get_settings()
    candles_5m = resample_candles(candles, settings.spot_chart_timeframe_minutes) if candles else []
    return build_spot_chart(candles_5m, spot, profile, indicator_candles_1m=candles)


def side_aligned_with_chart(side: Side | str, chart: Optional[SpotChart]) -> bool:
    if not chart:
        return True
    direction = (chart.direction or "NEUTRAL").upper()
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    if direction == "NEUTRAL":
        if side_val == "CALL":
            return chart.momentum5Pct >= -0.02
        return chart.momentum5Pct <= 0.02
    if side_val == "CALL":
        return direction == "BULLISH"
    return direction == "BEARISH"


def chart_blocks_side(
    side: Side | str,
    chart: Optional[SpotChart],
    *,
    trade_score: float = 0.0,
    momentum_surge: bool = False,
    breadth_aligned_bypass: bool = False,
    premium_led_bypass: bool = False,
    expiry_explosion_bypass: bool = False,
) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.chart_alignment_enabled or not chart:
        return False, "ok"

    side_val = side.value if isinstance(side, Side) else str(side).upper()
    min_strength = settings.chart_min_trend_strength
    min_mom = settings.chart_min_momentum_pct
    override = settings.chart_override_min_score

    # Hard direction conflict — breadth-aligned / premium-led / expiry explosion bypass.
    if side_val == "CALL" and chart.direction == "BEARISH" and chart.trendStrength >= min_strength:
        if breadth_aligned_bypass or premium_led_bypass or expiry_explosion_bypass:
            return False, "ok"
        return True, "chart_bearish_no_calls"
    if side_val == "PUT" and chart.direction == "BULLISH" and chart.trendStrength >= min_strength:
        if breadth_aligned_bypass or premium_led_bypass or expiry_explosion_bypass:
            return False, "ok"
        return True, "chart_bullish_no_puts"

    if momentum_surge or trade_score >= override:
        return False, "ok"

    if expiry_explosion_bypass and side_val == "CALL":
        return False, "ok"

    if side_val == "CALL":
        if chart.momentum5Pct < -min_mom and chart.momentum15Pct < 0:
            return True, "chart_declining_no_calls"
        if chart.orPosition == "BELOW" and chart.belowPoc and chart.momentum5Pct < 0:
            return True, "chart_below_poc_no_calls"
        if chart.rsiBias == "OVERBOUGHT" and chart.macdBias == "BEARISH" and chart.momentum5Pct < 0:
            return True, "chart_rsi_macd_bearish_no_calls"
    else:
        if chart.momentum5Pct > min_mom and chart.momentum15Pct > 0:
            return True, "chart_rallying_no_puts"
        if chart.orPosition == "ABOVE" and chart.abovePoc and chart.momentum5Pct > 0:
            return True, "chart_above_poc_no_puts"
        if chart.rsiBias == "OVERSOLD" and chart.macdBias == "BULLISH" and chart.momentum5Pct > 0:
            return True, "chart_rsi_macd_bullish_no_puts"

    return False, "ok"


HARD_CHART_BLOCK_REASONS = frozenset({
    "chart_bearish_no_calls",
    "chart_bullish_no_puts",
})


def is_hard_chart_block(reason: str) -> bool:
    return reason in HARD_CHART_BLOCK_REASONS


def chart_rank_adjustment(side: Side | str, chart: Optional[SpotChart]) -> float:
    settings = get_settings()
    if not settings.chart_alignment_enabled or not chart:
        return 0.0
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    bonus = settings.chart_alignment_rank_bonus
    if side_aligned_with_chart(side_val, chart):
        if chart.direction in ("BULLISH", "BEARISH"):
            return bonus
        return bonus * 0.4
    if chart.trendStrength >= settings.chart_min_trend_strength:
        return -bonus
    return -bonus * 0.5


def signed_momentum_pct(candles: list, bars: int = 5) -> float:
    _, _, _, closes = _candle_rows(candles)
    return round(_pct_change(closes, bars), 3)


def chart_summary_dict(chart: SpotChart) -> dict[str, Any]:
    return {
        "direction": chart.direction,
        "timeframe": chart.timeframe,
        "barCount": chart.barCount,
        "momentum5Pct": chart.momentum5Pct,
        "momentum15Pct": chart.momentum15Pct,
        "trendStrength": chart.trendStrength,
        "emaBias": chart.emaBias,
        "ema9": chart.ema9,
        "ema21": chart.ema21,
        "candleBias": chart.candleBias,
        "orPosition": chart.orPosition,
        "abovePoc": chart.abovePoc,
        "rsi": chart.rsi,
        "rsiBias": chart.rsiBias,
        "macd": chart.macd,
        "macdSignal": chart.macdSignal,
        "macdHistogram": chart.macdHistogram,
        "macdBias": chart.macdBias,
        "recommendedSide": "CALL" if chart.direction == "BULLISH" else (
            "PUT" if chart.direction == "BEARISH" else "WAIT"
        ),
    }


def analyze_premium_chart(candles: list, ltp: float) -> "PremiumChart":
    """Option premium chart from Upstox 1m candles."""
    from app.models.schemas import PremiumChart

    _, highs, lows, closes = _candle_rows(candles)
    volumes = []
    for c in candles or []:
        if isinstance(c, list) and len(c) >= 6:
            volumes.append(float(c[5] or 0))
        elif isinstance(c, dict):
            volumes.append(float(c.get("volume", 0) or 0))

    if not closes or ltp <= 0:
        return PremiumChart(lastPremium=ltp)

    mom3 = _pct_change(closes, 3)
    mom5 = _pct_change(closes, 5)
    vwap = sum(c * v for c, v in zip(closes, volumes)) / max(1, sum(volumes)) if volumes else closes[-1]

    green = red = 0
    opens, _, _, _ = _candle_rows(candles)
    for o, c in zip(opens[-6:], closes[-6:]):
        if c > o:
            green += 1
        elif c < o:
            red += 1

    if mom5 > 0.25 and mom3 >= 0:
        direction = "BULLISH"
    elif mom5 < -0.25 and mom3 <= 0:
        direction = "BEARISH"
    elif green >= red + 2:
        direction = "BULLISH"
    elif red >= green + 2:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    vol_recent = sum(volumes[-3:]) if len(volumes) >= 3 else 0
    vol_prior = sum(volumes[-6:-3]) if len(volumes) >= 6 else vol_recent or 1
    vol_surge = vol_recent / max(1, vol_prior)

    rsi_read = compute_rsi(closes)
    macd_read = compute_macd(closes)

    return PremiumChart(
        direction=direction,
        lastPremium=round(ltp, 2),
        momentum3Pct=round(mom3, 3),
        momentum5Pct=round(mom5, 3),
        volumeSurge=round(vol_surge, 2),
        vwap=round(vwap, 2),
        aboveVwap=ltp > vwap * 1.001,
        rsi=rsi_read.value,
        rsiBias=rsi_read.bias,
        macd=macd_read.line,
        macdSignal=macd_read.signal,
        macdHistogram=macd_read.histogram,
        macdBias=macd_read.bias,
    )


def premium_blocks_entry(side: Side | str, premium: "PremiumChart", trade_score: float = 0.0) -> tuple[bool, str]:
    """Block when option premium is fading at execution — bad fill timing."""
    settings = get_settings()
    if not settings.execution_chart_premium_check_enabled or not premium:
        return False, "ok"
    if trade_score >= settings.chart_override_min_score:
        return False, "ok"

    min_mom = settings.execution_chart_min_premium_momentum_pct

    if premium.momentum5Pct < min_mom and premium.momentum3Pct < 0:
        return True, "premium_fading_at_execution"
    if premium.direction == "BEARISH" and premium.momentum5Pct < -0.15:
        return True, "premium_chart_fading"
    return False, "ok"


def pro_index_quote_context(quote: dict[str, Any], spot: float) -> dict[str, Any]:
    """Day structure from Upstox index quote."""
    prev = float(quote.get("close") or quote.get("prev_close") or spot)
    ohlc = quote.get("ohlc") or {}
    day_open = float(ohlc.get("open") or quote.get("open") or spot)
    day_high = float(ohlc.get("high") or quote.get("high") or spot)
    day_low = float(ohlc.get("low") or quote.get("low") or spot)
    gap_pct = ((spot - prev) / prev * 100) if prev else 0.0
    from_open_pct = ((spot - day_open) / day_open * 100) if day_open else 0.0
    range_pct = ((day_high - day_low) / day_low * 100) if day_low else 0.0
    return {
        "prevClose": round(prev, 2),
        "dayOpen": round(day_open, 2),
        "dayHigh": round(day_high, 2),
        "dayLow": round(day_low, 2),
        "gapPct": round(gap_pct, 3),
        "fromOpenPct": round(from_open_pct, 3),
        "dayRangePct": round(range_pct, 3),
        "belowDayOpen": spot < day_open * 0.9999,
        "aboveDayOpen": spot > day_open * 1.0001,
    }
