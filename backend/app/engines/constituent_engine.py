"""Constituent market heatmap — weight-sized tiles, breadth, real Upstox quotes."""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.data.index_constituents import INDEX_LABELS, get_constituents, instrument_key
from app.models.schemas import Breadth, ConstituentHeatmap, ConstituentTile
from app.services.upstox import UpstoxClient, UpstoxError, resolve_quote_payload

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_cache: dict[str, tuple[datetime, ConstituentHeatmap]] = {}
CACHE_SECONDS = 90


def _parse_quote(quote: dict[str, Any], prev_close: float) -> dict[str, float]:
    ltp = float(quote.get("last_price") or quote.get("ltp") or 0)
    ohlc = quote.get("ohlc") or {}
    close = float(ohlc.get("close") or prev_close or ltp or 0)
    open_ = float(ohlc.get("open") or close)
    high = float(ohlc.get("high") or ltp)
    low = float(ohlc.get("low") or ltp)
    vwap = float(quote.get("average_price") or quote.get("vwap") or ltp)
    volume = float(quote.get("volume") or 0)
    if close > 0 and ltp > 0:
        change_pct = ((ltp - close) / close) * 100
    else:
        change_pct = 0.0
    return {
        "ltp": ltp,
        "open": open_,
        "high": high,
        "low": low,
        "vwap": vwap,
        "volume": volume,
        "changePct": round(change_pct, 2),
        "prevClose": close,
    }


def _compute_breadth(tiles: list[ConstituentTile]) -> tuple[float, str, int, int, int]:
    advancing = sum(1 for t in tiles if t.changePct > 0.05)
    declining = sum(1 for t in tiles if t.changePct < -0.05)
    unchanged = len(tiles) - advancing - declining

    adv_weight = sum(t.weight for t in tiles if t.changePct > 0.05)
    dec_weight = sum(t.weight for t in tiles if t.changePct < -0.05)
    total_weight = sum(t.weight for t in tiles) or 1.0

    breadth_pct = round((adv_weight / total_weight) * 100, 1)

    if breadth_pct >= 58:
        bias = "BULLISH"
    elif breadth_pct <= 42:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return breadth_pct, bias, advancing, declining, unchanged


def _analysis_text(
    symbol: str,
    breadth_pct: float,
    bias: str,
    advancing: int,
    declining: int,
    tiles: list[ConstituentTile],
) -> str:
    label = INDEX_LABELS.get(symbol, symbol)
    top = sorted(tiles, key=lambda t: abs(t.changePct) * t.weight, reverse=True)[:3]
    leaders = ", ".join(f"{t.symbol} {t.changePct:+.1f}%" for t in top if t.changePct > 0)
    laggards = ", ".join(
        f"{t.symbol} {t.changePct:+.1f}%"
        for t in sorted(tiles, key=lambda t: t.changePct)[:2]
        if t.changePct < 0
    )
    parts = [
        f"{label}: {advancing} advancing / {declining} declining — weighted breadth {breadth_pct}% ({bias.lower()}).",
    ]
    if leaders:
        parts.append(f"Leaders: {leaders}.")
    if laggards:
        parts.append(f"Laggards: {laggards}.")
    if breadth_pct >= 65:
        parts.append("Index tailwind supports call-side scalps and bullish swings.")
    elif breadth_pct <= 35:
        parts.append("Broad weakness — favor puts or wait for reversal confirmation.")
    else:
        parts.append("Mixed breadth — align option trades with explosion signals, not index drift alone.")
    return " ".join(parts)


async def build_constituent_heatmap(
    symbol: str,
    client: Optional[UpstoxClient] = None,
    force_refresh: bool = False,
) -> ConstituentHeatmap:
    """Fetch real constituent quotes and build heatmap analysis."""
    symbol = symbol.upper()
    now = datetime.now(IST)

    if not force_refresh and symbol in _cache:
        cached_at, cached = _cache[symbol]
        if (now - cached_at).total_seconds() < CACHE_SECONDS:
            return cached

    constituents = get_constituents(symbol)
    label = INDEX_LABELS.get(symbol, symbol)

    if not constituents:
        return ConstituentHeatmap(
            symbol=symbol,
            indexLabel=label,
            dataAvailable=False,
            error=f"No constituent map for {symbol}",
        )

    if not client:
        client = UpstoxClient()

    keys = [instrument_key(c) for c in constituents]
    tiles: list[ConstituentTile] = []

    try:
        quotes = await client.get_full_quotes(keys)
        for c in constituents:
            key = instrument_key(c)
            q = resolve_quote_payload(quotes, key)
            if not q:
                continue
            parsed = _parse_quote(q, 0)
            if parsed["ltp"] <= 0:
                continue
            tiles.append(
                ConstituentTile(
                    symbol=c["symbol"],
                    name=c["name"],
                    weight=c["weight"],
                    ltp=parsed["ltp"],
                    changePct=parsed["changePct"],
                    open=parsed["open"],
                    high=parsed["high"],
                    low=parsed["low"],
                    vwap=parsed["vwap"],
                    volume=parsed["volume"],
                )
            )
    except UpstoxError as e:
        logger.warning("Constituent quotes failed for %s: %s", symbol, e)
        return ConstituentHeatmap(
            symbol=symbol,
            indexLabel=label,
            dataAvailable=False,
            error=str(e),
        )

    if not tiles:
        return ConstituentHeatmap(
            symbol=symbol,
            indexLabel=label,
            stockCount=len(constituents),
            dataAvailable=False,
            error="No constituent quotes returned — check Upstox token",
        )

    breadth_pct, bias, advancing, declining, unchanged = _compute_breadth(tiles)
    analysis = _analysis_text(symbol, breadth_pct, bias, advancing, declining, tiles)
    tiles.sort(key=lambda t: t.weight, reverse=True)

    result = ConstituentHeatmap(
        symbol=symbol,
        indexLabel=label,
        timestamp=now,
        dataAvailable=True,
        stockCount=len(tiles),
        advancing=advancing,
        declining=declining,
        unchanged=unchanged,
        breadthPct=breadth_pct,
        bias=bias,
        analysis=analysis,
        tiles=tiles,
    )
    _cache[symbol] = (now, result)
    return result


def breadth_from_constituents(heatmap: ConstituentHeatmap) -> Optional[Breadth]:
    if not heatmap.dataAvailable:
        return None
    return Breadth(
        score=heatmap.breadthPct,
        bias=heatmap.bias,
        aligned=heatmap.breadthPct >= 58 or heatmap.breadthPct <= 42,
    )


def blend_breadth(option_breadth: Breadth, constituent: Optional[Breadth]) -> Breadth:
    """Blend option-chain OI breadth with real stock breadth (60% constituents)."""
    if not constituent:
        return option_breadth
    score = round(constituent.score * 0.6 + option_breadth.score * 0.4, 1)
    bias = constituent.bias if constituent.aligned else option_breadth.bias
    aligned = constituent.aligned or option_breadth.aligned
    return Breadth(score=score, bias=bias, aligned=aligned)
