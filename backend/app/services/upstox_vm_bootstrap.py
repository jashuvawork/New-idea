"""Cloud VM — hydrate local Upstox session for tick-faithful paper (no second OAuth on laptop)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.config import get_settings
from app.services.redis_store import has_upstox_token, store_upstox_token
from app.services.token_manager import get_daily_token_status, record_token_generated

logger = logging.getLogger(__name__)

_SYNC_HEADER = "X-Paper-Lab-VM-Sync-Key"


async def _bootstrap_from_runtime_access_token() -> dict[str, Any]:
    """Optional UPSTOX_ACCESS_TOKEN runtime secret (today's token) — never commit."""
    token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token:
        return {"ok": False, "error": "no_runtime_access_token"}
    await store_upstox_token(token, os.environ.get("UPSTOX_REFRESH_TOKEN", "").strip())
    await record_token_generated(token, "")
    status = await get_daily_token_status()
    logger.info("VM Upstox session loaded from UPSTOX_ACCESS_TOKEN (validToday=%s)", status.get("validToday"))
    return {"ok": True, "tokenStatus": status, "source": "runtime_env"}


async def maybe_bootstrap_vm_upstox() -> dict[str, Any]:
    """When VM_UPSTOX_LOCAL_ENABLED, copy today's prod access token if local store is empty."""
    settings = get_settings()
    if not bool(getattr(settings, "vm_upstox_local_enabled", False)):
        return {"bootstrapped": False, "reason": "vm_upstox_local_disabled"}
    if await has_upstox_token():
        status = await get_daily_token_status()
        return {
            "bootstrapped": False,
            "reason": "local_token_present",
            "tokenStatus": status,
        }
    from_env = await _bootstrap_from_runtime_access_token()
    if from_env.get("ok"):
        return {"bootstrapped": True, **from_env}
    synced = await sync_upstox_session_from_prod()
    if synced.get("ok"):
        return {"bootstrapped": True, "source": "prod_sync", **synced}
    return {"bootstrapped": False, "reason": synced.get("error", "sync_failed"), **synced}


async def sync_upstox_session_from_prod() -> dict[str, Any]:
    settings = get_settings()
    base = str(getattr(settings, "paper_lab_prod_api_base", "") or "").strip()
    sync_key = str(getattr(settings, "paper_lab_vm_token_sync_key", "") or "").strip()
    if not base:
        return {"ok": False, "error": "missing_paper_lab_prod_api_base"}
    if not sync_key:
        return {"ok": False, "error": "missing_paper_lab_vm_token_sync_key"}
    url = base.rstrip("/") + "/api/paper-lab/vm-upstox-session"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers={_SYNC_HEADER: sync_key})
    except Exception as exc:
        logger.warning("VM Upstox prod sync request failed: %s", exc)
        return {"ok": False, "error": "prod_unreachable", "detail": str(exc)}
    if resp.status_code == 404:
        return {
            "ok": False,
            "error": "prod_sync_not_deployed",
            "hint": "Deploy main with PAPER_LAB_VM_TOKEN_SYNC_EXPORT_ENABLED=true on EC2",
        }
    if resp.status_code == 401:
        return {"ok": False, "error": "sync_key_mismatch"}
    if resp.status_code == 503:
        try:
            body = resp.json()
        except Exception:
            body = {}
        return {"ok": False, "error": body.get("reason", "prod_token_unavailable")}
    if resp.status_code != 200:
        return {"ok": False, "error": f"prod_http_{resp.status_code}"}
    try:
        body = resp.json()
    except Exception:
        return {"ok": False, "error": "invalid_prod_response"}
    token = str(body.get("accessToken") or "").strip()
    refresh = str(body.get("refreshToken") or "").strip()
    if not token:
        return {"ok": False, "error": "empty_access_token"}
    await store_upstox_token(token, refresh)
    await record_token_generated(token, refresh)
    status = await get_daily_token_status()
    logger.info(
        "VM Upstox session synced from prod (validToday=%s)",
        status.get("validToday"),
    )
    return {"ok": True, "tokenStatus": status}