"""Daily Upstox token gate — respects Upstox 3:30 AM IST access-token expiry."""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.services.redis_store import get_json, get_upstox_token, store_json

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

TOKEN_META_KEY = "upstox:token_meta"
# Upstox access tokens always expire at the next 3:30 AM IST after generation.
UPSTOX_TOKEN_EXPIRY_HOUR = 3
UPSTOX_TOKEN_EXPIRY_MINUTE = 30


def _today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _parse_iso_ist(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except ValueError:
        return None


def compute_upstox_token_expiry(generated_at: datetime) -> datetime:
    """
    Upstox rule: access token expires at the next 3:30 AM IST boundary.
    e.g. 02:30 → same-day 03:30 · 08:00 → next-day 03:30 · 20:00 → next-day 03:30
    """
    gen = generated_at.astimezone(IST)
    cutoff_today = gen.replace(
        hour=UPSTOX_TOKEN_EXPIRY_HOUR,
        minute=UPSTOX_TOKEN_EXPIRY_MINUTE,
        second=0,
        microsecond=0,
    )
    if gen < cutoff_today:
        return cutoff_today
    next_day = gen + timedelta(days=1)
    return next_day.replace(
        hour=UPSTOX_TOKEN_EXPIRY_HOUR,
        minute=UPSTOX_TOKEN_EXPIRY_MINUTE,
        second=0,
        microsecond=0,
    )


def is_upstox_token_expired(generated_at: Optional[datetime], now: Optional[datetime] = None) -> bool:
    if not generated_at:
        return True
    now_ist = (now or datetime.now(IST)).astimezone(IST)
    return now_ist >= compute_upstox_token_expiry(generated_at)


async def get_token_meta() -> dict[str, Any]:
    meta = await get_json(TOKEN_META_KEY)
    return meta or {}


async def is_token_valid_today() -> bool:
    """True when a non-expired Upstox access token exists for the current session."""
    token = await get_upstox_token()
    if not token:
        return False
    meta = await get_token_meta()
    if meta.get("sessionDate") != _today_ist():
        return False
    generated_at = _parse_iso_ist(meta.get("generatedAt"))
    return not is_upstox_token_expired(generated_at)


async def can_generate_token_today() -> tuple[bool, str]:
    """Allow OAuth when no valid token, or after Upstox 3:30 AM expiry."""
    if await is_token_valid_today():
        meta = await get_token_meta()
        return False, f"Token already active — generated at {meta.get('generatedAt', 'unknown')}"
    meta = await get_token_meta()
    generated_at = _parse_iso_ist(meta.get("generatedAt"))
    if meta.get("sessionDate") == _today_ist() and is_upstox_token_expired(generated_at):
        return True, "Previous token expired at 3:30 AM IST — re-login allowed"
    if meta.get("sessionDate") == _today_ist() and not is_upstox_token_expired(generated_at):
        return False, f"Token already generated today at {meta.get('generatedAt', 'unknown')}"
    return True, "ok"


async def record_token_generated(access_token: str, refresh_token: str = "") -> dict[str, Any]:
    """Record successful token generation with Upstox expiry timestamp."""
    now = datetime.now(IST)
    expires_at = compute_upstox_token_expiry(now)
    meta = {
        "sessionDate": _today_ist(),
        "generatedAt": now.isoformat(),
        "expiresAt": expires_at.isoformat(),
        "refreshTokenStored": bool(refresh_token),
        "oneTimePerDay": True,
        "upstoxExpiryRule": "3:30 AM IST",
    }
    await store_json(TOKEN_META_KEY, meta)
    logger.info(
        "Upstox token recorded for %s — expires %s",
        meta["sessionDate"],
        expires_at.strftime("%Y-%m-%d %H:%M %Z"),
    )
    return meta


async def get_daily_token_status() -> dict[str, Any]:
    """Status for UI — reflects Upstox 3:30 AM IST token expiry."""
    meta = await get_token_meta()
    has_token = bool(await get_upstox_token())
    today = _today_ist()
    generated_at = _parse_iso_ist(meta.get("generatedAt"))
    expires_at = (
        _parse_iso_ist(meta.get("expiresAt"))
        or (compute_upstox_token_expiry(generated_at) if generated_at else None)
    )
    expired = has_token and is_upstox_token_expired(generated_at)
    valid_today = has_token and meta.get("sessionDate") == today and not expired

    if not has_token:
        message = "Login required — connect Upstox after 3:35 AM IST"
    elif expired:
        message = "Token expired at 3:30 AM IST — re-login required before market open"
    elif valid_today:
        exp_label = expires_at.strftime("%H:%M IST") if expires_at else "3:30 AM IST"
        message = f"Token active — valid until {exp_label}"
    else:
        message = "Login required — one token per IST trading day"

    return {
        "hasToken": has_token,
        "validToday": valid_today,
        "expired": expired,
        "sessionDate": meta.get("sessionDate"),
        "today": today,
        "generatedAt": meta.get("generatedAt"),
        "expiresAt": expires_at.isoformat() if expires_at else meta.get("expiresAt"),
        "oneTimePerDay": True,
        "canLogin": not valid_today,
        "recommendedLoginAfter": f"{today}T03:35:00+05:30",
        "message": message,
    }
