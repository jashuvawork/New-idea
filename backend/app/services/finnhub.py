"""Finnhub news provider for event risk."""

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def fetch_market_news() -> list[dict[str, Any]]:
    settings = get_settings()
    if settings.news_provider != "finnhub" or not settings.finnhub_api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/news",
                params={"category": "general", "token": settings.finnhub_api_key},
            )
            if resp.status_code >= 400:
                logger.warning("Finnhub news error: %s", resp.status_code)
                return []
            items = resp.json()
            return [
                {
                    "headline": item.get("headline", ""),
                    "summary": item.get("summary", ""),
                    "source": item.get("source", ""),
                    "datetime": item.get("datetime"),
                    "sentiment": _estimate_sentiment(item.get("headline", "")),
                }
                for item in (items or [])[:15]
            ]
    except Exception as e:
        logger.warning("Finnhub fetch failed: %s", e)
        return []


def _estimate_sentiment(headline: str) -> str:
    headline_lower = headline.lower()
    bullish = ["surge", "rally", "gain", "high", "bull", "rise", "record", "boost"]
    bearish = ["fall", "drop", "crash", "bear", "decline", "low", "fear", "sell"]
    b_score = sum(1 for w in bullish if w in headline_lower)
    s_score = sum(1 for w in bearish if w in headline_lower)
    if b_score > s_score:
        return "BULLISH"
    if s_score > b_score:
        return "BEARISH"
    return "NEUTRAL"
