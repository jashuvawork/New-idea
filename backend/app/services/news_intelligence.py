"""Verified market-news intelligence for Indian index option decisions.

News is context, never an entry signal by itself. Only fresh, India-relevant,
non-social items from broker-curated or recognized sources affect the guarded
session bias. Unverified social posts remain visible but cannot move TQS.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.finnhub import fetch_finnhub_news
from app.services.redis_store import has_upstox_token
from app.services.upstox import INDEX_KEYS, UpstoxClient, UpstoxError

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_TRUSTED_SOURCES = {
    "reuters",
    "bloomberg",
    "cnbc",
    "cnbc tv18",
    "reserve bank of india",
    "rbi",
    "sebi",
    "nse",
    "bse",
    "economic times",
    "business standard",
    "moneycontrol",
    "mint",
}
_SOCIAL_MARKERS = ("twitter", "x.com", "tweet", "social", "telegram", "reddit")
_INDIA_TERMS = {
    "india", "indian", "nifty", "sensex", "banknifty", "bank nifty", "rbi",
    "sebi", "rupee", "nse", "bse", "mumbai", "reliance", "hdfc", "infosys",
    "tcs", "adani",
}
_GLOBAL_CUE_TERMS = {
    "fed", "fomc", "treasury", "dollar", "crude", "brent", "wti", "opec",
    "oil", "tariff", "china", "geopolit", "war", "ceasefire", "sanctions",
    "nasdaq", "s&p", "dow jones", "nikkei", "gift nifty",
}
_HIGH_IMPACT_TERMS = {
    "rbi", "fed", "fomc", "rate decision", "emergency", "war", "ceasefire",
    "tariff", "sanctions", "crash", "default", "budget", "election",
    "inflation", "cpi", "gdp", "jobs report", "crude", "oil", "opec",
}
_BULLISH_TERMS = {
    "rally", "surge", "gain", "rises", "record high", "upgrade", "beats",
    "strong growth", "inflow", "recovery", "expansion", "rate cut",
    "ceasefire", "stimulus", "eases", "cooling inflation",
}
_BEARISH_TERMS = {
    "crash", "selloff", "falls", "drop", "decline", "downgrade", "misses",
    "outflow", "recession", "rate hike", "war", "sanctions", "tariff",
    "hot inflation", "default", "weak growth",
}
_STOP_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "is", "of",
    "on", "the", "to", "with", "after", "amid", "over", "says",
}
_KEY_TO_SYMBOL = {
    "NSE_INDEX|Nifty 50": "NIFTY",
    "NSE_INDEX|Nifty Bank": "BANKNIFTY",
    "BSE_INDEX|SENSEX": "SENSEX",
}

_provider_health: dict[str, dict[str, Any]] = {
    "upstox": {"status": "not_attempted", "itemCount": 0, "error": None},
    "finnhub": {"status": "not_attempted", "itemCount": 0, "error": None},
}


def _now() -> datetime:
    return datetime.now(IST)


def _published_at(item: dict[str, Any]) -> Optional[datetime]:
    raw = item.get("datetime")
    if raw is None:
        raw = item.get("published_time")
    try:
        epoch = float(raw)
        if epoch > 10_000_000_000:
            epoch /= 1000
        return datetime.fromtimestamp(epoch, tz=IST)
    except (TypeError, ValueError, OSError):
        return None


def _contains(text: str, phrases: set[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _headline_fingerprint(headline: str) -> str:
    words = [
        word for word in re.findall(r"[a-z0-9]+", headline.lower())
        if word not in _STOP_WORDS
    ]
    return " ".join(words[:12])


def _source_verification(item: dict[str, Any]) -> tuple[str, str]:
    provider = str(item.get("provider") or "").lower()
    source = str(item.get("source") or "").lower()
    combined = f"{provider} {source}"
    if any(marker in combined for marker in _SOCIAL_MARKERS):
        return "SOCIAL", "UNVERIFIED"
    if provider == "upstox":
        return "BROKER_NEWS", "VERIFIED"
    if any(source_name in source for source_name in _TRUSTED_SOURCES):
        return "GLOBAL_NEWS", "VERIFIED"
    return "GLOBAL_NEWS", "AGGREGATED"


def _affected_symbols(item: dict[str, Any], text: str) -> list[str]:
    symbols: set[str] = set()
    for key in item.get("instrumentKeys") or []:
        normalized = str(key).replace(":", "|")
        if normalized in _KEY_TO_SYMBOL:
            symbols.add(_KEY_TO_SYMBOL[normalized])
    if "banknifty" in text or "bank nifty" in text:
        symbols.add("BANKNIFTY")
    if "sensex" in text or "bse" in text:
        symbols.add("SENSEX")
    if "nifty" in text or "nse" in text:
        symbols.add("NIFTY")
    if not symbols and (_contains(text, _INDIA_TERMS) or _contains(text, _GLOBAL_CUE_TERMS)):
        symbols.update(("NIFTY", "SENSEX"))
    return sorted(symbols)


def _themes(text: str) -> list[str]:
    themes: list[str] = []
    groups = (
        ("MONETARY_POLICY", {"rbi", "fed", "fomc", "rate hike", "rate cut"}),
        ("CRUDE_OIL", {"crude", "brent", "wti", "oil", "opec"}),
        ("GEOPOLITICS", {"war", "ceasefire", "sanctions", "geopolit"}),
        ("TRADE_POLICY", {"tariff", "trade deal"}),
        ("INFLATION_GROWTH", {"inflation", "cpi", "gdp", "recession", "jobs report"}),
        ("CURRENCY", {"rupee", "dollar", "dxy"}),
        ("CORPORATE", {"earnings", "profit", "revenue", "upgrade", "downgrade"}),
    )
    for label, terms in groups:
        if _contains(text, terms):
            themes.append(label)
    return themes or ["MARKET"]


def _direction_score(text: str, upstream_sentiment: str) -> int:
    score = sum(1 for phrase in _BULLISH_TERMS if phrase in text)
    score -= sum(1 for phrase in _BEARISH_TERMS if phrase in text)

    # India is a major crude importer: an oil spike is bearish; an oil drop is bullish.
    if _contains(text, {"crude", "brent", "wti", "oil", "opec"}):
        if _contains(text, {"surge", "rises", "rise", "jumps", "spike", "higher"}):
            score = min(score, -2)
        elif _contains(text, {"falls", "drop", "decline", "lower", "slips"}):
            score = max(score, 2)
    if "rupee" in text:
        if _contains(text, {"weakens", "falls", "record low", "depreciat"}):
            score -= 2
        elif _contains(text, {"strengthens", "gains", "appreciat"}):
            score += 2
    if score == 0:
        score = {"BULLISH": 1, "BEARISH": -1}.get(upstream_sentiment.upper(), 0)
    return max(-3, min(3, score))


def _horizon(published: Optional[datetime], now: datetime) -> str:
    if published is None:
        return "BACKGROUND"
    settings = get_settings()
    age = max(timedelta(0), now - published)
    next_limit = timedelta(hours=max(1, settings.news_next_session_max_age_hours))
    if age > next_limit:
        return "STALE"

    minute = now.hour * 60 + now.minute
    published_minute = published.hour * 60 + published.minute
    market_open, market_close = 9 * 60, 15 * 60 + 30
    same_day = published.date() == now.date()
    intraday_limit = timedelta(minutes=max(1, settings.news_intraday_max_age_minutes))

    if same_day and minute > market_close and published_minute > market_close:
        return "NEXT_SESSION"
    if same_day and minute <= market_close and age <= intraday_limit:
        return "CURRENT_SESSION"
    if same_day and published_minute >= market_open and age <= intraday_limit:
        return "BOTH"
    if published.date() == (now - timedelta(days=1)).date() and minute < market_open:
        return "CURRENT_SESSION"
    return "NEXT_SESSION"


def analyze_news_item(
    item: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Normalize one article and attach guarded India-market impact metadata."""
    current = now or _now()
    out = dict(item)
    headline = str(out.get("headline") or out.get("heading") or "").strip()
    summary = str(out.get("summary") or "").strip()
    text = f"{headline} {summary}".lower()
    published = _published_at(out)
    source_type, verification = _source_verification(out)
    affected = _affected_symbols(out, text)
    india_relevant = bool(affected or _contains(text, _INDIA_TERMS | _GLOBAL_CUE_TERMS))
    direction = _direction_score(text, str(out.get("sentiment") or "NEUTRAL"))
    sentiment = "BULLISH" if direction > 0 else "BEARISH" if direction < 0 else "NEUTRAL"
    impact = (
        "HIGH"
        if _contains(text, _HIGH_IMPACT_TERMS)
        else "MEDIUM"
        if india_relevant
        else "LOW"
    )
    horizon = _horizon(published, current)
    actionable = bool(
        india_relevant
        and verification in {"VERIFIED", "AGGREGATED", "CORROBORATED"}
        and source_type != "SOCIAL"
        and impact in {"HIGH", "MEDIUM"}
        and horizon not in {"STALE", "BACKGROUND"}
    )

    out.update({
        "headline": headline,
        "summary": summary[:400],
        "datetime": int(published.timestamp()) if published else None,
        "sentiment": sentiment,
        "indiaRelevant": india_relevant,
        "sourceType": source_type,
        "verification": verification,
        "horizon": horizon,
        "impact": impact,
        "affectedSymbols": affected,
        "sideBias": "CALL" if direction > 0 else "PUT" if direction < 0 else "NEUTRAL",
        "directionScore": direction,
        "themes": _themes(text),
        "actionable": actionable,
        "tradeUse": "CONFIRMATION_ONLY" if actionable else "DISPLAY_ONLY",
    })
    return out


