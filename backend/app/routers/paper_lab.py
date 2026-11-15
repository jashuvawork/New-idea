"""Local paper lab — status and manual prod-sync (experiments vs EC2 live)."""

from fastapi import APIRouter

from app.engines.paper_lab_prod_feed import maybe_run_prod_snapshot_cycle, paper_lab_status

router = APIRouter(prefix="/api/paper-lab", tags=["paper-lab"])


@router.get("/status")
async def get_paper_lab_status():
    return await paper_lab_status()


@router.post("/sync-prod-once")
async def sync_prod_once():
    ran = await maybe_run_prod_snapshot_cycle()
    st = await paper_lab_status()
    return {"ran": ran, **st}