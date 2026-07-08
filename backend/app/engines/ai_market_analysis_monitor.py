"""Interval AI market analysis — full snapshot audit stored for post-mortems."""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.auto_trader import get_state
from app.engines.composer_market_monitor import build_market_context
from app.engines.snapshot_lag_analyzer import analyze_snapshot_lag, analyze_with_ai
from app.models.schemas import AutoTraderState, SymbolSnapshot
from app.services import trade_store

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_report_history: deque[dict[str, Any]] = deque(maxlen=48)
_last_report: Optional[dict[str, Any]] = None
_last_run_mono: float = 0.0
_last_error: Optional[str] = None
_cycle_count: int = 0


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _top_explosions(snapshots: dict[str, SymbolSnapshot], limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            rows.append({
                "symbol": sym,
                "side": alert.get("side"),
                "strike": alert.get("strike"),
                "tier": alert.get("tier"),
                "score": alert.get("explosionScore"),
                "dailyMovePct": alert.get("dailyMovePct") or alert.get("openPremiumMove"),
                "premium": alert.get("premium"),
                "allDayExplosion": alert.get("allDayExplosion"),
                "tradeable": alert.get("tradeable"),
            })
    rows.sort(
        key=lambda r: (
            float(r.get("dailyMovePct") or 0),
            float(r.get("score") or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def build_full_analysis_report(
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
    *,
    rules: Optional[dict[str, Any]] = None,
    ai_payload: Optional[dict[str, Any]] = None,
    source: str = "interval",
) -> dict[str, Any]:
    """Structured report combining rules, context, and optional AI narrative."""
    state = state or get_state()
    rules = rules or analyze_snapshot_lag(snapshots, state)
    context = build_market_context(snapshots, state)

    missed = [g for g in (rules.get("explosionGaps") or []) if g.get("blockers")]
    high_movers = [
        e for e in _top_explosions(snapshots)
        if float(e.get("dailyMovePct") or 0) >= 40 or str(e.get("tier")) in ("EXPLODING", "ELITE")
    ]

    return {
        "at": _now_iso(),
        "source": source,
        "lagScore": rules.get("lagScore"),
        "summary": rules.get("summary"),
        "windows": rules.get("windows"),
        "rules": rules,
        "marketContext": {
            "phase": context.get("marketPhase"),
            "symbols": list((context.get("symbols") or {}).keys()),
            "skippedCount": len(state.skipped or []),
            "openTrades": len(getattr(state, "openPaperTrades", None) or [])
            + len(getattr(state, "openLiveTrades", None) or []),
        },
        "topExplosions": _top_explosions(snapshots),
        "highMovers": high_movers,
        "blockedRadarAlerts": missed[:12],
        "aiSummary": (ai_payload or {}).get("aiSummary"),
        "aiError": (ai_payload or {}).get("aiError"),
        "aiSource": (ai_payload or {}).get("source"),
    }


async def run_analysis_cycle(
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
    *,
    force: bool = False,
    use_ai: Optional[bool] = None,
    source: str = "interval",
) -> dict[str, Any]:
    """Run full analysis; persist to disk and in-memory history."""
    global _last_report, _last_run_mono, _last_error, _cycle_count

    settings = get_settings()
    state = state or get_state()
    use_ai = settings.ai_analysis_monitor_use_ai if use_ai is None else use_ai

    rules = analyze_snapshot_lag(snapshots, state)
    ai_payload: Optional[dict[str, Any]] = None
    if use_ai and settings.cursor_api_key:
        ai_payload = await analyze_with_ai(snapshots, state)
        rules = ai_payload.get("rules") or rules

    report = build_full_analysis_report(
        snapshots,
        state,
        rules=rules,
        ai_payload=ai_payload,
        source=source,
    )

    try:
        trade_store.record_analysis_report(report)
    except Exception as exc:
        logger.warning("Failed to persist analysis report: %s", exc)
        report["persistError"] = str(exc)

    _last_report = report
    _report_history.appendleft(report)
    _last_run_mono = time.monotonic()
    _last_error = report.get("aiError") or report.get("persistError")
    _cycle_count += 1

    lag = report.get("lagScore", 0)
    blocked = len(report.get("blockedRadarAlerts") or [])
    logger.info(
        "AI analysis cycle #%d lag=%.0f blocked_radar=%d ai=%s",
        _cycle_count,
        float(lag or 0),
        blocked,
        "ok" if report.get("aiSummary") else (report.get("aiError") or "rules"),
    )
    return report


def get_latest_report() -> Optional[dict[str, Any]]:
    return _last_report


def get_report_history(limit: int = 12) -> list[dict[str, Any]]:
    return list(_report_history)[:limit]


def monitor_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.ai_analysis_monitor_enabled,
        "intervalSeconds": settings.ai_analysis_monitor_interval_seconds,
        "useAi": settings.ai_analysis_monitor_use_ai,
        "cycleCount": _cycle_count,
        "lastRunAt": (_last_report or {}).get("at"),
        "lastLagScore": (_last_report or {}).get("lagScore"),
        "lastError": _last_error,
        "hasApiKey": bool(settings.cursor_api_key),
        "inMemoryReports": len(_report_history),
    }
