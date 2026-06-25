"""Premarket analysis — gap, volume, constituent breadth, open-play scenarios."""

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.engines.constituent_engine import build_constituent_heatmap, breadth_from_constituents
from app.engines.simple_profit import get_session_targets
from app.models.schemas import (
    Breadth,
    ConstituentHeatmap,
    MarketPhase,
    MarketProfile,
    PremarketAnalysis,
    Regime,
    SymbolSnapshot,
)
from app.services.upstox import UpstoxClient, UpstoxError, get_market_phase

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Gap % thresholds (index-level) — tuned for Indian open volatility
_GAP_THRESHOLDS = {
    "NIFTY": {"flat": 0.12, "small": 0.35, "moderate": 0.70, "large": 1.20},
    "BANKNIFTY": {"flat": 0.15, "small": 0.45, "moderate": 0.90, "large": 1.50},
    "SENSEX": {"flat": 0.12, "small": 0.35, "moderate": 0.70, "large": 1.20},
}


def _minutes_to_open() -> int:
    now = datetime.now(IST)
    open_minutes = 9 * 60 + 15
    current = now.hour * 60 + now.minute
    if current >= open_minutes:
        return 0
    if current < 9 * 60:
        return open_minutes - 9 * 60
    return max(0, open_minutes - current)


def _gap_size_label(gap_pct: float, symbol: str) -> str:
    t = _GAP_THRESHOLDS.get(symbol, _GAP_THRESHOLDS["NIFTY"])
    abs_gap = abs(gap_pct)
    if abs_gap < t["flat"]:
        return "FLAT"
    if abs_gap < t["small"]:
        return "SMALL"
    if abs_gap < t["moderate"]:
        return "MODERATE"
    if abs_gap < t["large"]:
        return "LARGE"
    return "EXTREME"


def _parse_index_quote(quote: dict[str, Any]) -> dict[str, float]:
    ltp = float(quote.get("last_price") or quote.get("ltp") or 0)
    ohlc = quote.get("ohlc") or {}
    prev_close = float(ohlc.get("close") or 0)
    high = float(ohlc.get("high") or ltp)
    low = float(ohlc.get("low") or ltp)
    volume = float(quote.get("volume") or 0)
    return {
        "ltp": ltp,
        "prevClose": prev_close,
        "high": high,
        "low": low,
        "volume": volume,
    }


def _volume_surge_score(constituent_hm: Optional[ConstituentHeatmap]) -> float:
    if not constituent_hm or not constituent_hm.dataAvailable or not constituent_hm.tiles:
        return 0.0
    weighted_vol = sum(t.volume * t.weight for t in constituent_hm.tiles if t.volume > 0)
    active = sum(1 for t in constituent_hm.tiles if t.volume > 0)
    if active == 0:
        return 0.0
    avg_vol = weighted_vol / max(active, 1)
    # Heavyweights moving volume in pre-open → higher score (0–100)
    top_vol = sorted(constituent_hm.tiles, key=lambda t: t.volume * t.weight, reverse=True)[:5]
    top_weighted = sum(t.volume * t.weight for t in top_vol)
    if weighted_vol <= 0:
        return 0.0
    concentration = min(100.0, (top_weighted / weighted_vol) * 80)
    activity = min(100.0, active / len(constituent_hm.tiles) * 100)
    return round((concentration * 0.6 + activity * 0.4), 1)


