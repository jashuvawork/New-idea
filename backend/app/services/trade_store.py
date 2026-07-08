"""Persistent trade storage — daily JSON archives + append-only trade log for paper and live."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.models.schemas import PaperTrade

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_store_dir: Optional[Path] = None
_log_path: Optional[Path] = None


def get_store_dir() -> Path:
    global _store_dir
    if _store_dir is None:
        from app.config import get_settings

        _store_dir = Path(get_settings().trade_store_dir)
        _store_dir.mkdir(parents=True, exist_ok=True)
    return _store_dir


def get_log_path() -> Path:
    """Append-only trade log — one JSON event per line (paper + live)."""
    global _log_path
    if _log_path is None:
        from app.config import get_settings

        settings = get_settings()
        if settings.trade_log_file:
            _log_path = Path(settings.trade_log_file)
        else:
            _log_path = get_store_dir() / "trades.log"
        _log_path.parent.mkdir(parents=True, exist_ok=True)
    return _log_path


def _now() -> datetime:
    return datetime.now(IST)


def _today() -> str:
    return _now().strftime("%Y-%m-%d")


def _day_file(date: str) -> Path:
    return get_store_dir() / f"{date}.json"


def _load_day(date: str) -> dict[str, Any]:
    path = _day_file(date)
    if not path.exists():
        return {"date": date, "trades": [], "events": [], "summary": {}}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.warning("Failed to load trades for %s: %s", date, e)
        return {"date": date, "trades": [], "events": [], "summary": {}}


def _save_day(date: str, data: dict[str, Any]) -> None:
    path = _day_file(date)
    path.write_text(json.dumps(data, indent=2, default=str))


def _enum_val(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _execution_mode(context: Optional[dict]) -> str:
    if context and context.get("executionMode"):
        return str(context["executionMode"])
    return "PAPER"


def _trade_payload(trade: PaperTrade, context: Optional[dict] = None) -> dict[str, Any]:
    """Unified trade record for JSON archive and append-only log."""
    payload = {
        "id": trade.id,
        "symbol": trade.symbol,
        "side": _enum_val(trade.side),
        "strike": trade.strike,
        "entryPremium": trade.entryPremium,
        "currentPremium": trade.currentPremium,
        "lots": trade.lots,
        "pnlInr": trade.pnlInr,
        "pnlPoints": trade.pnlPoints,
        "bestPnlPoints": trade.bestPnlPoints,
        "status": trade.status,
        "exitReason": trade.exitReason,
        "strategyType": _enum_val(trade.strategyType),
        "openedAt": trade.openedAt.isoformat() if trade.openedAt else None,
        "closedAt": trade.closedAt.isoformat() if trade.closedAt else None,
        "sessionDate": trade.sessionDate or _today(),
        "executionMode": _execution_mode(context or trade.entryContext),
    }
    ctx = context or trade.entryContext or {}
    for key in (
        "instrumentKey",
        "optionExpiry",
        "brokerOrderId",
        "brokerExitOrderId",
        "brokerQuantity",
        "selectionMode",
        "selectionScore",
        "exitPlan",
        "signalPremium",
        "slippage",
    ):
        if key in ctx:
            payload[key] = ctx[key]
    return payload


def _trade_to_record(trade: PaperTrade, context: Optional[dict] = None) -> dict[str, Any]:
    record = trade.model_dump(mode="json")
    if context:
        record["context"] = context
    record["executionMode"] = _execution_mode(context or trade.entryContext)
    return record


def _append_log(event: str, payload: dict[str, Any]) -> None:
    """Write one JSON line to trades.log (durable audit trail for paper + live)."""
    entry = {
        "ts": _now().isoformat(),
        "event": event,
        **payload,
    }
    line = json.dumps(entry, default=str, separators=(",", ":"))
    try:
        with open(get_log_path(), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        logger.error("Failed to append trade log: %s", e)


def _human_log_line(event: str, trade: PaperTrade, context: Optional[dict] = None) -> str:
    mode = _execution_mode(context or trade.entryContext)
    side = _enum_val(trade.side)
    base = (
        f"{event} {mode} {trade.id} {trade.symbol} {side} {trade.strike:g} "
        f"lots={trade.lots} entry={trade.entryPremium:.2f}"
    )
    if event == "TRADE_CLOSED":
        return (
            f"{base} exit={trade.exitReason} pnl_inr={trade.pnlInr:.2f} "
            f"pnl_pts={trade.pnlPoints:.2f}"
        )
    ctx = context or {}
    broker = ctx.get("brokerOrderId")
    if broker:
        return f"{base} broker_order={broker}"
    return base


def _update_summary(data: dict[str, Any]) -> None:
    trades = data.get("trades", [])
    wins = losses = scratches = 0
    gross_profit = gross_loss = 0.0
    for t in trades:
        if t.get("status") != "CLOSED":
            continue
        pnl = t.get("pnlInr", 0)
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            losses += 1
            gross_loss += abs(pnl)
        else:
            scratches += 1
    total = wins + losses
    data["summary"] = {
        "totalTrades": len([t for t in trades if t.get("status") == "CLOSED"]),
        "wins": wins,
        "losses": losses,
        "scratches": scratches,
        "netPnlInr": round(gross_profit - gross_loss, 2),
        "profitFactor": round(gross_profit / gross_loss, 2) if gross_loss else gross_profit,
        "winRate": round(wins / total * 100, 1) if total else 0,
    }


def _hold_seconds(trade: PaperTrade) -> float:
    try:
        opened = trade.openedAt
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=IST)
        end = trade.closedAt or _now()
        if end.tzinfo is None:
            end = end.replace(tzinfo=IST)
        return (end.astimezone(IST) - opened.astimezone(IST)).total_seconds()
    except Exception:
        return 0


def record_trade_opened(trade: PaperTrade, context: Optional[dict] = None) -> None:
    """Persist trade open to daily archive and append-only log."""
    date = _today()
    data = _load_day(date)
    record = _trade_to_record(trade, context)
    record["sessionDate"] = date

    existing = {t["id"]: i for i, t in enumerate(data["trades"])}
    if trade.id in existing:
        data["trades"][existing[trade.id]] = record
    else:
        data["trades"].append(record)

    event_ctx = context or {}
    data["events"].append({
        "type": "TRADE_OPENED",
        "tradeId": trade.id,
        "timestamp": _now().isoformat(),
        "executionMode": _execution_mode(event_ctx),
        "symbol": trade.symbol,
        "side": _enum_val(trade.side),
        "strike": trade.strike,
        "premium": trade.entryPremium,
        "lots": trade.lots,
        "strategy": _enum_val(trade.strategyType),
        "context": event_ctx,
    })
    _update_summary(data)
    _save_day(date, data)

    trade_payload = _trade_payload(trade, context)
    _append_log("TRADE_OPENED", {"trade": trade_payload, "context": event_ctx})
    logger.info(_human_log_line("TRADE_OPENED", trade, context))


def record_trade_closed(trade: PaperTrade, context: Optional[dict] = None) -> None:
    """Persist trade close with full outcome to archive and log."""
    date = trade.openedAt.astimezone(IST).strftime("%Y-%m-%d") if trade.openedAt.tzinfo else _today()
    data = _load_day(date)
    record = _trade_to_record(trade, context)
    record["sessionDate"] = date
    record["closedAt"] = (trade.closedAt or _now()).isoformat()
    record["status"] = "CLOSED"

    existing = {t["id"]: i for i, t in enumerate(data["trades"])}
    if trade.id in existing:
        data["trades"][existing[trade.id]] = record
    else:
        data["trades"].append(record)

    event_ctx = context or {}
    data["events"].append({
        "type": "TRADE_CLOSED",
        "tradeId": trade.id,
        "timestamp": _now().isoformat(),
        "executionMode": _execution_mode(event_ctx),
        "exitReason": trade.exitReason,
        "pnlInr": trade.pnlInr,
        "pnlPoints": trade.pnlPoints,
        "bestPnlPoints": trade.bestPnlPoints,
        "holdSeconds": _hold_seconds(trade),
        "context": event_ctx,
    })
    _update_summary(data)
    _save_day(date, data)

    trade_payload = _trade_payload(trade, context)
    _append_log("TRADE_CLOSED", {
        "trade": trade_payload,
        "holdSeconds": _hold_seconds(trade),
        "context": event_ctx,
    })
    logger.info(_human_log_line("TRADE_CLOSED", trade, context))
    _maybe_archive_completed_batch()


def _reports_file(date: Optional[str] = None) -> Path:
    d = date or _today()
    reports_dir = get_store_dir() / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir / f"{d}.jsonl"


def record_trade_report(report: dict[str, Any]) -> None:
    """Append structured post-trade analysis (one JSON line per close)."""
    date = str(report.get("sessionDate") or _today())[:10]
    entry = {"ts": _now().isoformat(), **report}
    line = json.dumps(entry, default=str, separators=(",", ":"))
    try:
        with open(_reports_file(date), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        logger.error("Failed to write trade report: %s", e)
    _append_log("TRADE_REPORT", {"report": report})


def get_trade_reports(
    *,
    date: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Recent trade close reports for dashboard / AI review."""
    path = _reports_file(date)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(out))


