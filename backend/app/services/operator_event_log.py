"""Append-only operator event log for live-session diagnostics."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from app.config import get_settings

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)


def _log_dir() -> Path:
    directory = Path(get_settings().trade_store_dir) / "operator_events"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def append_operator_event(kind: str, payload: Mapping[str, Any]) -> None:
    """Best-effort JSONL append — never raises into trading paths."""
    try:
        now = datetime.now(IST)
        row = {
            "at": now.isoformat(),
            "kind": str(kind),
            **dict(payload),
        }
        path = _log_dir() / f"{now.date().isoformat()}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, default=str) + "\n")
    except Exception as exc:
        logger.debug("operator_event_log_append_failed kind=%s err=%s", kind, exc)
