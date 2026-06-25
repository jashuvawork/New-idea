"""Upstox OAuth authentication — one token per IST trading day."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse

from app.config import get_settings
from app.services.redis_store import store_upstox_token
from app.services.token_manager import (
    can_generate_token_today,
    get_daily_token_status,
    is_token_valid_today,
    record_token_generated,
)
from app.services.upstox import UpstoxClient

router = APIRouter(prefix="/api/upstox", tags=["upstox"])


@router.get("/login-url")
async def login_url():
    status = await get_daily_token_status()
    client = UpstoxClient()
    return {
        "loginUrl": client.get_login_url(),
        "tokenStatus": status,
        "canLogin": status["canLogin"],
    }


@router.get("/login")
async def login_redirect():
    if await is_token_valid_today():
        status = await get_daily_token_status()
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:40px;background:#0a0e17;color:#fff'>"
            f"<h2>Upstox already connected today</h2>"
            f"<p>Token generated at: {status.get('generatedAt', 'today')}</p>"
            f"<p>One login per IST trading day — no re-auth needed.</p>"
            f"<a href='/' style='color:#06b6d4'>Back to terminal</a></body></html>"
        )
    client = UpstoxClient()
    return RedirectResponse(client.get_login_url())


@router.get("/callback")
async def oauth_callback(code: str = Query(...)):
    allowed, reason = await can_generate_token_today()
    if not allowed:
        status = await get_daily_token_status()
        return {
            "status": "already_authenticated",
            "hasToken": True,
            "message": reason,
            "tokenStatus": status,
        }

    client = UpstoxClient()
    try:
        tokens = await client.exchange_code(code)
        await store_upstox_token(tokens["access_token"], tokens.get("refresh_token", ""))
        meta = await record_token_generated(
            tokens["access_token"],
            tokens.get("refresh_token", ""),
        )
        return {
            "status": "authenticated",
            "hasToken": True,
            "tokenStatus": await get_daily_token_status(),
            "meta": meta,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status")
async def upstox_status():
    status = await get_daily_token_status()
    return status


@router.get("/token/daily")
async def daily_token_info():
    """Explicit daily token status endpoint."""
    return await get_daily_token_status()


@router.get("/setup")
async def upstox_setup():
    """Exact values to register in Upstox Developer Console."""
    settings = get_settings()
    client = UpstoxClient()
    return {
        "portal": "https://account.upstox.com/developer/apps",
        "clientId": settings.upstox_api_key,
        "redirectUri": settings.upstox_redirect_uri,
        "loginUrl": client.get_login_url(),
        "instructions": [
            "Open Upstox Developer Console → your app → Edit",
            "Copy API Key — must match clientId above exactly",
            "Set Redirect URI — must match redirectUri above exactly (no trailing slash)",
            "Save app, then login via /api/upstox/login once per IST day",
        ],
        "commonMistakes": [
            "Using api.jashuvatrade.xyz instead of www.jashuvatrade.xyz",
            "Trailing slash: .../callback/ vs .../callback",
            "http instead of https",
            "Wrong API key from a different Upstox app",
        ],
    }