def _derive_open_play(
    gap_direction: str,
    gap_size: str,
    auction_bias: str,
    breadth_pct: float,
    volume_surge: float,
) -> tuple[str, list[str], str]:
    scenarios: list[str] = []
    explosion = "LOW"

    if gap_size in ("LARGE", "EXTREME"):
        explosion = "HIGH"
        scenarios.append("Large gap — expect violent first 5–15 min and premium explosions on ATM options.")
    elif gap_size == "MODERATE" and volume_surge >= 50:
        explosion = "MEDIUM"
        scenarios.append("Moderate gap with active pre-open volume — watch for opening drive scalps.")

    if gap_direction == "GAP_UP":
        if gap_size in ("LARGE", "EXTREME") and breadth_pct < 50:
            play = "GAP_FILL_WATCH"
            scenarios.append("Gap up but weak stock breadth — fade / put scalps if index stalls at open.")
        elif auction_bias == "BULLISH" and breadth_pct >= 55:
            play = "GAP_AND_GO"
            scenarios.append("Aligned gap-up breadth — call scalps on opening drive above pre-open high.")
        elif gap_size == "FLAT":
            play = "RANGE_BREAKOUT"
            scenarios.append("Flat open — wait for OR break with volume confirmation.")
        else:
            play = "MIXED_OPEN"
            scenarios.append("Gap up with mixed internals — reduce size until direction confirms.")
    elif gap_direction == "GAP_DOWN":
        if gap_size in ("LARGE", "EXTREME") and breadth_pct > 50:
            play = "GAP_FILL_WATCH"
            scenarios.append("Gap down but stocks holding up — bounce scalps possible at open.")
        elif auction_bias == "BEARISH" and breadth_pct <= 45:
            play = "GAP_AND_GO"
            scenarios.append("Aligned gap-down breadth — put scalps on breakdown below pre-open low.")
        else:
            play = "MIXED_OPEN"
            scenarios.append("Gap down with mixed signals — wait for first 3-min structure.")
    else:
        if volume_surge >= 60:
            play = "VOLUME_BREAKOUT"
            if explosion == "LOW":
                explosion = "MEDIUM"
            scenarios.append("Flat gap but heavy pre-open volume — breakout either side likely at 9:15.")
        else:
            play = "WAIT"
            scenarios.append("Quiet pre-open — let opening range form before scalping.")

    if volume_surge >= 70 and gap_size != "FLAT":
        explosion = "HIGH"
        scenarios.append("High pre-open volume concentration — rapid premium moves likely in first minutes.")

    return play, scenarios, explosion


def _auction_bias(gap_direction: str, breadth_pct: float, news_sentiment: str) -> str:
    score = 0
    if gap_direction == "GAP_UP":
        score += 2
    elif gap_direction == "GAP_DOWN":
        score -= 2
    if breadth_pct >= 58:
        score += 2
    elif breadth_pct <= 42:
        score -= 2
    if news_sentiment == "BULLISH":
        score += 1
    elif news_sentiment == "BEARISH":
        score -= 1

    if score >= 2:
        return "BULLISH"
    if score <= -2:
        return "BEARISH"
    if abs(breadth_pct - 50) < 8 and gap_direction == "FLAT":
        return "NEUTRAL"
    return "MIXED"


def _gap_leaders_laggards(constituent_hm: Optional[ConstituentHeatmap]) -> tuple[list[str], list[str]]:
    if not constituent_hm or not constituent_hm.tiles:
        return [], []
    ranked = sorted(constituent_hm.tiles, key=lambda t: t.changePct * t.weight, reverse=True)
    leaders = [f"{t.symbol} {t.changePct:+.2f}%" for t in ranked[:4] if t.changePct > 0.05]
    laggards = [f"{t.symbol} {t.changePct:+.2f}%" for t in sorted(ranked, key=lambda t: t.changePct)[:4] if t.changePct < -0.05]
    return leaders, laggards


async def build_premarket_analysis(
    symbol: str,
    client: UpstoxClient,
    news_sentiment: str = "NEUTRAL",
    constituent_hm: Optional[ConstituentHeatmap] = None,
    spot_override: Optional[float] = None,
) -> PremarketAnalysis:
    """Compute gap, breadth, volume, and open-play from index quote + constituents."""
    quote = await client.get_index_quote(symbol)
    parsed = _parse_index_quote(quote)

    prev_close = parsed["prevClose"]
    indicative = spot_override if spot_override is not None else parsed["ltp"]
    if prev_close <= 0 and indicative > 0:
        prev_close = indicative

    gap_points = indicative - prev_close if prev_close else 0
    gap_pct = (gap_points / prev_close * 100) if prev_close else 0

    if gap_pct > 0.08:
        gap_direction = "GAP_UP"
    elif gap_pct < -0.08:
        gap_direction = "GAP_DOWN"
    else:
        gap_direction = "FLAT"

    gap_size = _gap_size_label(gap_pct, symbol)

    if constituent_hm is None:
        constituent_hm = await build_constituent_heatmap(symbol, client)

    breadth_pct = constituent_hm.breadthPct if constituent_hm.dataAvailable else 50.0
    volume_surge = _volume_surge_score(constituent_hm)
    auction_bias = _auction_bias(gap_direction, breadth_pct, news_sentiment)
    leaders, laggards = _gap_leaders_laggards(constituent_hm)
    open_play, scenarios, explosion = _derive_open_play(
        gap_direction, gap_size, auction_bias, breadth_pct, volume_surge,
    )

    confidence = 50.0
    if constituent_hm.dataAvailable:
        confidence += 15
    if gap_size != "FLAT":
        confidence += 10
    if volume_surge >= 40:
        confidence += 10
    if auction_bias in ("BULLISH", "BEARISH"):
        confidence += 10
    confidence = min(95.0, confidence)

    mins = _minutes_to_open()
    analysis_parts = [
        f"Premarket {symbol}: {gap_direction.replace('_', ' ')} {gap_pct:+.2f}% ({gap_size.lower()}).",
        f"Indicative {indicative:.2f} vs prev close {prev_close:.2f} ({gap_points:+.1f} pts).",
        f"Constituent gap breadth {breadth_pct:.0f}% ({constituent_hm.bias if constituent_hm.dataAvailable else 'N/A'}).",
        f"Auction bias {auction_bias} · Open play {open_play.replace('_', ' ')} · Explosion risk {explosion}.",
    ]
    if mins > 0:
        analysis_parts.append(f"Market opens in ~{mins} min — pre-open auction 9:00–9:15 IST.")
    else:
        analysis_parts.append("Live session — use gap levels as opening reference.")

    return PremarketAnalysis(
        prevClose=round(prev_close, 2),
        indicativeOpen=round(indicative, 2),
        gapPoints=round(gap_points, 2),
        gapPct=round(gap_pct, 3),
        gapDirection=gap_direction,
        gapSize=gap_size,
        preOpenHigh=round(parsed["high"], 2),
        preOpenLow=round(parsed["low"], 2),
        preOpenVolume=round(parsed["volume"], 0),
        constituentGapBreadth=round(breadth_pct, 1),
        volumeSurgeScore=volume_surge,
        auctionBias=auction_bias,
        openPlay=open_play,
        explosionRisk=explosion,
        confidence=round(confidence, 1),
        minutesToOpen=mins,
        gapLeaders=leaders,
        gapLaggards=laggards,
        scenarios=scenarios,
        analysis=" ".join(analysis_parts),
    )


