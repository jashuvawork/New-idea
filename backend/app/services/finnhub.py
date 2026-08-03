"""Finnhub news — market events, sentiment, and India macro risk."""

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_BULLISH = (
    "surge", "rally", "gain", "high", "bull", "rise", "record", "boost", "growth",
    "upgrade", "beat", "strong", "inflow", "recovery", "expansion",
)
_BEARISH = (
    "fall", "drop", "crash", "bear", "decline", "low", "fear", "sell", "cut",
    "downgrade", "miss", "weak", "outflow", "recession", "war", "hike", "inflation",
)
# Tags that move Indian index options — domestic + global risk (oil, Fed, geopolitics).
_INDIA_TAGS = (
    "india", "nifty", "sensex", "banknifty", "rbi", "sebi", "rupee", "mumbai", "nse", "bse",
    "reliance", "hdfc", "infosys", "tcs", "crude", "brent", "wti", "oil price", "opec",
    "iran", "israel", "middle east", "geopolit", "fed ", "fomc", "dollar", "treasury",
    "tariff", "china", "war", "ceasefire", "sanctions",
)


async def fetch_market_news() -> list[dict[str, Any]]:
    settings = get_settings()
    if settings.news_provider != "finnhub" or not settings.finnhub_api_key:
        return []

    items: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            token = settings.finnhub_api_key
            # Prefer general/forex for index risk; keep a small crypto sample only.
            category_limits = (("general", 15), ("forex", 10), ("crypto", 3))
            for category, limit in category_limits:
                resp = await client.get(
                    "https://finnhub.io/api/v1/news",
                    params={"category": category, "token": token},
                )
                if resp.status_code >= 400:
                    continue
                for item in (resp.json() or [])[:limit]:
                    headline = item.get("headline", "")
                    summary = item.get("summary", "")
                    sentiment = _estimate_sentiment(headline, summary)
                    items.append({
                        "headline": headline,
                        "summary": summary[:200],
                        "source": item.get("source", category),
                        "datetime": item.get("datetime"),
                        "url": item.get("url") or "",
                        "sentiment": sentiment,
                        "indiaRelevant": _is_india_relevant(headline, summary),
                        "category": category,
                    })

            # India company news sample (Reliance as market bellwether)
            for symbol in ("RELIANCE.NS", "HDFCBANK.NS", "INFY.NS"):
                resp = await client.get(
                    "https://finnhub.io/api/v1/company-news",
                    params={
                        "symbol": symbol,
                        "from": _days_ago(3),
                        "to": _days_ago(0),
                        "token": token,
                    },
                )
                if resp.status_code >= 400:
                    continue
                for item in (resp.json() or [])[:5]:
                    headline = item.get("headline", "")
                    items.append({
                        "headline": headline,
                        "summary": (item.get("summary") or "")[:200],
                        "source": item.get("source", symbol),
                        "datetime": item.get("datetime"),
                        "url": item.get("url") or "",
                        "sentiment": _estimate_sentiment(headline, item.get("summary", "")),
                        "indiaRelevant": True,
                        "category": "company",
                    })
    except Exception as e:
        logger.warning("Finnhub fetch failed: %s", e)
        return []

    # Deduplicate by headline; India/macro-relevant and newer first.
    # (Previous reverse sort on `not indiaRelevant` put relevant headlines last.)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    ranked = sorted(
        items,
        key=lambda x: (
            1 if x.get("indiaRelevant") else 0,
            0 if x.get("category") == "crypto" else 1,
            x.get("datetime") or 0,
        ),
        reverse=True,
    )
    for item in ranked:
        key = item.get("headline", "")[:80]
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:20]


def aggregate_sentiment(news: list[dict[str, Any]]) -> dict[str, Any]:
    if not news:
        return {"bias": "NEUTRAL", "score": 0, "indiaHeadlines": 0}
    scores = {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}
    total = sum(scores.get(n.get("sentiment", "NEUTRAL"), 0) for n in news[:12])
    india = sum(1 for n in news if n.get("indiaRelevant"))
    avg = total / min(12, len(news))
    bias = "BULLISH" if avg > 0.2 else "BEARISH" if avg < -0.2 else "NEUTRAL"
    return {"bias": bias, "score": round(avg * 100, 1), "indiaHeadlines": india, "count": len(news)}


def _estimate_sentiment(headline: str, summary: str = "") -> str:
    text = f"{headline} {summary}".lower()
    b_score = sum(1 for w in _BULLISH if w in text)
    s_score = sum(1 for w in _BEARISH if w in text)
    if b_score > s_score:
        return "BULLISH"
    if s_score > b_score:
        return "BEARISH"
    return "NEUTRAL"


def _is_india_relevant(headline: str, summary: str = "") -> bool:
    text = f"{headline} {summary}".lower()
    return any(tag in text for tag in _INDIA_TAGS)


def _days_ago(n: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.utcnow() - timedelta(days=n)).strftime("%Y-%m-%d")
