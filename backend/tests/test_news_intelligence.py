"""News intelligence source, horizon, and trading-safety regressions."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from app.services.news_intelligence import (
    aggregate_news_intelligence,
    analyze_news_item,
    normalize_and_rank_news,
)
from app.services.upstox import UpstoxClient

IST = ZoneInfo("Asia/Kolkata")


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def test_oil_spike_is_bearish_for_india_despite_bullish_price_language():
    now = datetime(2026, 8, 17, 10, 30, tzinfo=IST)
    item = analyze_news_item({
        "headline": "Brent crude oil surges as supply disruption deepens",
        "summary": "Oil rises to a record high after fresh sanctions",
        "provider": "upstox",
        "source": "Upstox News",
        "datetime": _epoch(datetime(2026, 8, 17, 10, 0, tzinfo=IST)),
        "instrumentKeys": ["NSE_INDEX|Nifty 50"],
    }, now=now)

    assert item["sentiment"] == "BEARISH"
    assert item["sideBias"] == "PUT"
    assert item["impact"] == "HIGH"
    assert item["horizon"] == "CURRENT_SESSION"
    assert item["actionable"] is True


def test_unverified_tweet_never_changes_trade_bias():
    now = datetime(2026, 8, 17, 11, 0, tzinfo=IST)
    items = normalize_and_rank_news([{
        "headline": "Tweet claims RBI will announce an emergency rate cut",
        "summary": "Unconfirmed social post",
        "provider": "x",
        "source": "Twitter",
        "datetime": _epoch(datetime(2026, 8, 17, 10, 58, tzinfo=IST)),
    }], now=now)

    assert items[0]["sourceType"] == "SOCIAL"
    assert items[0]["verification"] == "UNVERIFIED"
    assert items[0]["actionable"] is False
    aggregate = aggregate_news_intelligence(items, now=now)
    assert aggregate["currentSession"]["bias"] == "NEUTRAL"
    assert aggregate["currentSession"]["headlineCount"] == 0
    assert aggregate["unverifiedSocialCount"] == 1


def test_after_close_news_is_reserved_for_next_session():
    now = datetime(2026, 8, 17, 18, 0, tzinfo=IST)
    item = analyze_news_item({
        "headline": "India inflation cools as growth recovery strengthens",
        "provider": "upstox",
        "source": "Upstox News",
        "datetime": _epoch(datetime(2026, 8, 17, 17, 0, tzinfo=IST)),
        "instrumentKeys": ["BSE_INDEX|SENSEX"],
    }, now=now)
    aggregate = aggregate_news_intelligence([item], now=now)

    assert item["horizon"] == "NEXT_SESSION"
    assert aggregate["currentSession"]["headlineCount"] == 0
    assert aggregate["nextSession"]["sideBias"] == "CALL"
    assert aggregate["nextSession"]["headlineCount"] == 1


def test_duplicate_headline_is_deduplicated_and_corroborated():
    now = datetime(2026, 8, 17, 10, 30, tzinfo=IST)
    published = _epoch(datetime(2026, 8, 17, 10, 0, tzinfo=IST))
    items = normalize_and_rank_news([
        {
            "headline": "Fed rate cut lifts global markets and Nifty outlook",
            "provider": "finnhub",
            "source": "Publisher One",
            "datetime": published,
        },
        {
            "headline": "Fed rate cut lifts global markets and Nifty outlook",
            "provider": "wire-two",
            "source": "Publisher Two",
            "datetime": published,
        },
    ], now=now)

    assert len(items) == 1
    assert items[0]["verification"] == "CORROBORATED"
    assert items[0]["actionable"] is True
    assert len(items[0]["corroboratedBy"]) == 2


def test_upstox_news_client_sends_supported_v2_parameters(monkeypatch):
    client = UpstoxClient()
    get = AsyncMock(return_value={"NSE_INDEX|Nifty 50": [{"heading": "Headline"}]})
    monkeypatch.setattr(client, "_get", get)

    result = asyncio.run(
        client.get_news(
            instrument_keys=["NSE_INDEX|Nifty 50", "BSE_INDEX|SENSEX"],
            page_number=0,
            page_size=500,
        )
    )

    assert "NSE_INDEX|Nifty 50" in result
    get.assert_awaited_once_with(
        "/news",
        params={
            "category": "instrument_keys",
            "page_number": 1,
            "page_size": 100,
            "instrument_keys": "NSE_INDEX|Nifty 50,BSE_INDEX|SENSEX",
        },
    )