async def build_premarket_snapshot(
    symbol: str,
    client: UpstoxClient,
    news_sentiment: str = "NEUTRAL",
) -> SymbolSnapshot:
    """Lightweight snapshot during 9:00–9:15 IST pre-open — no option chain."""
    now = datetime.now(IST)
    phase = MarketPhase.PREMARKET

    constituent_hm = await build_constituent_heatmap(symbol, client)
    premarket = await build_premarket_analysis(
        symbol, client, news_sentiment, constituent_hm=constituent_hm,
    )
    stock_breadth = breadth_from_constituents(constituent_hm)
    session_profile = get_session_targets()

    spot = premarket.indicativeOpen
    atm = round(spot / 100) * 100 if symbol != "SENSEX" else round(spot / 100) * 100

    return SymbolSnapshot(
        symbol=symbol,
        timestamp=now,
        marketPhase=phase,
        dataAvailable=True,
        tradeQualityScore=min(85.0, 55 + premarket.confidence * 0.3),
        regime=Regime.VOLATILITY_SPIKE if premarket.gapSize in ("LARGE", "EXTREME") else Regime.RANGE_BOUND,
        spot=spot,
        atmStrike=atm,
        breadth=Breadth(
            score=stock_breadth.score,
            bias=stock_breadth.bias,
            aligned=premarket.auctionBias in ("BULLISH", "BEARISH"),
        ),
        optimizedProfile=session_profile,
        constituentHeatmap=constituent_hm if constituent_hm.dataAvailable else None,
        premarket=premarket,
        marketProfile=MarketProfile(
            poc=spot,
            vah=premarket.preOpenHigh,
            val=premarket.preOpenLow,
            openingRangeHigh=premarket.preOpenHigh,
            openingRangeLow=premarket.preOpenLow,
        ),
    )


def is_open_drive_window() -> bool:
    """First 45 minutes after open — still show premarket context."""
    now = datetime.now(IST)
    t = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= t < 10 * 60


async def attach_premarket_to_snapshot(
    snap: SymbolSnapshot,
    client: UpstoxClient,
    news_sentiment: str = "NEUTRAL",
) -> None:
    """Enrich live snapshot with gap analysis during premarket or early open."""
    phase = get_market_phase()
    if phase not in ("PREMARKET", "LIVE_MARKET"):
        return
    if phase == "LIVE_MARKET" and not is_open_drive_window():
        return
    try:
        hm = snap.constituentHeatmap
        if hm is None or not hm.dataAvailable:
            hm = await build_constituent_heatmap(snap.symbol, client)
            snap.constituentHeatmap = hm if hm.dataAvailable else snap.constituentHeatmap
        snap.premarket = await build_premarket_analysis(
            snap.symbol,
            client,
            news_sentiment,
            constituent_hm=hm,
            spot_override=snap.spot,
        )
    except (UpstoxError, Exception) as e:
        logger.warning("Premarket attach failed for %s: %s", snap.symbol, e)
