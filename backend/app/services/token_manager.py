"""Daily one-time Upstox token gate — one OAuth exchange per IST calendar day."""

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.services.redis_store import get_json, get_upstox_token, store_json

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

TOKEN_META_KEY = "upstox:token_meta"


def _today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


async def get_token_meta() -> dict[str, Any]:
    meta = await get_json(TOKEN_META_KEY)
    return meta or {}


async def is_token_valid_today() -> bool:
    """True if we already have a token generated for today's IST session."""
    token = await get_upstox_token()
    if not token:
        return False
    meta = await get_token_meta()
    return meta.get("sessionDate") == _today_ist()


async def can_generate_token_today() -> tuple[bool, str]:
    """Check if a new token exchange is allowed today."""
    if await is_token_valid_today():
        meta = await get_token_meta()
        return False, f"Token already generated today at {meta.get('generatedAt', 'unknown')}"
    return True, "ok"


async def record_token_generated(access_token: str, refresh_token: str = "") -> dict[str, Any]:
    """Record successful one-time daily token generation."""
    now = datetime.now(IST)
    meta = {
        "sessionDate": _today_ist(),
        "generatedAt": now.isoformat(),
        "expiresAt": f"{_today_ist()}T15:35:00+05:30",  # market close reference
        "refreshTokenStored": bool(refresh_token),
        "oneTimePerDay": True,
    }
    await store_json(TOKEN_META_KEY, meta)
    logger.info("Daily Upstox token recorded for session %s", meta["sessionDate"])
    return meta


async def get_daily_token_status() -> dict[str, Any]:
    """Status for UI — whether today's token exists and when it was set."""
    meta = await get_token_meta()
    has_token = bool(await get_upstox_token())
    today = _today_ist()
    valid_today = has_token and meta.get("sessionDate") == today

    return {
        "hasToken": has_token,
        "validToday": valid_today,
        "sessionDate": meta.get("sessionDate"),
        "today": today,
        "generatedAt": meta.get("generatedAt"),
        "oneTimePerDay": True,
        "canLogin": not valid_today,
        "message": (
            "Token active for today — no re-login needed"
            if valid_today
            else "Login required — one token per IST trading day"
        ),
    }
