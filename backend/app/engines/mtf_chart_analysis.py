"""Multi-timeframe chart analysis — 1m/5m/15m/1h/4h from Upstox for scalp pre-test."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.config import get_settings
from app.engines.spot_direction import _candle_rows, _ema, _pct_change
from app.models.schemas import Side, TimeframeChartRead
from app.services.upstox import UpstoxClient

logger = logging.getLogger(__name__)

# Scalp timeframes — V3 intraday unit/interval (Upstox direct)
SCALP_TIMEFRAMES: list[dict[str, Any]] = [
    {"label": "1m", "unit": "minutes", "interval": 1, "resample": 1},
    {"label": "5m", "unit": "minutes", "interval": 5, "resample": 5},
    {"label": "15m", "unit": "minutes", "interval": 15, "resample": 15},
    {"label": "1h", "unit": "hours", "interval": 1, "resample": 60},
    {"label": "4h", "unit": "hours", "interval": 4, "resample": 240},
]


def resample_candles(candles_1m: list, period: int) -> list[list[float]]:
    """Aggregate 1m OHLCV into higher timeframe bars."""
    if period <= 1 or not candles_1m:
        return candles_1m

    buckets: list[list[list]] = []
    chunk: list = []
    for c in candles_1m:
        chunk.append(c)
        if len(chunk) >= period:
            buckets.append(chunk)
            chunk = []
    if chunk and len(chunk) >= max(2, period // 2):
        buckets.append(chunk)

    out: list[list[float]] = []
    for bucket in buckets:
        opens, highs, lows, closes, vols = [], [], [], [], []
        for c in bucket:
            if isinstance(c, list) and len(c) >= 5:
                opens.append(float(c[1]))
                highs.append(float(c[2]))
                lows.append(float(c[3]))
                closes.append(float(c[4]))
                vols.append(float(c[5]) if len(c) > 5 else 0)
            elif isinstance(c, dict):
                opens.append(float(c.get("open", 0) or 0))
                highs.append(float(c.get("high", 0) or 0))
                lows.append(float(c.get("low", 0) or 0))
                closes.append(float(c.get("close", 0) or 0))
                vols.append(float(c.get("volume", 0) or 0))
        if not closes:
            continue
        out.append([0, opens[0], max(highs), min(lows), closes[-1], sum(vols)])
    return out


def analyze_timeframe(candles: list, price: float, label: str) -> TimeframeChartRead:
    """Direction + momentum read for one timeframe."""
    opens, _, _, closes = _candle_rows(candles)
    if not closes or price <= 0:
        return TimeframeChartRead(label=label, price=round(price, 2))

    lookback = min(5, len(closes) - 1) if len(closes) > 1 else 1
    mom = _pct_change(closes, lookback)
    mom3 = _pct_change(closes, min(3, len(closes) - 1)) if len(closes) > 3 else mom

    ema_fast = _ema(closes, min(8, len(closes)))
    ema_slow = _ema(closes, min(21, len(closes)))
    if ema_fast > ema_slow * 1.0002:
        ema_bias = "BULLISH"
    elif ema_fast < ema_slow * 0.9998:
        ema_bias = "BEARISH"
    else:
        ema_bias = "NEUTRAL"

    green = red = 0
    for o, c in zip(opens[-4:], closes[-4:]):
        if c > o:
            green += 1
        elif c < o:
            red += 1

    bullish = bearish = 0
    if mom > 0.03:
        bullish += 2
    elif mom < -0.03:
        bearish += 2
    if ema_bias == "BULLISH":
        bullish += 2
    elif ema_bias == "BEARISH":
        bearish += 2
    if green >= red + 1:
        bullish += 1
    elif red >= green + 1:
        bearish += 1

    if bullish >= bearish + 2:
        direction = "BULLISH"
    elif bearish >= bullish + 2:
        direction = "BEARISH"
    elif mom > 0.01:
        direction = "BULLISH"
    elif mom < -0.01:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    strength = min(100.0, abs(mom) * 30 + abs(mom3) * 20 + abs(bullish - bearish) * 10)

    return TimeframeChartRead(
        label=label,
        direction=direction,
        momentumPct=round(mom, 3),
        momentum3Pct=round(mom3, 3),
        trendStrength=round(strength, 1),
        emaBias=ema_bias,
        price=round(price, 2),
        barCount=len(closes),
    )


def _tf_dict(read: TimeframeChartRead) -> dict[str, Any]:
    return {
        "label": read.label,
        "direction": read.direction,
        "momentumPct": read.momentumPct,
        "momentum3Pct": read.momentum3Pct,
        "trendStrength": read.trendStrength,
        "emaBias": read.emaBias,
        "barCount": read.barCount,
        "alignedCall": read.direction in ("BULLISH", "NEUTRAL") and read.momentumPct >= -0.02,
        "alignedPut": read.direction in ("BEARISH", "NEUTRAL") and read.momentumPct <= 0.02,
    }


def mtf_summary(reads: dict[str, TimeframeChartRead], side: Side) -> dict[str, Any]:
    side_val = side.value
    aligned = sum(
        1 for r in reads.values()
        if (side_val == "CALL" and r.direction != "BEARISH" and r.momentumPct >= -0.03)
        or (side_val == "PUT" and r.direction != "BULLISH" and r.momentumPct <= 0.03)
    )
    oppose = sum(
        1 for r in reads.values()
        if (side_val == "CALL" and r.direction == "BEARISH" and r.trendStrength >= 20)
        or (side_val == "PUT" and r.direction == "BULLISH" and r.trendStrength >= 20)
    )
    return {
        "timeframes": {k: _tf_dict(v) for k, v in reads.items()},
        "alignedCount": aligned,
        "opposingCount": oppose,
        "total": len(reads),
        "consensus": _consensus_direction(reads),
    }


def _consensus_direction(reads: dict[str, TimeframeChartRead]) -> str:
    bull = sum(1 for r in reads.values() if r.direction == "BULLISH")
    bear = sum(1 for r in reads.values() if r.direction == "BEARISH")
    if bull >= bear + 2:
        return "BULLISH"
    if bear >= bull + 2:
        return "BEARISH"
    return "NEUTRAL"


async def fetch_mtf_charts(
    client: UpstoxClient,
    instrument_key: str,
    price: float,
    *,
    force_refresh: bool = True,
) -> dict[str, TimeframeChartRead]:
    """Fetch and analyze all scalp timeframes for index or option leg."""
    settings = get_settings()
    candles_1m = await client.get_historical_candles(
        instrument_key,
        interval="1minute",
        count=settings.execution_mtf_1m_bars,
        force_refresh=force_refresh,
    )

    reads: dict[str, TimeframeChartRead] = {}
    reads["1m"] = analyze_timeframe(candles_1m, price, "1m")

    async def _native_or_resample(frame: dict[str, Any]) -> tuple[str, list]:
        label = frame["label"]
        if settings.execution_mtf_use_v3_native:
            try:
                candles = await client.get_intraday_candles_v3(
                    instrument_key,
                    unit=frame["unit"],
                    interval=frame["interval"],
                    force_refresh=force_refresh,
                )
                if candles:
                    return label, candles
            except Exception as exc:
                logger.debug("V3 %s failed, resampling 1m: %s", label, exc)
        return label, resample_candles(candles_1m, frame["resample"])

    other_frames = [f for f in SCALP_TIMEFRAMES if f["label"] != "1m"]
    results = await asyncio.gather(*[_native_or_resample(f) for f in other_frames])
    for label, candles in results:
        reads[label] = analyze_timeframe(candles, price, label) if candles else TimeframeChartRead(
            label=label, price=round(price, 2),
        )
    return reads


def validate_mtf_scalp(
    side: Side,
    index_mtf: dict[str, TimeframeChartRead],
    premium_mtf: Optional[dict[str, TimeframeChartRead]] = None,
    *,
    trade_score: float = 0.0,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Pre-trade MTF gate for scalping:
    - 1m + 5m index must align with CE/PE
    - Min aligned count across all TFs
    - Higher TFs (15m/1h/4h) must not all oppose
    - Premium 1m/5m must not be fading
    """
    settings = get_settings()
    if not settings.execution_mtf_enabled or not index_mtf:
        return True, "ok", {}

    if trade_score >= settings.chart_override_min_score:
        return True, "ok", mtf_summary(index_mtf, side)

    side_val = side.value
    meta = {
        "index": mtf_summary(index_mtf, side),
        "passed": True,
    }
    if premium_mtf:
        meta["premium"] = mtf_summary(premium_mtf, side)

    def _opposes(r: TimeframeChartRead) -> bool:
        if side_val == "CALL":
            return r.direction == "BEARISH" and r.trendStrength >= 18
        return r.direction == "BULLISH" and r.trendStrength >= 18

    def _aligned(r: TimeframeChartRead) -> bool:
        if side_val == "CALL":
            return r.direction != "BEARISH" and r.momentumPct >= -0.03
        return r.direction != "BULLISH" and r.momentumPct <= 0.03

    # Scalp anchors: 1m + 5m required
    for required in ("1m", "5m"):
        tf = index_mtf.get(required)
        if tf and not _aligned(tf):
            return False, f"exec_mtf_{required}_opposes_{side_val.lower()}", meta

    aligned_count = sum(1 for r in index_mtf.values() if _aligned(r))
    if aligned_count < settings.execution_mtf_min_align:
        meta["passed"] = False
        return False, f"exec_mtf_align_{aligned_count}_of_{len(index_mtf)}", meta

    htf_labels = ("15m", "1h", "4h")
    htf_oppose = sum(1 for lb in htf_labels if (t := index_mtf.get(lb)) and _opposes(t))
    if settings.execution_mtf_block_htf_conflict and htf_oppose >= 2:
        meta["passed"] = False
        return False, "exec_mtf_higher_tf_conflict", meta

    if premium_mtf and settings.execution_chart_premium_check_enabled:
        for req in ("1m", "5m"):
            pt = premium_mtf.get(req)
            if pt and pt.direction == "BEARISH" and pt.momentumPct < settings.execution_chart_min_premium_momentum_pct:
                meta["passed"] = False
                return False, f"exec_mtf_premium_{req}_fading", meta

    meta["passed"] = True
    return True, "ok", meta
