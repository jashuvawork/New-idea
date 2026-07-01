"""Upstox API client — real data only, no dummy prices."""

import asyncio
import logging
import time
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

# Global throttle + response cache (shared across UpstoxClient instances)
_throttle_lock = asyncio.Lock()
_last_request_mono: float = 0.0
_rate_limit_until_mono: float = 0.0
_rate_limit_recovery_until_mono: float = 0.0
_response_cache: dict[str, tuple[float, Any]] = {}
_resolved_expiry: dict[str, str] = {}


def _cache_get(key: str, ttl: float) -> Any | None:
    entry = _response_cache.get(key)
    if not entry:
        return None
    cached_at, value = entry
    if time.monotonic() - cached_at > ttl:
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    _response_cache[key] = (time.monotonic(), value)


def rate_limit_recovery_active() -> bool:
    """True briefly after cooldown clears — use gentler REST pacing."""
    return time.monotonic() < _rate_limit_recovery_until_mono


async def _throttle() -> None:
    """Serialize requests and enforce minimum spacing to avoid UDAPI10005 429s."""
    global _last_request_mono, _rate_limit_until_mono
    settings = get_settings()
    now = time.monotonic()
    if now < _rate_limit_until_mono:
        wait = _rate_limit_until_mono - now
        raise UpstoxError(f"Upstox cooling down — retry in {wait:.0f}s")

    min_ms = settings.upstox_min_request_interval_ms
    if rate_limit_recovery_active():
        min_ms = max(min_ms, min_ms * 2)
    min_interval = max(0.05, min_ms / 1000.0)
    async with _throttle_lock:
        now = time.monotonic()
        if now < _rate_limit_until_mono:
            wait = _rate_limit_until_mono - now
            raise UpstoxError(f"Upstox cooling down — retry in {wait:.0f}s")
        wait = min_interval - (now - _last_request_mono)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_mono = time.monotonic()


def _trip_rate_limit_cooldown() -> None:
    global _rate_limit_until_mono
    settings = get_settings()
    until = time.monotonic() + settings.upstox_rate_limit_cooldown_seconds
    if until > _rate_limit_until_mono:
        _rate_limit_until_mono = until
        logger.warning(
            "Upstox rate limit cooldown for %ds",
            settings.upstox_rate_limit_cooldown_seconds,
        )


def rate_limit_cooldown_remaining() -> float:
    """Seconds until Upstox REST calls are allowed again."""
    return max(0.0, _rate_limit_until_mono - time.monotonic())


def rate_limit_active() -> bool:
    return rate_limit_cooldown_remaining() > 0


def clear_rate_limit_cooldown() -> None:
    """Clear in-memory 429 backoff (e.g. after env/deploy fix)."""
    global _rate_limit_until_mono, _rate_limit_recovery_until_mono
    _rate_limit_until_mono = 0.0
    _rate_limit_recovery_until_mono = time.monotonic() + 90.0


def resolve_quote_payload(data: dict[str, Any], instrument_key: str) -> dict[str, Any]:
    """Resolve quote dict — Upstox keys may be NSE_EQ:SYMBOL while requests use NSE_EQ|ISIN."""
    if not isinstance(data, dict) or not instrument_key:
        return {}
    pipe_key = instrument_key.replace(":", "|")
    colon_key = instrument_key.replace("|", ":")
    for candidate in (instrument_key, pipe_key, colon_key):
        hit = data.get(candidate)
        if isinstance(hit, dict) and hit:
            return hit

    isin_tail = pipe_key.split("|")[-1]
    for v in data.values():
        if not isinstance(v, dict):
            continue
        token = str(v.get("instrument_token") or "").replace(":", "|")
        if token and (token == pipe_key or token.endswith(f"|{isin_tail}")):
            return v
    for k, v in data.items():
        if isinstance(v, dict) and isin_tail and isin_tail in k.replace(":", "|"):
            return v
    return {}


