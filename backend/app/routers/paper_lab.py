"""Local paper lab — status and manual prod-sync (experiments vs EC2 live)."""

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.engines.paper_lab_base_rip import build_index_base_rip_monitor
from app.engines.paper_lab_prod_feed import (
    fetch_prod_multi_snapshot,
    maybe_run_prod_snapshot_cycle,
    paper_lab_status,
)

router = APIRouter(prefix="/api/paper-lab", tags=["paper-lab"])


@router.get("/status")
async def get_paper_lab_status():
    return await paper_lab_status()


@router.get("/base-rip-monitor")
async def base_rip_monitor():
    """Dual-index near-base rip board (paper experiment)."""
    from app.config import get_settings

    settings = get_settings()
    base = str(getattr(settings, "paper_lab_prod_api_base", "") or "").strip()
    if not base:
        return {"error": "PAPER_LAB_PROD_API_BASE not set"}
    multi = await fetch_prod_multi_snapshot(base)
    if not multi or not multi.snapshots:
        return {"dataReady": False, "board": build_index_base_rip_monitor({})}
    return {"dataReady": True, "board": build_index_base_rip_monitor(multi.snapshots)}


@router.post("/sync-prod-once")
async def sync_prod_once():
    ran = await maybe_run_prod_snapshot_cycle()
    st = await paper_lab_status()
    return {"ran": ran, **st}


@router.post("/bootstrap-upstox")
async def bootstrap_upstox_local():
    """Pull prod token (sync key) or UPSTOX_ACCESS_TOKEN runtime secret into local paper VM."""
    from app.services.upstox_vm_bootstrap import maybe_bootstrap_vm_upstox

    boot = await maybe_bootstrap_vm_upstox()
    st = await paper_lab_status()
    return {"boot": boot, **st}


@router.get("/vm-upstox-session")
async def export_vm_upstox_session(
    x_paper_lab_vm_sync_key: str = Header(default="", alias="X-Paper-Lab-VM-Sync-Key"),
):
    """
    EC2-only: copy today's Upstox access token to a trusted Cloud VM (shared sync key).
    Disabled unless PAPER_LAB_VM_TOKEN_SYNC_EXPORT_ENABLED=true on the host.
    """
    from app.services.redis_store import get_upstox_token
    from app.services.token_manager import get_daily_token_status, is_token_valid_today

    settings = get_settings()
    if not bool(getattr(settings, "paper_lab_vm_token_sync_export_enabled", False)):
        raise HTTPException(status_code=404, detail="vm_upstox_export_disabled")
    expected = str(getattr(settings, "paper_lab_vm_token_sync_key", "") or "").strip()
    provided = str(x_paper_lab_vm_sync_key or "").strip()
    if not expected or provided != expected:
        raise HTTPException(status_code=401, detail="sync_key_invalid")
    if not await is_token_valid_today():
        raise HTTPException(
            status_code=503,
            detail={"reason": "prod_token_unavailable", "tokenStatus": await get_daily_token_status()},
        )
    token = await get_upstox_token()
    if not token:
        raise HTTPException(status_code=503, detail={"reason": "no_access_token"})
    return {
        "accessToken": token,
        "refreshToken": "",
        "tokenStatus": await get_daily_token_status(),
    }