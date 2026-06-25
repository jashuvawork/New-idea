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

    async def get_index_ltp(self, symbol: str) -> float:
        key = INDEX_KEYS.get(symbol)
        if not key:
            raise UpstoxError(f"Unknown symbol: {symbol}")
        data = await self._get("/market-quote/ltp", params={"instrument_key": key})
        quote = data.get(key, {})
        ltp = quote.get("last_price")
        if ltp is None:
            raise UpstoxError(f"No LTP for {symbol}")
        return float(ltp)

    async def get_option_chain(self, symbol: str, expiry: str) -> list[dict[str, Any]]:
        """Fetch option chain for symbol and expiry date (YYYY-MM-DD)."""
        segment = OPTION_SEGMENTS.get(symbol, "NSE_FO")
        instrument = f"{segment}|{symbol}"
        data = await self._get(
            "/option/chain",
            params={"instrument_key": instrument, "expiry_date": expiry},
        )
        if isinstance(data, list):
            return data
        return data if isinstance(data, list) else []

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
                raise UpstoxError(f"Order failed: {resp.text[:200]}")
            return resp.json()


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