def normalize_quotes_map(data: dict[str, Any]) -> dict[str, Any]:
    """Index quotes under pipe/colon keys and instrument_token aliases."""
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in data.items():
        out[k] = v
        out[k.replace(":", "|")] = v
        out[k.replace("|", ":")] = v
        if isinstance(v, dict):
            token = v.get("instrument_token")
            if token:
                tok = str(token)
                out[tok] = v
                out[tok.replace(":", "|")] = v
                out[tok.replace("|", ":")] = v
            sym = v.get("symbol")
            if sym and ("|" in k or ":" in k):
                seg = k.split("|")[0].split(":")[0]
                if seg:
                    out[f"{seg}|{sym}"] = v
                    out[f"{seg}:{sym}"] = v
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
    V3_BASE_URL = "https://api.upstox.com/v3"

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
        settings = get_settings()
        last_error: Optional[str] = None

        for attempt in range(settings.upstox_request_retries):
            await _throttle()
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}{path}",
                    headers=await self._headers(),
                    params=params or {},
                )
            if resp.status_code == 401:
                raise UpstoxError("Upstox token expired — re-authenticate")
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                backoff = min(60, 5 * (2 ** attempt))
                if retry_after:
                    try:
                        backoff = max(backoff, float(retry_after))
                    except ValueError:
                        pass
                last_error = resp.text[:200]
                _trip_rate_limit_cooldown()
                logger.warning(
                    "Upstox 429 on %s — backing off %.1fs (attempt %d/%d)",
                    path, backoff, attempt + 1, settings.upstox_request_retries,
                )
                await asyncio.sleep(backoff)
                continue
            if resp.status_code >= 400:
                raise UpstoxError(f"Upstox API error {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            return data.get("data", data)

        raise UpstoxError(f"Upstox rate limited after retries: {last_error}")

    async def _get_v3(self, path: str, params: Optional[dict] = None) -> Any:
        """Upstox V3 API — multi-interval intraday/historical candles."""
        settings = get_settings()
        last_error: Optional[str] = None

        for attempt in range(settings.upstox_request_retries):
            await _throttle()
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.V3_BASE_URL}{path}",
                    headers=await self._headers(),
                    params=params or {},
                )
            if resp.status_code == 401:
                raise UpstoxError("Upstox token expired — re-authenticate")
            if resp.status_code == 429:
                _trip_rate_limit_cooldown()
                last_error = resp.text[:200]
                await asyncio.sleep(min(60, 5 * (2 ** attempt)))
                continue
            if resp.status_code >= 400:
                raise UpstoxError(f"Upstox V3 error {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            return data.get("data", data)

        raise UpstoxError(f"Upstox V3 rate limited after retries: {last_error}")

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
        chunk_size = 25
        for i in range(0, len(instrument_keys), chunk_size):
            chunk = instrument_keys[i : i + chunk_size]
            keys_param = ",".join(chunk)
            cache_key = f"quotes:{hash(keys_param)}"
            cached = _cache_get(cache_key, self.settings.upstox_ltp_cache_seconds)
            if cached is not None:
                results.update(cached)
                continue
            data = await self._get("/market-quote/quotes", params={"instrument_key": keys_param})
            if isinstance(data, dict) and data:
                normalized = normalize_quotes_map(data)
                _cache_set(cache_key, normalized)
                results.update(normalized)
            else:
                logger.warning("Empty Upstox quote batch (%d keys)", len(chunk))
        return results

    async def get_index_ltp(self, symbol: str) -> float:
        cache_key = f"ltp:{symbol}"
        cached = _cache_get(cache_key, self.settings.upstox_ltp_cache_seconds)
        if cached is not None:
            return float(cached)

        key = INDEX_KEYS.get(symbol)
        if not key:
            raise UpstoxError(f"Unknown symbol: {symbol}")
        data = await self._get("/market-quote/ltp", params={"instrument_key": key})
        if isinstance(data, dict):
            data = normalize_quotes_map(data)
        quote = resolve_quote_payload(data, key)
        ltp = quote.get("last_price")
        if ltp is None:
            quote = await self.get_index_quote(symbol)
            ltp = quote.get("last_price")
        if ltp is None:
            raise UpstoxError(f"No LTP for {symbol}")
        _cache_set(cache_key, ltp)
        return float(ltp)

    async def get_index_quote(self, symbol: str, *, force_refresh: bool = False) -> dict[str, Any]:
        """Full index quote — prev close, OHLC, volume for premarket gap analysis."""
        cache_key = f"quote:{symbol}"
        if not force_refresh:
            cached = _cache_get(cache_key, self.settings.upstox_ltp_cache_seconds)
            if cached is not None:
                return cached

        key = INDEX_KEYS.get(symbol)
        if not key:
            raise UpstoxError(f"Unknown symbol: {symbol}")
        data = await self._get("/market-quote/quotes", params={"instrument_key": key})
        if isinstance(data, dict):
            data = normalize_quotes_map(data)
        quote = resolve_quote_payload(data, key)
        if not quote:
            raise UpstoxError(f"No quote for {symbol}")
        _cache_set(cache_key, quote)
        return quote

    async def get_option_expiries(self, symbol: str) -> list[str]:
        """Upcoming expiry dates for an index from /option/contract."""
        cache_key = f"expiries:{symbol}"
        cached = _cache_get(cache_key, self.settings.upstox_expiries_cache_seconds)
        if cached is not None:
            return cached

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
        _cache_set(cache_key, expiries)
        return expiries

    async def get_lot_size(self, symbol: str) -> int:
        """Units per lot for an index — from Upstox option contract metadata."""
        sym = symbol.upper()
        cache_key = f"lot_size:{sym}"
        cached = _cache_get(cache_key, self.settings.upstox_expiries_cache_seconds)
        if cached is not None:
            return int(cached)

        key = INDEX_KEYS.get(sym)
        if not key:
            raise UpstoxError(f"Unknown symbol: {sym}")

        data = await self._get("/option/contract", params={"instrument_key": key})
        if not isinstance(data, list) or not data:
            raise UpstoxError(f"No option contracts for {sym}")

        for contract in data:
            if not isinstance(contract, dict):
                continue
            raw = contract.get("lot_size") or contract.get("minimum_lot")
            if raw is None:
                continue
            lot = int(raw)
            if lot > 0:
                _cache_set(cache_key, lot)
                logger.info("Upstox lot_size %s = %d", sym, lot)
                return lot

        raise UpstoxError(f"No lot_size in Upstox contracts for {sym}")

    async def get_option_chain(self, symbol: str, expiry: str) -> list[dict[str, Any]]:
        """Fetch option chain for symbol and expiry date (YYYY-MM-DD)."""
        cache_key = f"chain:{symbol}:{expiry}"
        cached = _cache_get(cache_key, self.settings.upstox_chain_cache_seconds)
        if cached is not None:
            return cached

        key = INDEX_KEYS.get(symbol)
        if not key:
            raise UpstoxError(f"Unknown symbol: {symbol}")
        data = await self._get(
            "/option/chain",
            params={"instrument_key": key, "expiry_date": expiry},
        )
        chain = normalize_option_chain(data) if isinstance(data, list) else []
        _cache_set(cache_key, chain)
        return chain

    async def get_option_chain_resolved(self, symbol: str) -> tuple[list[dict[str, Any]], str]:
        """Fetch option chain with minimal expiry probes and short TTL cache."""
        settings = self.settings
        resolved_key = f"chain_resolved:{symbol}"
        cached = _cache_get(resolved_key, settings.upstox_chain_cache_seconds)
        if cached is not None:
            return cached

        candidates: list[str] = []
        sticky = _resolved_expiry.get(symbol)
        if sticky:
            candidates.append(sticky)
        candidates.append(get_nearest_expiry(symbol))

        expiries = await self.get_option_expiries(symbol)
        for exp in expiries[: settings.upstox_max_expiry_probes]:
            if exp not in candidates:
                candidates.append(exp)

        seen: set[str] = set()
        best_chain: list[dict[str, Any]] = []
        best_expiry = candidates[0] if candidates else get_nearest_expiry(symbol)

        for expiry in candidates:
            if expiry in seen:
                continue
            seen.add(expiry)
            chain = await self.get_option_chain(symbol, expiry)
            if not chain:
                continue
            if not best_chain or len(chain) > len(best_chain):
                best_chain = chain
                best_expiry = expiry
            if len(chain) >= 40:
                break
            if len(seen) >= settings.upstox_max_expiry_probes:
                break

        result = (best_chain, best_expiry)
        if best_chain:
            _resolved_expiry[symbol] = best_expiry
            _cache_set(resolved_key, result)
        return result

    async def get_candles(
        self, symbol: str, interval: str = "1minute", count: int = 60, *, force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        key = INDEX_KEYS.get(symbol)
        if not key:
            raise UpstoxError(f"Unknown symbol: {symbol}")
        return await self.get_historical_candles(
            key, interval=interval, count=count, force_refresh=force_refresh,
        )

    async def get_historical_candles(
        self,
        instrument_key: str,
        interval: str = "1minute",
        count: int = 60,
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """OHLCV candles for any Upstox instrument (index or option leg)."""
        cache_key = f"candles:{instrument_key}:{interval}:{count}"
        if not force_refresh:
            cached = _cache_get(cache_key, self.settings.upstox_candles_cache_seconds)
            if cached is not None:
                return cached

        encoded_key = quote(instrument_key, safe="")
        to_date = datetime.now(IST).strftime("%Y-%m-%d")
        from_date = (datetime.now(IST) - timedelta(days=2)).strftime("%Y-%m-%d")
        data = await self._get(
            f"/historical-candle/{encoded_key}/{interval}/{to_date}/{from_date}",
        )
        candles = data.get("candles", []) if isinstance(data, dict) else data
        result = candles[-count:] if candles else []
        if result and not force_refresh:
            _cache_set(cache_key, result)
        return result

    async def get_intraday_candles_v3(
        self,
        instrument_key: str,
        *,
        unit: str = "minutes",
        interval: int = 1,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """V3 intraday OHLCV — supports minutes 1-300, hours 1-5."""
        cache_key = f"v3intraday:{instrument_key}:{unit}:{interval}"
        if not force_refresh:
            cached = _cache_get(cache_key, self.settings.upstox_candles_cache_seconds)
            if cached is not None:
                return cached

        encoded_key = quote(instrument_key, safe="")
        data = await self._get_v3(
            f"/historical-candle/intraday/{encoded_key}/{unit}/{interval}",
        )
        candles = data.get("candles", []) if isinstance(data, dict) else data
        result = candles if isinstance(candles, list) else []
        if result and not force_refresh:
            _cache_set(cache_key, result)
        return result

    async def get_funds(self) -> dict[str, Any]:
        cache_key = "funds"
        cached = _cache_get(cache_key, self.settings.upstox_funds_cache_seconds)
        if cached is not None:
            return cached
        data = await self._get("/user/get-funds-and-margin")
        _cache_set(cache_key, data)
        return data

    async def get_positions(self) -> list[dict[str, Any]]:
        data = await self._get("/portfolio/short-term-positions")
        return data if isinstance(data, list) else []

    async def place_order(self, order_payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.enable_live_trading:
            raise UpstoxError("Live trading disabled — ENABLE_LIVE_TRADING=false")
        await _throttle()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/order/place",
                headers=await self._headers(),
                json=order_payload,
            )
            if resp.status_code == 429:
                raise UpstoxError("Upstox rate limited — order not placed, retry next tick")
            if resp.status_code >= 400:
                raise UpstoxError(f"Order failed: {resp.status_code}: {resp.text[:300]}")
            body = resp.json()
            return body.get("data", body) if isinstance(body, dict) else body


def get_nearest_expiry(symbol: str) -> str:
    """Return nearest weekly expiry (Thursday for NIFTY/BANKNIFTY, Friday for SENSEX)."""
    now = datetime.now(IST)
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
