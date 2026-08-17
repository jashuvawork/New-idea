"""AI/ML strategy and learning API."""

import asyncio
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.engines.ai_learning import get_ai_learning
from app.engines.composer_market_monitor import (
    get_brief_history,
    get_latest_brief,
    monitor_status,
    run_monitor_cycle,
)
from app.engines.ml_engine import get_ml_engine
from app.engines.strategy_orchestrator import ALL_STRATEGIES
from app.services.cursor_composer_client import get_composer_client

router = APIRouter(prefix="/api/ai", tags=["ai"])
IST = ZoneInfo("Asia/Kolkata")


@router.get("/strategies")
async def list_strategies():
    return {
        "count": len(ALL_STRATEGIES),
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "preferredSessions": s.preferred_sessions,
                "preferredRegimes": [r.value for r in s.preferred_regimes],
            }
            for s in ALL_STRATEGIES
        ],
    }


@router.get("/ml/status")
async def ml_status():
    ml = get_ml_engine()
    return {
        "trained": ml._trained,
        "featureImportance": ml.get_feature_importance(),
        "featureNames": ml.FEATURE_NAMES if hasattr(ml, 'FEATURE_NAMES') else [],
    }


@router.get("/learning/report")
async def learning_report():
    return get_ai_learning().get_learning_report()


@router.get("/composer/status")
async def composer_status():
    from app.engines.auto_trader import get_state
    from app.engines.expiry_day_guards import is_expiry_session
    from app.routers.market import get_multi_snapshot

    status = monitor_status()
    state = get_state()
    skipped = state.skipped or []
    status["tradingBlockers"] = [
        {
            "symbol": s.get("symbol"),
            "reason": s.get("reason"),
            "message": s.get("message"),
        }
        for s in skipped
        if s.get("symbol") == "SESSION" or s.get("reason", "").startswith(
            ("whipsaw_", "last_n_", "loss_streak", "controlled_", "daily_", "STAGE", "TRAIL", "expiry")
        )
    ]
    status["composerAdvisoryOnly"] = True
    try:
        multi = await get_multi_snapshot(force=False)
        status["isExpirySession"] = is_expiry_session(multi.snapshots) if multi else None
    except Exception:
        status["isExpirySession"] = None
    ping = await get_composer_client().ping()
    status["apiPing"] = ping
    return status


@router.get("/composer/brief")
async def composer_brief_latest():
    latest = get_latest_brief()
    if not latest:
        raise HTTPException(status_code=404, detail="No composer brief yet — wait for next monitor cycle")
    return latest


@router.get("/composer/history")
async def composer_brief_history(limit: int = 12):
    return {"briefs": get_brief_history(limit=limit)}


@router.post("/composer/refresh")
async def composer_refresh():
    """Force a new market brief (rules + Composer 2.5 when API key set)."""
    from app.routers.market import get_multi_snapshot
    from app.services.upstox import rate_limit_active, rate_limit_recovery_active

    force = not rate_limit_active() and not rate_limit_recovery_active()
    snapshots = (await get_multi_snapshot(force=force)).snapshots
    brief = await run_monitor_cycle(snapshots, force=True)
    return brief.to_dict()


@router.get("/missed-trades")
async def missed_trades_explainer():
    """Per-alert gate-by-gate explainer — why radar rips did not become trades."""
    from app.engines.auto_trader import get_state
    from app.engines.missed_trade_explainer import build_missed_trade_report
    from app.routers.market import get_multi_snapshot_fast

    multi = await get_multi_snapshot_fast()
    return build_missed_trade_report(multi.snapshots, get_state())


@router.get("/radar-archives")
async def radar_archives(limit: int = 30):
    """List compressed daily top-radar archives available for future review."""
    from app.services.radar_archive import list_archives

    return {"archives": list_archives(limit=min(max(limit, 1), 365))}


@router.get("/radar-archives/{date}")
async def download_radar_archive(date: str):
    """Download one YYYY-MM-DD top-radar ZIP archive."""
    from app.services.radar_archive import archive_path

    try:
        path = archive_path(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="Radar archive not found")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
    )


@router.get("/radar-health")
async def radar_health():
    """Detector sampling, archive, replay, funnel, and backup health."""
    from app.services.radar_health import health_status

    return health_status()


