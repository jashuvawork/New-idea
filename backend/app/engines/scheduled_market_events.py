"""Verified scheduled-event context for FTV probability advisories."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
_IMPACTS = {"LOW", "MEDIUM", "HIGH"}
_SIDES = {"CALL", "PUT", "BOTH", "NEUTRAL"}


def _configured_events() -> list[dict[str, Any]]:
    raw = str(get_settings().ftv_scheduled_events_json or "[]")
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    events: list[dict[str, Any]] = []
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        try:
            starts = datetime.fromisoformat(
                f"{row['date']}T{row['time']}:00",
            ).replace(tzinfo=IST)
        except (KeyError, TypeError, ValueError):
            continue
        title = str(row.get("title") or "").strip()[:120]
        if not title:
            continue
        impact = str(row.get("impact") or "HIGH").upper()
        side = str(row.get("sideBias") or "BOTH").upper()
        symbols = [
            str(symbol).upper() for symbol in (row.get("symbols") or [])
            if str(symbol).strip()
        ][:10]
        events.append({
            "id": f"configured:{starts.isoformat()}:{title}",
            "title": title,
            "startsAt": starts,
            "durationMinutes": max(1, min(360, int(row.get("durationMinutes") or 30))),
            "impact": impact if impact in _IMPACTS else "HIGH",
            "symbols": symbols,
            "sideBias": side if side in _SIDES else "BOTH",
            "source": "operator_verified",
        })
    return events


def _expiry_events(
    snapshots: Mapping[str, SymbolSnapshot],
    now: datetime,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for symbol, snapshot in snapshots.items():
        expiry = str(snapshot.optionExpiry or "")[:10]
        if expiry != now.date().isoformat():
            continue
        starts = now.replace(hour=9, minute=15, second=0, microsecond=0)
        events.append({
            "id": f"exchange_expiry:{symbol}:{expiry}",
            "title": f"{symbol} option expiry session",
            "startsAt": starts,
            "durationMinutes": 375,
            "impact": "HIGH",
            "symbols": [symbol.upper()],
            "sideBias": "BOTH",
            "source": "upstox_option_expiry",
        })
    return events


def build_scheduled_event_context(
    snapshots: Mapping[str, SymbolSnapshot],
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    current = now or datetime.now(IST)
    lead = max(0, int(get_settings().ftv_scheduled_event_lead_minutes))
    rows = [*_configured_events(), *_expiry_events(snapshots, current)]
    events: list[dict[str, Any]] = []
    for row in rows:
        starts: datetime = row["startsAt"]
        ends = starts + timedelta(minutes=int(row["durationMinutes"]))
        minutes_to = int((starts - current).total_seconds() / 60)
        status = (
            "ACTIVE" if starts <= current <= ends
            else "UPCOMING" if 0 < minutes_to <= lead
            else "FUTURE" if minutes_to > lead
            else "ENDED"
        )
        events.append({
            **{key: value for key, value in row.items() if key != "startsAt"},
            "startsAt": starts.isoformat(),
            "endsAt": ends.isoformat(),
            "status": status,
            "minutesTo": max(0, minutes_to) if minutes_to > 0 else 0,
        })
    events.sort(key=lambda event: event["startsAt"])
    active = [
        event for event in events
        if event["status"] in {"ACTIVE", "UPCOMING"}
    ]
    return {
        "configured": bool(_configured_events()),
        "events": events,
        "activeOrUpcoming": active,
        "riskLevel": (
            "HIGH" if any(event["impact"] == "HIGH" for event in active)
            else "ELEVATED" if active
            else "NORMAL"
        ),
        "guardrail": "Only operator-verified schedules and Upstox expiry dates are used.",
    }
