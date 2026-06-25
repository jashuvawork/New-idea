"""Upstox API client — real data only, no dummy prices."""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings
from app.services.redis_store import get_upstox_token

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Upstox instrument keys for indices
INDEX_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "SENSEX": "BSE_INDEX|SENSEX",
}

# Option chain segment mapping
OPTION_SEGMENTS = {
    "NIFTY": "NSE_FO",
    "BANKNIFTY": "NSE_FO",
    "SENSEX": "BSE_FO",
}


def resolve_quote_payload(data: dict[str, Any], instrument_key: str) -> dict[str, Any]:
    """Resolve quote dict — Upstox responses use ':' keys, requests use '|'."""
    if not isinstance(data, dict) or not instrument_key:
        return {}
    if instrument_key in data and data[instrument_key]:
        return data[instrument_key]
    colon_key = instrument_key.replace("|", ":")
    if colon_key in data and data[colon_key]:
        return data[colon_key]
    pipe_key = instrument_key.replace(":", "|")
    if pipe_key in data and data[pipe_key]:
        return data[pipe_key]
    tail = instrument_key.split("|")[-1].split(":")[-1]
    for k, v in data.items():
        if isinstance(v, dict) and tail in k:
            return v
    return {}


def normalize_quotes_map(data: dict[str, Any]) -> dict[str, Any]:
    """Index quotes under both pipe and colon keys for downstream lookups."""
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in data.items():
        out[k] = v
        out[k.replace(":", "|")] = v
        out[k.replace("|", ":")] = v
    return out


def normalize_option_leg(leg: dict[str, Any]) -> dict[str, Any]:
    """Flatten Upstox v2 nested call/put leg (market_data + option_greeks)."""
    if not isinstance(leg, dict):
        return {}
    if "market_data" not in leg and ("ltp" in leg or "last_price" in leg):
        return leg

    md = leg.get("market_data") or {}
    greeks_src = leg.get("option_greeks") or leg.get("greeks") or {}
    ltp = md.get("ltp") or leg.get("ltp") or leg.get("last_price")
    return {
        "instrument_key": leg.get("instrument_key"),
        "ltp": ltp,
        "last_price": ltp,
        "volume": md.get("volume") if md.get("volume") is not None else leg.get("volume", 0),
        "oi": md.get("oi") if md.get("oi") is not None else leg.get("oi", 0),
        "bid_price": md.get("bid_price") or leg.get("bid_price"),
        "ask_price": md.get("ask_price") or leg.get("ask_price"),
        "implied_volatility": greeks_src.get("iv") or leg.get("implied_volatility"),
        "greeks": {
            "delta": greeks_src.get("delta"),
            "gamma": greeks_src.get("gamma"),
            "theta": greeks_src.get("theta"),
            "vega": greeks_src.get("vega"),
            "iv": greeks_src.get("iv"),
        },
    }


