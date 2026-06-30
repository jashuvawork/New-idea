"""Index chart analysis — signed spot momentum and CE/PE alignment."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
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


def analyze_spot_chart(
    candles: list,
    spot: float,
    profile: MarketProfile,
) -> SpotChart:
    """
    Multi-factor index chart read from 1m candles:
    momentum, EMA stack, POC/OR position, candle color bias.
    """
    _, _, _, closes = _candle_rows(candles)
    opens, _, _, _ = _candle_rows(candles)

    if not closes or spot <= 0:
        return SpotChart(direction="NEUTRAL", spot=spot)

    mom5 = _pct_change(closes, 5)
    mom10 = _pct_change(closes, 10)
    mom15 = _pct_change(closes, 15) if len(closes) > 15 else mom10
    mom30 = _pct_change(closes, 30) if len(closes) > 30 else mom15

    ema5 = _ema(closes, 5)
    ema15 = _ema(closes, 15)
    if ema5 > ema15 * 1.00015:
        ema_bias = "BULLISH"
    elif ema5 < ema15 * 0.99985:
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

    if bullish >= bearish + 3:
        direction = "BULLISH"
    elif bearish >= bullish + 3:
        direction = "BEARISH"
    elif mom5 > 0.02 and mom15 >= 0:
        direction = "BULLISH"
    elif mom5 < -0.02 and mom15 <= 0:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    trend_strength = min(
        100.0,
        abs(mom15) * 15 + abs(mom5) * 25 + abs(bullish - bearish) * 8,
    )

    return SpotChart(
        direction=direction,
        spot=round(spot, 2),
        momentum5Pct=round(mom5, 3),
        momentum10Pct=round(mom10, 3),
        momentum15Pct=round(mom15, 3),
        momentum30Pct=round(mom30, 3),
        trendStrength=round(trend_strength, 1),
        emaBias=ema_bias,
        candleBias=candle_bias,
        orPosition=or_pos,
        abovePoc=above_poc,
        belowPoc=below_poc,
        poc=round(poc, 2),
    )


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
) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.chart_alignment_enabled or not chart:
        return False, "ok"

    side_val = side.value if isinstance(side, Side) else str(side).upper()
    min_strength = settings.chart_min_trend_strength
    min_mom = settings.chart_min_momentum_pct
    override = settings.chart_override_min_score

    if momentum_surge or trade_score >= override:
        return False, "ok"

    if side_val == "CALL":
        if chart.direction == "BEARISH" and chart.trendStrength >= min_strength:
            return True, "chart_bearish_no_calls"
        if chart.momentum5Pct < -min_mom and chart.momentum15Pct < 0:
            return True, "chart_declining_no_calls"
        if chart.orPosition == "BELOW" and chart.belowPoc and chart.momentum5Pct < 0:
            return True, "chart_below_poc_no_calls"
    else:
        if chart.direction == "BULLISH" and chart.trendStrength >= min_strength:
            return True, "chart_bullish_no_puts"
        if chart.momentum5Pct > min_mom and chart.momentum15Pct > 0:
            return True, "chart_rallying_no_puts"
        if chart.orPosition == "ABOVE" and chart.abovePoc and chart.momentum5Pct > 0:
            return True, "chart_above_poc_no_puts"

    return False, "ok"


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
        "momentum5Pct": chart.momentum5Pct,
        "momentum15Pct": chart.momentum15Pct,
        "trendStrength": chart.trendStrength,
        "emaBias": chart.emaBias,
        "candleBias": chart.candleBias,
        "orPosition": chart.orPosition,
        "abovePoc": chart.abovePoc,
        "recommendedSide": "CALL" if chart.direction == "BULLISH" else (
            "PUT" if chart.direction == "BEARISH" else "WAIT"
        ),
    }
