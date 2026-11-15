"""Paper lab — run auto_trader on production snapshot JSON (local experiments vs EC2 live)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings
from app.engines.auto_trader import process
from app.models.schemas import MultiSnapshot, SymbolSnapshot
from app.services.redis_store import has_upstox_token, get_upstox_token

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_last_data_ready: Optional[bool] = None


def paper_lab_active(settings: Any | None = None) -> bool:
    settings = settings or get_settings()
    if bool(getattr(settings, "enable_live_trading", False)):
        return False
    if not bool(getattr(settings, "paper_trading", True)):
        return False
    if not bool(getattr(settings, "paper_lab_use_prod_snapshots", False)):
        return False
    base = str(getattr(settings, "paper_lab_prod_api_base", "") or "").strip()
    return bool(base)


async def fetch_prod_multi_snapshot(api_base: str) -> Optional[MultiSnapshot]:
    url = api_base.rstrip("/") + "/api/market/snapshots"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.warning("Paper lab prod snapshot fetch failed: %s", exc)
        return None
    if not payload.get("dataReady"):
        return None
    snaps_raw = payload.get("snapshots") or {}
    snapshots: dict[str, SymbolSnapshot] = {}
    for sym, raw in snaps_raw.items():
        if not isinstance(raw, dict):
            continue
        try:
            snapshots[str(sym).upper()] = SymbolSnapshot.model_validate(raw)
        except Exception:
            continue
    if not snapshots:
        return None
    ts_raw = payload.get("timestamp")
    if isinstance(ts_raw, str):
        ts = datetime.fromisoformat(ts_raw)
    elif isinstance(ts_raw, datetime):
        ts = ts_raw
    else:
        ts = datetime.now(IST)
    return MultiSnapshot(
        timestamp=ts,
        dataReady=True,
        waitingReason=payload.get("waitingReason"),
        wsTickAgeMs=payload.get("wsTickAgeMs"),
        snapshots=snapshots,
    )


async def maybe_run_prod_snapshot_cycle(*, broadcast: bool = False) -> bool:
    """One trader cycle from prod snapshots. Returns True when a cycle ran."""
    global _last_data_ready
    settings = get_settings()
    if not paper_lab_active(settings):
        return False
    # Prefer real Upstox on the laptop when configured.
    if await has_upstox_token():
        return False
    base = str(settings.paper_lab_prod_api_base).strip()
    multi = await fetch_prod_multi_snapshot(base)
    if not multi or not multi.snapshots:
        if _last_data_ready:
            logger.info("Paper lab: prod snapshots not ready (market closed or warming)")
        _last_data_ready = False
        return False
    _last_data_ready = True
    tag = str(getattr(settings, "lab_session_tag", "") or "local-paper-lab")
    await process(multi.snapshots, client=None)
    logger.debug("Paper lab cycle complete (%s, %d symbols)", tag, len(multi.snapshots))
    return True


async def paper_lab_status() -> dict[str, Any]:
    settings = get_settings()
    token = await get_upstox_token()
    return {
        "active": paper_lab_active(settings),
        "prodApiBase": (settings.paper_lab_prod_api_base or "").strip() or None,
        "useProdSnapshots": bool(settings.paper_lab_use_prod_snapshots),
        "localUpstoxToken": bool(token),
        "labSessionTag": (settings.lab_session_tag or "").strip() or None,
        "labExperimentNotes": (settings.lab_experiment_notes or "").strip() or None,
        "lastProdDataReady": _last_data_ready,
    }