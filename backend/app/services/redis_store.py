"""Redis token and state persistence — optional, graceful fallback."""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_redis = None
_redis_available: Optional[bool] = None

# In-memory fallback when Redis is unavailable
_memory_store: dict[str, str] = {}


async def get_redis():
    global _redis, _redis_available
    if _redis_available is False:
        return None
    if _redis is not None:
        return _redis
    try:
        import redis.asyncio as aioredis
        from app.config import get_settings

        settings = get_settings()
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis = client
        _redis_available = True
        return _redis
    except Exception as e:
        logger.warning("Redis unavailable, using in-memory fallback: %s", e)
        _redis_available = False
        return None


async def store_upstox_token(access_token: str, refresh_token: str = "") -> bool:
    r = await get_redis()
    if r:
        try:
            await r.set("upstox:access_token", access_token)
            if refresh_token:
                await r.set("upstox:refresh_token", refresh_token)
            return True
        except Exception as e:
            logger.warning("Redis store failed: %s", e)
    _memory_store["upstox:access_token"] = access_token
    if refresh_token:
        _memory_store["upstox:refresh_token"] = refresh_token
    return True


async def get_upstox_token() -> Optional[str]:
    r = await get_redis()
    if r:
        try:
            token = await r.get("upstox:access_token")
            if token:
                return token
        except Exception as e:
            logger.warning("Redis get failed: %s", e)
    return _memory_store.get("upstox:access_token")


async def has_upstox_token() -> bool:
    token = await get_upstox_token()
    return bool(token)


async def store_json(key: str, data: Any) -> bool:
    payload = json.dumps(data, default=str)
    r = await get_redis()
    if r:
        try:
            await r.set(key, payload)
            return True
        except Exception:
            pass
    _memory_store[key] = payload
    return True


async def get_json(key: str) -> Optional[Any]:
    r = await get_redis()
    if r:
        try:
            raw = await r.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    raw = _memory_store.get(key)
    if raw:
        return json.loads(raw)
    return None