def get_trade_reports_range(days: int = 7, limit: int = 200) -> list[dict[str, Any]]:
    from datetime import timedelta

    reports: list[dict[str, Any]] = []
    today = _now().date()
    for i in range(max(1, min(days, 30))):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        reports.extend(get_trade_reports(date=d, limit=limit))
        if len(reports) >= limit:
            break
    return reports[:limit]


def _analysis_file(date: Optional[str] = None) -> Path:
    d = date or _today()
    analysis_dir = get_store_dir() / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    return analysis_dir / f"{d}.jsonl"


def record_analysis_report(report: dict[str, Any]) -> None:
    """Append interval market analysis (rules + optional AI) — one JSON line per cycle."""
    at = str(report.get("at") or _now().isoformat())
    date = at[:10]
    entry = {"ts": at, **report}
    line = json.dumps(entry, default=str, separators=(",", ":"))
    try:
        with open(_analysis_file(date), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        logger.error("Failed to write analysis report: %s", e)
        raise
    _append_log("ANALYSIS_REPORT", {
        "lagScore": report.get("lagScore"),
        "source": report.get("source"),
        "summary": (report.get("summary") or "")[:200],
    })


def get_analysis_reports(
    *,
    date: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    path = _analysis_file(date)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(out))


def get_analysis_reports_range(days: int = 7, limit: int = 200) -> list[dict[str, Any]]:
    from datetime import timedelta

    reports: list[dict[str, Any]] = []
    today = _now().date()
    for i in range(max(1, min(days, 30))):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        reports.extend(get_analysis_reports(date=d, limit=limit))
        if len(reports) >= limit:
            break
    return reports[:limit]


def record_session_reset(reason: str = "manual_reset", open_trade_ids: Optional[list[str]] = None) -> None:
    """Log session reset — aligns in-memory state with persistent store audit trail."""
    reset_at = set_session_reset_at()
    payload = {
        "reason": reason,
        "openTradeIds": open_trade_ids or [],
        "sessionDate": _today(),
        "resetAt": reset_at,
    }
    _append_log("SESSION_RESET", payload)
    logger.info("SESSION_RESET reason=%s open_trades=%s reset_at=%s", reason, len(open_trade_ids or []), reset_at)


def close_open_trades_on_reset(reason: str = "SESSION_RESET") -> list[str]:
    """Mark all persisted open trades closed on session reset."""
    closed_ids: list[str] = []
    for path in sorted(get_store_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        changed = False
        for t in data.get("trades", []):
            if t.get("status") != "OPEN":
                continue
            t["status"] = "CLOSED"
            t["exitReason"] = reason
            t["closedAt"] = _now().isoformat()
            t["pnlInr"] = t.get("pnlInr", 0)
            closed_ids.append(t["id"])
            changed = True
            data["events"].append({
                "type": "TRADE_CLOSED",
                "tradeId": t["id"],
                "timestamp": _now().isoformat(),
                "executionMode": t.get("executionMode", "PAPER"),
                "exitReason": reason,
                "pnlInr": t.get("pnlInr", 0),
                "context": {"reset": True},
            })
            try:
                trade = PaperTrade(**t)
                _append_log("TRADE_CLOSED", {
                    "trade": _trade_payload(trade, t.get("context")),
                    "context": {"reset": True, "reason": reason},
                })
            except Exception:
                _append_log("TRADE_CLOSED", {
                    "trade": {"id": t.get("id"), "status": "CLOSED", "exitReason": reason},
                    "context": {"reset": True},
                })
        if changed:
            _update_summary(data)
            _save_day(data.get("date", path.stem), data)
    return closed_ids


def check_store_health() -> dict[str, Any]:
    """Verify trade store and log are writable — used for live deployment readiness."""
    store_dir = get_store_dir()
    log_path = get_log_path()
    checks: dict[str, Any] = {
        "storeDirExists": store_dir.is_dir(),
        "storeDirWritable": os.access(store_dir, os.W_OK),
        "logFileExists": log_path.exists(),
        "logFileWritable": os.access(log_path.parent, os.W_OK),
    }
    checks["healthy"] = checks["storeDirWritable"] and checks["logFileWritable"]
    return {
        "storeDir": str(store_dir),
        "logFile": str(log_path),
        "logSizeBytes": log_path.stat().st_size if log_path.exists() else 0,
        "checks": checks,
    }


def get_recent_log_lines(limit: int = 100) -> list[dict[str, Any]]:
    """Return newest trade log entries (JSON lines), parsed."""
    path = get_log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        logger.warning("Failed to read trade log: %s", e)
        return []
    entries: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(entries))


def get_history(days: int = 30) -> list[dict[str, Any]]:
    """Return daily summaries for last N days."""
    results = []
    files = sorted(get_store_dir().glob("*.json"), reverse=True)
    for path in files[:days]:
        try:
            data = json.loads(path.read_text())
            results.append({
                "date": data.get("date", path.stem),
                "summary": data.get("summary", {}),
                "tradeCount": len(data.get("trades", [])),
                "eventCount": len(data.get("events", [])),
            })
        except Exception:
            continue
    return results


def get_day_detail(date: str) -> dict[str, Any]:
    """Full trade + event log for a specific day."""
    return _load_day(date)


def get_all_closed_trades(limit: int = 200) -> list[dict[str, Any]]:
    """All closed trades across days, newest first."""
    closed = get_all_closed_trades_chronological(limit=100_000)
    closed.sort(key=lambda x: x.get("closedAt", x.get("openedAt", "")), reverse=True)
    return closed[:limit]


def get_all_closed_trades_chronological(limit: int = 500) -> list[dict[str, Any]]:
    """All closed trades across days, oldest first (for milestone batches)."""
    closed: list[dict[str, Any]] = []
    for path in sorted(get_store_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text())
            for t in data.get("trades", []):
                if t.get("status") == "CLOSED":
                    closed.append(t)
        except Exception:
            continue
    closed.sort(key=lambda x: x.get("closedAt", x.get("openedAt", "")))
    return closed[:limit]


def count_all_closed_trades() -> int:
    return len(get_all_closed_trades_chronological(limit=100_000))


def purge_all_trade_data() -> dict[str, Any]:
    """
    Delete all persisted trade archives, log, and batch files.
    Use when old logs block gates (collect_session_trades reads today's file).
    """
    store = get_store_dir()
    removed: list[str] = []

    log_path = get_log_path()
    if log_path.exists():
        log_path.write_text("", encoding="utf-8")
        removed.append(str(log_path))

    for path in sorted(store.glob("????-??-??.json")):
        try:
            path.unlink()
            removed.append(str(path))
        except OSError as e:
            logger.warning("Failed to remove %s: %s", path, e)

    batches = store / "batches"
    if batches.exists():
        for path in sorted(batches.glob("*.json")):
            try:
                path.unlink()
                removed.append(str(path))
            except OSError as e:
                logger.warning("Failed to remove %s: %s", path, e)

    meta = {"batchOffset": 0, "purgedAt": _now().isoformat()}
    _milestone_meta_path().write_text(json.dumps(meta, indent=2), encoding="utf-8")
    removed.append(str(_milestone_meta_path()))

    session_meta = _session_meta_path()
    if session_meta.exists():
        try:
            session_meta.unlink()
            removed.append(str(session_meta))
        except OSError as e:
            logger.warning("Failed to remove %s: %s", session_meta, e)

    _append_log("PURGE_ALL", {"removedFiles": len(removed), "storeDir": str(store)})
    logger.warning("Purged all trade data — %d paths touched", len(removed))
    return {
        "storeDir": str(store),
        "removedCount": len(removed),
        "removedFiles": removed,
        "logSizeBytes": log_path.stat().st_size if log_path.exists() else 0,
    }


MILESTONE_BATCH_SIZE = 50
MILESTONE_META_FILE = "milestone_meta.json"
SESSION_META_FILE = "session_meta.json"


def _session_meta_path() -> Path:
    return get_store_dir() / SESSION_META_FILE


def set_session_reset_at(ts: Optional[datetime] = None) -> str:
    """Record IST timestamp of session reset — gates ignore trades closed before this."""
    ts = ts or _now()
    meta = {"lastResetAt": ts.isoformat(), "sessionDate": _today()}
    _session_meta_path().write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta["lastResetAt"]


def get_session_reset_at() -> Optional[datetime]:
    """Last manual/session reset time, or None if never reset today."""
    path = _session_meta_path()
    if path.exists():
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            raw = meta.get("lastResetAt")
            if raw:
                return datetime.fromisoformat(str(raw))
        except Exception as exc:
            logger.warning("Failed to read session meta: %s", exc)

    # Fallback: scan log for most recent SESSION_RESET today
    log_path = get_log_path()
    if not log_path.exists():
        return None
    today = _today()
    last_reset: Optional[datetime] = None
    try:
        for line in reversed(log_path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "SESSION_RESET":
                continue
            ts_raw = str(row.get("ts", ""))
            if not ts_raw.startswith(today):
                continue
            last_reset = datetime.fromisoformat(ts_raw)
            break
    except Exception as exc:
        logger.warning("Failed to scan log for SESSION_RESET: %s", exc)
    return last_reset


def _milestone_meta_path() -> Path:
    return get_store_dir() / MILESTONE_META_FILE


def get_milestone_batch_offset() -> int:
    path = _milestone_meta_path()
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
        return int(data.get("batchOffset") or 0)
    except Exception:
        return 0


def get_milestone_meta() -> dict[str, Any]:
    path = _milestone_meta_path()
    if not path.exists():
        return {"batchOffset": 0}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"batchOffset": 0}


def reset_milestone_batch(reason: str = "manual_reset") -> dict[str, Any]:
    """
    Start a fresh 50-trade milestone batch without deleting trade logs.
    Archives the prior batch window and sets offset to current closed count.
    """
    from app.engines.performance_milestone import _stats_for_trades

    all_closed = get_all_closed_trades_chronological(limit=100_000)
    offset = len(all_closed)
    prior_offset = get_milestone_batch_offset()
    batch_trades = all_closed[prior_offset:offset]

    archive_info: dict[str, Any] | None = None
    if batch_trades:
        batch_number = _next_batch_number()
        summary = _stats_for_trades(batch_trades)
        path = archive_milestone_batch(batch_number, batch_trades, {
            **summary,
            "resetReason": reason,
            "archivedOnReset": True,
        })
        archive_info = {
            "batchNumber": batch_number,
            "tradeCount": len(batch_trades),
            "summary": summary,
            "archiveFile": str(path),
        }

    meta = {
        "batchOffset": offset,
        "resetAt": _now().isoformat(),
        "reason": reason,
        "previousOffset": prior_offset,
        "lifetimeTradesAtReset": offset,
    }
    _milestone_meta_path().write_text(json.dumps(meta, indent=2, default=str))
    _append_log("MILESTONE_BATCH_RESET", {
        "batchOffset": offset,
        "reason": reason,
        "archivedBatch": archive_info,
    })
    logger.info("Milestone batch reset — offset=%d reason=%s", offset, reason)
    return {"meta": meta, "archivedBatch": archive_info}


def _batches_dir() -> Path:
    path = get_store_dir() / "batches"
    path.mkdir(parents=True, exist_ok=True)
    return path


def archive_milestone_batch(batch_number: int, trades: list[dict[str, Any]], summary: dict[str, Any]) -> Path:
    """Persist a completed 50-trade batch for review and learning."""
    payload = {
        "batchNumber": batch_number,
        "tradeCount": len(trades),
        "completedAt": _now().isoformat(),
        "summary": summary,
        "trades": trades,
    }
    path = _batches_dir() / f"batch-{batch_number:03d}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    _append_log("MILESTONE_BATCH_COMPLETE", {
        "batchNumber": batch_number,
        "tradeCount": len(trades),
        "summary": summary,
        "archiveFile": str(path),
    })
    logger.info(
        "MILESTONE_BATCH_COMPLETE batch=%d trades=%d pf=%s wr=%s",
        batch_number,
        len(trades),
        summary.get("profitFactor"),
        summary.get("winRate"),
    )
    return path