def normalize_and_rank_news(
    items: list[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Analyze, deduplicate, corroborate, and rank articles."""
    current = now or _now()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in items:
        analyzed = analyze_news_item(raw, now=current)
        fingerprint = _headline_fingerprint(analyzed["headline"])
        if fingerprint:
            grouped.setdefault(fingerprint, []).append(analyzed)

    unique: list[dict[str, Any]] = []
    for variants in grouped.values():
        variants.sort(
            key=lambda x: (
                x.get("verification") == "VERIFIED",
                x.get("provider") == "upstox",
                x.get("datetime") or 0,
            ),
            reverse=True,
        )
        selected = variants[0]
        providers = sorted({str(v.get("provider") or v.get("source") or "") for v in variants})
        if len(providers) > 1 and selected.get("verification") != "VERIFIED":
            selected["verification"] = "CORROBORATED"
            selected["actionable"] = selected.get("sourceType") != "SOCIAL"
            selected["tradeUse"] = "CONFIRMATION_ONLY"
        selected["corroboratedBy"] = providers
        unique.append(selected)

    impact_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    horizon_order = {"CURRENT_SESSION": 4, "BOTH": 3, "NEXT_SESSION": 2, "BACKGROUND": 1, "STALE": 0}
    unique.sort(
        key=lambda x: (
            bool(x.get("actionable")),
            horizon_order.get(str(x.get("horizon")), 0),
            impact_order.get(str(x.get("impact")), 0),
            x.get("datetime") or 0,
        ),
        reverse=True,
    )
    return unique[:40]


def _session_aggregate(items: list[dict[str, Any]], horizons: set[str]) -> dict[str, Any]:
    eligible = [
        item for item in items
        if item.get("actionable") and item.get("horizon") in horizons
    ]
    weighted = 0.0
    total_weight = 0.0
    high_impact = 0
    for item in eligible:
        weight = 2.0 if item.get("impact") == "HIGH" else 1.0
        if item.get("verification") == "CORROBORATED":
            weight *= 1.25
        weighted += float(item.get("directionScore") or 0) * weight
        total_weight += 3.0 * weight
        high_impact += int(item.get("impact") == "HIGH")
    score = round((weighted / total_weight) * 100, 1) if total_weight else 0.0
    bias = "BULLISH" if score >= 12 else "BEARISH" if score <= -12 else "NEUTRAL"
    confidence = (
        "HIGH" if high_impact >= 2 or len(eligible) >= 4
        else "MEDIUM" if eligible
        else "LOW"
    )
    return {
        "bias": bias,
        "sideBias": "CALL" if bias == "BULLISH" else "PUT" if bias == "BEARISH" else "NEUTRAL",
        "score": score,
        "confidence": confidence,
        "headlineCount": len(eligible),
        "highImpactCount": high_impact,
    }


def aggregate_news_intelligence(
    news: list[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    current = now or _now()
    analyzed = normalize_and_rank_news(news, now=current) if any(
        "horizon" not in item for item in news
    ) else news
    current_session = _session_aggregate(analyzed, {"CURRENT_SESSION", "BOTH"})
    next_session = _session_aggregate(analyzed, {"NEXT_SESSION", "BOTH"})
    high_risk = sum(
        1 for item in analyzed
        if item.get("actionable") and item.get("impact") == "HIGH"
    )
    providers = sorted({str(item.get("provider") or "") for item in analyzed if item.get("provider")})
    return {
        # Compatibility fields consumed by TQS, premarket, and existing clients.
        "bias": current_session["bias"],
        "score": current_session["score"],
        "indiaHeadlines": sum(1 for item in analyzed if item.get("indiaRelevant")),
        "count": len(analyzed),
        # Full guarded intelligence.
        "currentSession": current_session,
        "nextSession": next_session,
        "riskLevel": "HIGH" if high_risk >= 2 else "ELEVATED" if high_risk else "NORMAL",
        "providerCoverage": providers,
        "providerHealth": {key: dict(value) for key, value in _provider_health.items()},
        "unverifiedSocialCount": sum(
            1 for item in analyzed
            if item.get("sourceType") == "SOCIAL" and item.get("verification") == "UNVERIFIED"
        ),
        "guardrail": "News confirms or blocks context; it never opens a trade by itself.",
        "generatedAt": current.isoformat(),
    }


def _flatten_upstox_news(data: dict[str, list[dict[str, Any]]], category: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for instrument_key, articles in data.items():
        for article in articles:
            if not isinstance(article, dict):
                continue
            out.append({
                "headline": article.get("heading") or "",
                "summary": article.get("summary") or "",
                "source": "Upstox News",
                "provider": "upstox",
                "datetime": (
                    float(article.get("published_time") or 0) / 1000
                    if article.get("published_time")
                    else None
                ),
                "url": article.get("article_link") or "",
                "thumbnail": article.get("thumbnail") or "",
                "category": category,
                "instrumentKeys": [instrument_key],
            })
    return out


async def _fetch_upstox_news() -> list[dict[str, Any]]:
    if not await has_upstox_token():
        _provider_health["upstox"] = {
            "status": "unauthenticated", "itemCount": 0, "error": "Upstox token unavailable",
        }
        return []
    client = UpstoxClient()
    data = await client.get_news(instrument_keys=list(INDEX_KEYS.values()))
    items = _flatten_upstox_news(data, "instrument_keys")
    if get_settings().news_upstox_positions_enabled:
        positions = await client.get_news(category="positions")
        items.extend(_flatten_upstox_news(positions, "positions"))
    return items


async def fetch_market_news() -> list[dict[str, Any]]:
    """Fetch Upstox instrument news plus global cues, then apply safe analysis."""
    settings = get_settings()
    if settings.news_provider == "none":
        return []

    jobs: list[tuple[str, Any]] = []
    if settings.news_provider in ("auto", "upstox"):
        jobs.append(("upstox", _fetch_upstox_news()))
    if settings.news_provider in ("auto", "finnhub") and settings.finnhub_api_key:
        jobs.append(("finnhub", fetch_finnhub_news()))

    raw: list[dict[str, Any]] = []
    if jobs:
        results = await asyncio.gather(*(job for _, job in jobs), return_exceptions=True)
        for (provider, _), result in zip(jobs, results):
            if isinstance(result, Exception):
                message = str(result)[:200]
                _provider_health[provider] = {"status": "error", "itemCount": 0, "error": message}
                if not isinstance(result, UpstoxError):
                    logger.warning("%s news fetch failed: %s", provider, message)
                continue
            provider_items = list(result)
            _provider_health[provider] = {
                "status": "ok", "itemCount": len(provider_items), "error": None,
                "lastFetchAt": _now().isoformat(),
            }
            raw.extend(provider_items)

    return normalize_and_rank_news(raw)
