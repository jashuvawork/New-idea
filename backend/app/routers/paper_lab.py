"""Local paper lab — status and manual prod-sync (experiments vs EC2 live)."""

from fastapi import APIRouter

from app.engines.paper_lab_base_rip import build_index_base_rip_monitor
from app.engines.paper_lab_prod_feed import maybe_run_prod_snapshot_cycle, paper_lab_status
from app.engines.paper_lab_prod_feed import fetch_prod_multi_snapshot

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