def normalize_option_chain(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize each strike row for engines that expect flat call/put fields."""
    out: list[dict[str, Any]] = []
    for row in chain:
        if not isinstance(row, dict):
            continue
        normalized = dict(row)
        if row.get("call_options"):
            normalized["call_options"] = normalize_option_leg(row["call_options"])
        if row.get("put_options"):
            normalized["put_options"] = normalize_option_leg(row["put_options"])
        out.append(normalized)
    return out


class UpstoxError(Exception):
    pass


class UpstoxClient:
    BASE_URL = "https://api.upstox.com/v2"

    def __init__(self):
        self.settings = get_settings()

    async def _headers(self) -> dict[str, str]:
        token = await get_upstox_token()
        if not token:
            raise UpstoxError("No Upstox token — operator must authenticate")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}{path}",
                headers=await self._headers(),
                params=params or {},
            )
            if resp.status_code == 401:
                raise UpstoxError("Upstox token expired — re-authenticate")
            if resp.status_code >= 400:
                raise UpstoxError(f"Upstox API error {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            return data.get("data", data)

    def get_login_url(self) -> str:
        key = self.settings.upstox_api_key
        redirect = self.settings.upstox_redirect_uri
        encoded_redirect = quote(redirect, safe="")
        return (
            f"https://api.upstox.com/v2/login/authorization/dialog"
            f"?response_type=code&client_id={key}&redirect_uri={encoded_redirect}"
        )

    async def exchange_code(self, code: str) -> dict[str, str]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/login/authorization/token",
                data={
                    "code": code,
                    "client_id": self.settings.upstox_api_key,
                    "client_secret": self.settings.upstox_api_secret,
                    "redirect_uri": self.settings.upstox_redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code >= 400:
                raise UpstoxError(f"Token exchange failed: {resp.text[:200]}")
            data = resp.json()
            return {
                "access_token": data.get("access_token", ""),
                "refresh_token": data.get("refresh_token", ""),
            }

    async def get_full_quotes(self, instrument_keys: list[str]) -> dict[str, Any]:
        """Full market quotes for up to 500 instruments (batch)."""
        if not instrument_keys:
            return {}
        results: dict[str, Any] = {}
        chunk_size = 50
        for i in range(0, len(instrument_keys), chunk_size):
            chunk = instrument_keys[i : i + chunk_size]
            keys_param = ",".join(chunk)
            data = await self._get("/market-quote/quotes", params={"instrument_key": keys_param})
            if isinstance(data, dict):
                results.update(normalize_quotes_map(data))
        return results

    async def get_index_ltp(self, symbol: str) -> float:
        key = INDEX_KEYS.get(symbol)
        if not key:
            raise UpstoxError(f"Unknown symbol: {symbol}")
        data = await self._get("/market-quote/ltp", params={"instrument_key": key})
        if isinstance(data, dict):
            data = normalize_quotes_map(data)
        quote = resolve_quote_payload(data, key)
        ltp = quote.get("last_price")
        if ltp is None:
            # Fallback to full quote endpoint
            quote = await self.get_index_quote(symbol)
            ltp = quote.get("last_price")
        if ltp is None:
            raise UpstoxError(f"No LTP for {symbol}")
        return float(ltp)

    async def get_index_quote(self, symbol: str) -> dict[str, Any]:
        """Full index quote — prev close, OHLC, volume for premarket gap analysis."""
        key = INDEX_KEYS.get(symbol)
        if not key:
            raise UpstoxError(f"Unknown symbol: {symbol}")
        data = await self._get("/market-quote/quotes", params={"instrument_key": key})
        if isinstance(data, dict):
            data = normalize_quotes_map(data)
        quote = resolve_quote_payload(data, key)
        if not quote:
            raise UpstoxError(f"No quote for {symbol}")
        return quote

    async def get_option_expiries(self, symbol: str) -> list[str]:
        """Upcoming expiry dates for an index from /option/contract."""
        key = INDEX_KEYS.get(symbol)
        if not key:
            raise UpstoxError(f"Unknown symbol: {symbol}")
        data = await self._get("/option/contract", params={"instrument_key": key})
        if not isinstance(data, list):
            return []
        today = datetime.now(IST).strftime("%Y-%m-%d")
        expiries = sorted(
            {str(c.get("expiry")) for c in data if isinstance(c, dict) and c.get("expiry") and str(c["expiry"]) >= today}
        )
        return expiries

    async def get_option_chain(self, symbol: str, expiry: str) -> list[dict[str, Any]]:
        """Fetch option chain for symbol and expiry date (YYYY-MM-DD)."""
        key = INDEX_KEYS.get(symbol)
        if not key:
            raise UpstoxError(f"Unknown symbol: {symbol}")
        data = await self._get(
            "/option/chain",
            params={"instrument_key": key, "expiry_date": expiry},
        )
        if isinstance(data, list):
            return normalize_option_chain(data)
        return []

    async def get_option_chain_resolved(self, symbol: str) -> tuple[list[dict[str, Any]], str]:
        """Fetch option chain, probing upcoming expiries until data is returned."""
        expiries = await self.get_option_expiries(symbol)
        if not expiries:
            expiries = [get_nearest_expiry(symbol)]

        best_chain: list[dict[str, Any]] = []
        best_expiry = expiries[0]
        for expiry in expiries[:6]:
            chain = await self.get_option_chain(symbol, expiry)
            if not chain:
                continue
            if not best_chain or len(chain) > len(best_chain):
                best_chain = chain
                best_expiry = expiry
            if len(chain) >= 40:
                break

        return best_chain, best_expiry

    async def get_candles(
        self, symbol: str, interval: str = "1minute", count: int = 60
    ) -> list[dict[str, Any]]:
        key = INDEX_KEYS.get(symbol)
        if not key:
            raise UpstoxError(f"Unknown symbol: {symbol}")
        to_date = datetime.now(IST).strftime("%Y-%m-%d")
        from_date = (datetime.now(IST) - timedelta(days=2)).strftime("%Y-%m-%d")
        data = await self._get(
            f"/historical-candle/{key}/{interval}/{to_date}/{from_date}",
        )
        candles = data.get("candles", []) if isinstance(data, dict) else data
        return candles[-count:] if candles else []

    async def get_funds(self) -> dict[str, Any]:
        return await self._get("/user/get-funds-and-margin")

    async def get_positions(self) -> list[dict[str, Any]]:
        data = await self._get("/portfolio/short-term-positions")
        return data if isinstance(data, list) else []

    async def place_order(self, order_payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.enable_live_trading:
            raise UpstoxError("Live trading disabled — ENABLE_LIVE_TRADING=false")
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/order/place",
                headers=await self._headers(),
                json=order_payload,
            )
            if resp.status_code >= 400:
                raise UpstoxError(f"Order failed: {resp.status_code}: {resp.text[:300]}")
            body = resp.json()
            return body.get("data", body) if isinstance(body, dict) else body


def get_nearest_expiry(symbol: str) -> str:
    """Return nearest weekly expiry (Thursday for NIFTY/BANKNIFTY, Friday for SENSEX)."""
    now = datetime.now(IST)
    # NIFTY/BANKNIFTY expire Thursday (3), SENSEX Friday (4)
    target_dow = 4 if symbol == "SENSEX" else 3
    days_ahead = (target_dow - now.weekday()) % 7
    if days_ahead == 0 and now.hour >= 15:
        days_ahead = 7
    expiry = now + timedelta(days=days_ahead)
    return expiry.strftime("%Y-%m-%d")


def get_market_phase() -> str:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return "CLOSED"
    t = now.hour * 60 + now.minute
    if t < 9 * 60:
        return "CLOSED"
    if t < 9 * 60 + 15:
        return "PREMARKET"
    if t < 15 * 60 + 30:
        return "LIVE_MARKET"
    if t < 16 * 60:
        return "POST_MARKET"
    return "CLOSED"
