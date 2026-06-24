"""Upstox OAuth authentication."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.services.redis_store import has_upstox_token, store_upstox_token
from app.services.upstox import UpstoxClient

router = APIRouter(prefix="/api/upstox", tags=["upstox"])


@router.get("/login-url")
async def login_url():
    client = UpstoxClient()
    return {"loginUrl": client.get_login_url()}


@router.get("/login")
async def login_redirect():
    client = UpstoxClient()
    return RedirectResponse(client.get_login_url())


@router.get("/callback")
async def oauth_callback(code: str = Query(...)):
    client = UpstoxClient()
    try:
        tokens = await client.exchange_code(code)
        await store_upstox_token(tokens["access_token"], tokens.get("refresh_token", ""))
        return {"status": "authenticated", "hasToken": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status")
async def upstox_status():
    return {"hasToken": await has_upstox_token()}
