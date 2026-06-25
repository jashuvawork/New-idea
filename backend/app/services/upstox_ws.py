"""Upstox Market Data Feed V3 WebSocket client."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
import uuid
from typing import Any, Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from app.config import get_settings
from app.proto import MarketDataFeed_pb2 as pb
from app.services.redis_store import get_upstox_token, has_upstox_token
from app.services.tick_store import clear as clear_ticks, collect_option_keys_from_chain, record_tick
from app.services.upstox import INDEX_KEYS, UpstoxClient, get_market_phase

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"

_ws_task: Optional[asyncio.Task] = None
_connected: bool = False
_subscribed_count: int = 0
_last_error: Optional[str] = None
_reconnect_count: int = 0
_last_message_mono: float = 0.0
_subscription_keys: set[str] = set()


def _norm_key(key: str) -> str:
    return key.replace(":", "|")


def _extract_ltp(feed: pb.Feed) -> tuple[Optional[float], int, int]:
    """Return (ltp, ltt_ms, volume) from any feed union."""
    if feed.HasField("ltpc"):
        ltpc = feed.ltpc
        return ltpc.ltp or None, int(ltpc.ltt or 0), int(ltpc.ltq or 0)
    if feed.HasField("fullFeed"):
        ff = feed.fullFeed
        if ff.HasField("marketFF") and ff.marketFF.HasField("ltpc"):
            ltpc = ff.marketFF.ltpc
            return ltpc.ltp or None, int(ltpc.ltt or 0), int(ff.marketFF.vtt or 0)
        if ff.HasField("indexFF") and ff.indexFF.HasField("ltpc"):
            ltpc = ff.indexFF.ltpc
            return ltpc.ltp or None, int(ltpc.ltt or 0), 0
    if feed.HasField("firstLevelWithGreeks") and feed.firstLevelWithGreeks.HasField("ltpc"):
        ltpc = feed.firstLevelWithGreeks.ltpc
        return ltpc.ltp or None, int(ltpc.ltt or 0), int(feed.firstLevelWithGreeks.vtt or 0)
    return None, 0, 0


def decode_feed_message(raw: bytes) -> dict[str, tuple[float, int, int]]:
    """Decode protobuf feed into instrument_key -> (ltp, ltt, volume)."""
    out: dict[str, tuple[float, int, int]] = {}
    try:
        resp = pb.FeedResponse()
        resp.ParseFromString(raw)
    except Exception as e:
        logger.debug("Protobuf decode failed: %s", e)
        return out

    for key, feed in resp.feeds.items():
        ltp, ltt, vol = _extract_ltp(feed)
        if ltp and ltp > 0:
            out[_norm_key(key)] = (ltp, ltt, vol)
    return out


async def _authorize() -> str:
    token = await get_upstox_token()
    if not token:
        raise RuntimeError("No Upstox token for WebSocket authorize")

    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if settings.upstox_api_key:
        headers["x-api-key"] = settings.upstox_api_key

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(AUTHORIZE_URL, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"WS authorize failed {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        url = (data.get("data") or {}).get("authorized_redirect_uri")
        if not url:
            raise RuntimeError("WS authorize missing redirect URI")
        return url


async def _send_subscribe(ws, instrument_keys: list[str], mode: str = "ltpc") -> None:
    if not instrument_keys:
        return
    payload = {
        "guid": str(uuid.uuid4())[:12],
        "method": "sub",
        "data": {
            "mode": mode,
            "instrumentKeys": [_norm_key(k) for k in instrument_keys],
        },
    }
    await ws.send(json.dumps(payload))


async def _send_unsubscribe(ws, instrument_keys: list[str]) -> None:
    if not instrument_keys:
        return
    payload = {
        "guid": str(uuid.uuid4())[:12],
        "method": "unsub",
        "data": {"instrumentKeys": [_norm_key(k) for k in instrument_keys]},
    }
    await ws.send(json.dumps(payload))


async def _base_subscription_keys() -> list[str]:
    """Index keys always subscribed."""
    return [_norm_key(k) for k in INDEX_KEYS.values()]


async def _refresh_option_keys() -> list[str]:
    """Pull ATM option keys from cached REST chain for WS subscription."""
    settings = get_settings()
    keys: list[str] = []
    client = UpstoxClient()
    for sym in settings.symbols:
        try:
            spot = await client.get_index_ltp(sym)
            chain, _ = await client.get_option_chain_resolved(sym)
            if not chain:
                continue
            step = 100
            atm = round(spot / step) * step
            keys.extend(
                collect_option_keys_from_chain(chain, atm, settings.explosion_scan_range)
            )
        except Exception as e:
            logger.debug("Option key refresh failed for %s: %s", sym, e)
    return keys


async def _subscription_refresh_loop(ws) -> None:
    """Periodically add new option keys as chains update."""
    global _subscription_keys, _subscribed_count
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.upstox_ws_resubscribe_seconds)
        try:
            option_keys = await _refresh_option_keys()
            base = set(await _base_subscription_keys())
            desired = base | set(option_keys)
            to_add = sorted(desired - _subscription_keys)
            if to_add:
                # Upstox allows batched sub; chunk to avoid huge payloads
                chunk = 100
                for i in range(0, len(to_add), chunk):
                    await _send_subscribe(ws, to_add[i : i + chunk])
                _subscription_keys |= set(to_add)
                _subscribed_count = len(_subscription_keys)
                logger.info("WS subscribed +%d keys (total %d)", len(to_add), _subscribed_count)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("WS subscription refresh error: %s", e)


async def _consume_loop(ws) -> None:
    global _last_message_mono
    while True:
        raw = await ws.recv()
        _last_message_mono = time.monotonic()
        if isinstance(raw, str):
            continue
        ticks = decode_feed_message(raw)
        for ik, (ltp, ltt, vol) in ticks.items():
            record_tick(ik, ltp, ltt_ms=ltt, volume=vol)


async def _run_session() -> None:
    global _connected, _last_error, _reconnect_count, _subscription_keys, _subscribed_count

    settings = get_settings()
    token = await get_upstox_token()
    if not token:
        raise RuntimeError("No Upstox token")

    ws_url = await _authorize()
    ssl_ctx = ssl.create_default_context()
    extra_headers = {"Authorization": f"Bearer {token}"}
    if settings.upstox_api_key:
        extra_headers["x-api-key"] = settings.upstox_api_key

    async with websockets.connect(
        ws_url,
        ssl=ssl_ctx,
        additional_headers=extra_headers,
        ping_interval=20,
        ping_timeout=20,
        max_size=8 * 1024 * 1024,
    ) as ws:
        _connected = True
        _last_error = None
        logger.info("Upstox WebSocket connected")

        base_keys = await _base_subscription_keys()
        option_keys = await _refresh_option_keys()
        all_keys = list(dict.fromkeys(base_keys + option_keys))
        await _send_subscribe(ws, all_keys, mode=settings.upstox_ws_mode)
        _subscription_keys = set(all_keys)
        _subscribed_count = len(_subscription_keys)
        logger.info("WS initial subscribe: %d instruments (mode=%s)", _subscribed_count, settings.upstox_ws_mode)

        refresh_task = asyncio.create_task(_subscription_refresh_loop(ws))
        try:
            await _consume_loop(ws)
        finally:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass


async def _ws_loop() -> None:
    global _connected, _last_error, _reconnect_count
    settings = get_settings()
    backoff = settings.upstox_ws_reconnect_seconds

    while True:
        if get_market_phase() == "CLOSED":
            _connected = False
            await asyncio.sleep(30)
            continue

        if not await has_upstox_token():
            _connected = False
            await asyncio.sleep(10)
            continue

        try:
            await _run_session()
        except ConnectionClosed as e:
            _last_error = f"Connection closed: {e}"
            logger.warning("Upstox WS closed: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _last_error = str(e)[:200]
            logger.warning("Upstox WS error: %s", e)
        finally:
            _connected = False

        _reconnect_count += 1
        await asyncio.sleep(backoff)


async def start_upstox_ws() -> None:
    global _ws_task
    settings = get_settings()
    if not settings.upstox_ws_enabled:
        return
    if _ws_task and not _ws_task.done():
        return
    _ws_task = asyncio.create_task(_ws_loop())
    logger.info("Upstox WebSocket feed task started")


async def stop_upstox_ws() -> None:
    global _ws_task, _connected, _subscription_keys, _subscribed_count
    if _ws_task:
        _ws_task.cancel()
        try:
            await _ws_task
        except asyncio.CancelledError:
            pass
        _ws_task = None
    _connected = False
    _subscription_keys = set()
    _subscribed_count = 0
    clear_ticks()


def ws_status() -> dict[str, Any]:
    from app.services.tick_store import status as tick_status

    age_ms = None
    if _last_message_mono:
        age_ms = int((time.monotonic() - _last_message_mono) * 1000)
    tick = tick_status()
    return {
        "enabled": get_settings().upstox_ws_enabled,
        "connected": _connected,
        "subscribedInstruments": _subscribed_count,
        "reconnectCount": _reconnect_count,
        "lastError": _last_error,
        "lastMessageAgeMs": age_ms,
        "mode": get_settings().upstox_ws_mode,
        **tick,
    }


def is_ws_active() -> bool:
    """True when WS is connected and receiving recent ticks."""
    if not _connected:
        return False
    if not _last_message_mono:
        return False
    return (time.monotonic() - _last_message_mono) < 15.0