@router.get("/radar-pipeline/{date}")
async def radar_pipeline(date: str):
    """Durable startup, cache, option-subscription, and premium-sampling timeline."""
    from app.services.radar_learning import pipeline_history_summary

    try:
        return await asyncio.to_thread(pipeline_history_summary, date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/radar-scorecard/{date}")
async def radar_scorecard(date: str):
    """Daily precision/recall, lead-time, missed-winner, and outcome scorecard."""
    from app.services.radar_learning import analyze_hindsight

    try:
        return await asyncio.to_thread(analyze_hindsight, date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/radar-funnel/{date}")
async def radar_funnel(date: str):
    """Detection → gate blocker → entry → outcome funnel for one session."""
    from app.services.radar_learning import build_funnel_report

    try:
        return await asyncio.to_thread(build_funnel_report, date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/radar-replay/{date}")
async def radar_replay(
    date: str,
    flat_max_range_pct: float | None = None,
    vertical_min_move_pct: float | None = None,
    lookahead_seconds: int | None = None,
):
    """Replay archived premium tape with optional hindsight threshold overrides."""
    from app.services.radar_learning import analyze_hindsight

    if flat_max_range_pct is not None and not 0 < flat_max_range_pct <= 50:
        raise HTTPException(status_code=400, detail="flat_max_range_pct must be in (0, 50]")
    if vertical_min_move_pct is not None and not 1 <= vertical_min_move_pct <= 1000:
        raise HTTPException(status_code=400, detail="vertical_min_move_pct must be in [1, 1000]")
    if lookahead_seconds is not None and not 60 <= lookahead_seconds <= 14400:
        raise HTTPException(status_code=400, detail="lookahead_seconds must be in [60, 14400]")
    try:
        return await asyncio.to_thread(
            analyze_hindsight,
            date,
            flat_max_range_pct=flat_max_range_pct,
            vertical_min_move_pct=vertical_min_move_pct,
            lookahead_seconds=lookahead_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/radar-finalize/{date}")
async def finalize_radar_review(date: str):
    """Build scorecard/funnel artifacts and run configured durable backup."""
    from app.config import get_settings
    from app.services.radar_archive import archive_path
    from app.services.radar_learning import (
        RadarOperationBusyError,
        finalize_daily_review,
    )

    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        now = datetime.now(IST)
        if target_date > now.date():
            raise HTTPException(status_code=400, detail="Cannot finalize a future radar session")
        if target_date == now.date():
            settings = get_settings()
            finalize_at = (
                int(settings.radar_archive_finalize_hour),
                int(settings.radar_archive_finalize_minute),
            )
            if (now.hour, now.minute) < finalize_at:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Current radar session is still active; finalize after "
                        f"{finalize_at[0]:02d}:{finalize_at[1]:02d} IST"
                    ),
                )
        if not archive_path(date).exists():
            raise HTTPException(status_code=404, detail="Radar archive not found")
        return await asyncio.to_thread(finalize_daily_review, date)
    except RadarOperationBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/radar-detector-replay/{date}")
async def radar_detector_replay(date: str):
    """Replay premium tape through an isolated production-detector subprocess."""
    from app.services.radar_learning import (
        RadarOperationBusyError,
        run_detector_replay_isolated,
    )

    try:
        return await asyncio.to_thread(run_detector_replay_isolated, date)
    except RadarOperationBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/snapshot-analysis")
async def snapshot_analysis_rules():
    """Rules-based gap report: radar vs entry gates, misleading UI flags."""
    from app.engines.auto_trader import get_state
    from app.engines.snapshot_lag_analyzer import analyze_snapshot_lag
    from app.routers.market import get_multi_snapshot_fast

    multi = await get_multi_snapshot_fast()
    return analyze_snapshot_lag(multi.snapshots, get_state())


@router.post("/snapshot-analysis")
async def snapshot_analysis_ai():
    """Rules + Composer audit of where monitoring lags execution."""
    from app.engines.auto_trader import get_state
    from app.engines.snapshot_lag_analyzer import analyze_with_ai
    from app.routers.market import get_multi_snapshot
    from app.services.upstox import rate_limit_active, rate_limit_recovery_active

    force = not rate_limit_active() and not rate_limit_recovery_active()
    multi = await get_multi_snapshot(force=force)
    return await analyze_with_ai(multi.snapshots, get_state())


@router.get("/trade-reports")
async def trade_reports(limit: int = 30, days: int = 7):
    from app.services import trade_store

    return {
        "reports": trade_store.get_trade_reports_range(days=min(days, 30), limit=min(limit, 200)),
    }


@router.get("/analysis-monitor/status")
async def analysis_monitor_status():
    from app.engines.ai_market_analysis_monitor import monitor_status

    return monitor_status()


@router.get("/analysis-reports/latest")
async def analysis_reports_latest():
    from app.engines.ai_market_analysis_monitor import get_latest_report

    latest = get_latest_report()
    if not latest:
        from app.services import trade_store

        stored = trade_store.get_analysis_reports(limit=1)
        if stored:
            return stored[0]
        return {
            "waiting": True,
            "summary": "No analysis report yet — wait for next monitor cycle or POST /analysis-monitor/refresh",
            "reports": [],
        }
    return latest


@router.get("/analysis-reports")
async def analysis_reports(limit: int = 30, days: int = 7):
    from app.services import trade_store

    return {
        "reports": trade_store.get_analysis_reports_range(days=min(days, 30), limit=min(limit, 200)),
    }


@router.post("/analysis-monitor/refresh")
async def analysis_monitor_refresh():
    """Force a full market analysis cycle (rules + Composer when API key set)."""
    from app.engines.ai_market_analysis_monitor import run_analysis_cycle
    from app.routers.market import get_multi_snapshot
    from app.services.upstox import rate_limit_active, rate_limit_recovery_active

    force = not rate_limit_active() and not rate_limit_recovery_active()
    multi = await get_multi_snapshot(force=force)
    return await run_analysis_cycle(multi.snapshots, source="manual")
