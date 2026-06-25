"""Persistent paper trade storage — daily archives for learning and review."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.models.schemas import PaperTrade

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_store_dir: Optional[Path] = None


def get_store_dir() -> Path:
    global _store_dir
    if _store_dir is None:
        from app.config import get_settings

        _store_dir = Path(get_settings().trade_store_dir)
        _store_dir.mkdir(parents=True, exist_ok=True)
    return _store_dir


def _today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


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


def _trade_to_record(trade: PaperTrade, context: Optional[dict] = None) -> dict[str, Any]:
    record = trade.model_dump(mode="json")
    if context:
        record["context"] = context
    return record


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


def record_trade_opened(trade: PaperTrade, context: Optional[dict] = None) -> None:
    """Persist trade open event."""
    date = _today()
    data = _load_day(date)
    record = _trade_to_record(trade, context)
    record["sessionDate"] = date

    # Update or add to trades list
    existing = {t["id"]: i for i, t in enumerate(data["trades"])}
    if trade.id in existing:
        data["trades"][existing[trade.id]] = record
    else:
        data["trades"].append(record)

    data["events"].append({
        "type": "PAPER_OPENED",
        "tradeId": trade.id,
        "timestamp": datetime.now(IST).isoformat(),
        "symbol": trade.symbol,
        "side": trade.side.value if hasattr(trade.side, "value") else trade.side,
        "strike": trade.strike,
        "premium": trade.entryPremium,
        "strategy": trade.strategyType.value if hasattr(trade.strategyType, "value") else trade.strategyType,
        "context": context or {},
    })
    _update_summary(data)
    _save_day(date, data)
    logger.info("Stored paper trade open: %s", trade.id)


def record_trade_closed(trade: PaperTrade, context: Optional[dict] = None) -> None:
    """Persist trade close event with full outcome."""
    date = trade.openedAt.astimezone(IST).strftime("%Y-%m-%d") if trade.openedAt.tzinfo else _today()
    data = _load_day(date)
    record = _trade_to_record(trade, context)
    record["sessionDate"] = date
    record["closedAt"] = datetime.now(IST).isoformat()
    record["status"] = "CLOSED"

    existing = {t["id"]: i for i, t in enumerate(data["trades"])}
    if trade.id in existing:
        data["trades"][existing[trade.id]] = record
    else:
        data["trades"].append(record)

    data["events"].append({
        "type": "EXITED",
        "tradeId": trade.id,
        "timestamp": datetime.now(IST).isoformat(),
        "exitReason": trade.exitReason,
        "pnlInr": trade.pnlInr,
        "pnlPoints": trade.pnlPoints,
        "bestPnlPoints": trade.bestPnlPoints,
        "holdSeconds": _hold_seconds(trade),
        "context": context or {},
    })
    _update_summary(data)
    _save_day(date, data)
    logger.info("Stored paper trade close: %s pnl=%.0f reason=%s", trade.id, trade.pnlInr, trade.exitReason)


def _hold_seconds(trade: PaperTrade) -> float:
    try:
        opened = trade.openedAt
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=IST)
        return (datetime.now(IST) - opened.astimezone(IST)).total_seconds()
    except Exception:
        return 0


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
    closed = []
    for path in sorted(get_store_dir().glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text())
            for t in data.get("trades", []):
                if t.get("status") == "CLOSED":
                    closed.append(t)
        except Exception:
            continue
    closed.sort(key=lambda x: x.get("closedAt", x.get("openedAt", "")), reverse=True)
    return closed[:limit]


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
