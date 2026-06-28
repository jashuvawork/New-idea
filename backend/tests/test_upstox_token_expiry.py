"""Upstox 3:30 AM IST token expiry rules."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.token_manager import (
    compute_upstox_token_expiry,
    is_upstox_token_expired,
    is_token_valid_today,
    can_generate_token_today,
)

IST = ZoneInfo("Asia/Kolkata")


def test_token_before_330_expires_same_morning():
    gen = datetime(2026, 6, 29, 3, 27, tzinfo=IST)
    exp = compute_upstox_token_expiry(gen)
    assert exp == datetime(2026, 6, 29, 3, 30, tzinfo=IST)
    assert is_upstox_token_expired(gen, now=datetime(2026, 6, 29, 3, 31, tzinfo=IST))


def test_token_after_330_expires_next_morning():
    gen = datetime(2026, 6, 29, 8, 0, tzinfo=IST)
    exp = compute_upstox_token_expiry(gen)
    assert exp == datetime(2026, 6, 30, 3, 30, tzinfo=IST)
    assert not is_upstox_token_expired(gen, now=datetime(2026, 6, 29, 15, 0, tzinfo=IST))


def test_token_evening_expires_next_330():
    gen = datetime(2026, 6, 28, 20, 0, tzinfo=IST)
    exp = compute_upstox_token_expiry(gen)
    assert exp == datetime(2026, 6, 29, 3, 30, tzinfo=IST)


"""Upstox 3:30 AM IST token expiry rules."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.token_manager import (
    compute_upstox_token_expiry,
    is_upstox_token_expired,
    is_token_valid_today,
    can_generate_token_today,
)

IST = ZoneInfo("Asia/Kolkata")


def test_token_before_330_expires_same_morning():
    gen = datetime(2026, 6, 29, 3, 27, tzinfo=IST)
    exp = compute_upstox_token_expiry(gen)
    assert exp == datetime(2026, 6, 29, 3, 30, tzinfo=IST)
    assert is_upstox_token_expired(gen, now=datetime(2026, 6, 29, 3, 31, tzinfo=IST))


def test_token_after_330_expires_next_morning():
    gen = datetime(2026, 6, 29, 8, 0, tzinfo=IST)
    exp = compute_upstox_token_expiry(gen)
    assert exp == datetime(2026, 6, 30, 3, 30, tzinfo=IST)
    assert not is_upstox_token_expired(gen, now=datetime(2026, 6, 29, 15, 0, tzinfo=IST))


def test_token_evening_expires_next_330():
    gen = datetime(2026, 6, 28, 20, 0, tzinfo=IST)
    exp = compute_upstox_token_expiry(gen)
    assert exp == datetime(2026, 6, 29, 3, 30, tzinfo=IST)


def test_can_relogin_after_330_expiry(monkeypatch):
    from app.services import token_manager

    async def fake_meta():
        return {
            "sessionDate": "2026-06-29",
            "generatedAt": "2026-06-29T03:27:07+05:30",
        }

    async def fake_token():
        return "stale-token"

    monkeypatch.setattr(token_manager, "get_token_meta", fake_meta)
    monkeypatch.setattr(token_manager, "get_upstox_token", fake_token)
    monkeypatch.setattr(token_manager, "_today_ist", lambda: "2026-06-29")

    assert not asyncio.run(is_token_valid_today())
    allowed, reason = asyncio.run(can_generate_token_today())
    assert allowed
    assert "3:30 AM" in reason