def _maybe_archive_completed_batch() -> None:
    """When current milestone window hits 50, 100… archive that batch."""
    from app.engines.performance_milestone import _stats_for_trades

    all_closed = get_all_closed_trades_chronological(limit=100_000)
    offset = get_milestone_batch_offset()
    window = all_closed[offset:]
    total = len(window)
    if total == 0 or total % MILESTONE_BATCH_SIZE != 0:
        return

    batch_number = _next_batch_number()
    batch_path = _batches_dir() / f"batch-{batch_number:03d}.json"
    if batch_path.exists():
        return

    start = total - MILESTONE_BATCH_SIZE
    batch_trades = window[start:total]
    summary = _stats_for_trades(batch_trades)
    archive_milestone_batch(batch_number, batch_trades, summary)


def _next_batch_number() -> int:
    existing = list(_batches_dir().glob("batch-*.json"))
    return len(existing) + 1


def list_milestone_batches(limit: int = 20) -> list[dict[str, Any]]:
    """Summaries of archived 50-trade batches, newest first."""
    results: list[dict[str, Any]] = []
    for path in sorted(_batches_dir().glob("batch-*.json"), reverse=True):
        try:
            data = json.loads(path.read_text())
            results.append({
                "batchNumber": data.get("batchNumber"),
                "tradeCount": data.get("tradeCount"),
                "completedAt": data.get("completedAt"),
                "summary": data.get("summary", {}),
                "archiveFile": str(path),
            })
        except Exception:
            continue
        if len(results) >= limit:
            break
    return results


def load_open_trades() -> list[dict[str, Any]]:
    """Restore open trades from all day files (supports multi-day swing holds)."""
    open_by_id: dict[str, dict[str, Any]] = {}
    for path in sorted(get_store_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text())
            for t in data.get("trades", []):
                if t.get("status") == "OPEN":
                    open_by_id[t["id"]] = t
        except Exception:
            continue
    return list(open_by_id.values())


def count_today_trades() -> dict[str, int]:
    """Quick counts for readiness dashboard."""
    data = _load_day(_today())
    trades = data.get("trades", [])
    return {
        "open": len([t for t in trades if t.get("status") == "OPEN"]),
        "closed": len([t for t in trades if t.get("status") == "CLOSED"]),
        "total": len(trades),
    }
