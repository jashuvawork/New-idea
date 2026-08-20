"""Runtime health telemetry for detector sampling, archives, analysis, and backups."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from app.config import get_settings

IST = ZoneInfo("Asia/Kolkata")
_lock = threading.RLock()
_state: dict[str, Any] = {
    "sources": {},
    "components": {},
    "backup": {},
    "counters": {},
}


def _now() -> datetime:
    return datetime.now(IST)


def _iso(now: datetime | None = None) -> str:
    value = now or _now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=IST)
    return value.astimezone(IST).isoformat()


def _top_keys(snapshots: Mapping[str, Any]) -> list[str]:
    keys: list[str] = []
    for symbol, snap in snapshots.items():
        alerts = getattr(snap, "explosionAlerts", None) or []
        if not alerts:
            continue
        alert = alerts[0]
        if not isinstance(alert, Mapping):
            continue
        side = str(alert.get("side") or "").upper()
        try:
            strike = f"{float(alert.get('strike') or 0):g}"
        except (TypeError, ValueError):
            strike = "0"
        keys.append(f"{symbol.upper()}:{side}:{strike}")
    return sorted(keys)


def record_source(
    source: str,
    snapshots: Mapping[str, Any],
    *,
    archive_count: int | None = None,
    now: datetime | None = None,
) -> None:
    seen_at = _iso(now)
    with _lock:
        previous = dict(_state["sources"].get(source) or {})
        symbol_states = {
            str(symbol).upper(): dict(value)
            for symbol, value in (previous.get("symbolStates") or {}).items()
        }
        for symbol, snap in snapshots.items():
            symbol_name = str(symbol).upper()
            symbol_states[symbol_name] = {
                "lastSeenAt": seen_at,
                "topRadarKeys": _top_keys({symbol_name: snap}),
                "dataAvailable": bool(getattr(snap, "dataAvailable", False)),
            }
        row = {
            "lastSeenAt": seen_at,
            "symbols": sorted(symbol_states),
            "topRadarKeys": sorted({
                key
                for state in symbol_states.values()
                for key in state.get("topRadarKeys") or []
            }),
            "dataAvailableCount": sum(
                1 for state in symbol_states.values()
                if state.get("dataAvailable")
            ),
            "symbolStates": symbol_states,
        }
        if archive_count is not None:
            row["archiveEntryCount"] = archive_count
        elif "archiveEntryCount" in previous:
            row["archiveEntryCount"] = previous["archiveEntryCount"]
        _state["sources"][source] = row
        _state["counters"][source] = int(_state["counters"].get(source, 0)) + 1


def record_component_success(
    component: str,
    *,
    detail: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    with _lock:
        _state["components"][component] = {
            "healthy": True,
            "lastSuccessAt": _iso(now),
            "lastError": None,
            **dict(detail or {}),
        }
        _state["counters"][f"{component}Success"] = (
            int(_state["counters"].get(f"{component}Success", 0)) + 1
        )


def record_component_error(
    component: str,
    error: Exception | str,
    *,
    now: datetime | None = None,
) -> None:
    with _lock:
        previous = dict(_state["components"].get(component) or {})
        _state["components"][component] = {
            **previous,
            "healthy": False,
            "lastErrorAt": _iso(now),
            "lastError": str(error)[:500],
        }
        _state["counters"][f"{component}Error"] = (
            int(_state["counters"].get(f"{component}Error", 0)) + 1
        )


def record_backup(
    *,
    destination: str,
    file_name: str,
    success: bool,
    error: str | None = None,
    now: datetime | None = None,
) -> None:
    with _lock:
        _state["backup"] = {
            "healthy": success,
            "lastAttemptAt": _iso(now),
            "destination": destination,
            "fileName": file_name,
            "lastError": error,
        }


def _age_seconds(raw: Any, now: datetime) -> float | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return max(0.0, (now - parsed.astimezone(IST)).total_seconds())
    except (TypeError, ValueError):
        return None


def health_status(*, now: datetime | None = None) -> dict[str, Any]:
    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    current = current.astimezone(IST)
    settings = get_settings()
    stale_after = max(1, int(settings.radar_health_stale_seconds))
    rest_stale_after = max(
        stale_after,
        int(float(getattr(settings, "full_rest_min_seconds", 45.0) or 45.0) * 2),
        int(float(getattr(settings, "full_rest_backoff_seconds", 75.0) or 75.0) + 30),
    )
    with _lock:
        sources = {
            key: {
                **dict(value),
                "symbolStates": {
                    symbol: dict(state)
                    for symbol, state in (value.get("symbolStates") or {}).items()
                },
            }
            for key, value in _state["sources"].items()
        }
        components = {
            key: dict(value)
            for key, value in _state["components"].items()
        }
        backup = dict(_state["backup"])
        counters = dict(_state["counters"])

    stale_sources: list[str] = []
    for source, row in sources.items():
        age = _age_seconds(row.get("lastSeenAt"), current)
        source_stale_after = rest_stale_after if source == "rest_snapshot" else stale_after
        symbol_states = row.pop("symbolStates", {})
        if symbol_states:
            active_states = {
                symbol: state
                for symbol, state in symbol_states.items()
                if (
                    (symbol_age := _age_seconds(state.get("lastSeenAt"), current))
                    is not None
                    and symbol_age <= source_stale_after
                )
            }
            row["symbols"] = sorted(active_states)
            row["topRadarKeys"] = sorted({
                key
                for state in active_states.values()
                for key in state.get("topRadarKeys") or []
            })
            row["dataAvailableCount"] = sum(
                1 for state in active_states.values()
                if state.get("dataAvailable")
            )
        row["ageSeconds"] = round(age, 1) if age is not None else None
        row["staleAfterSeconds"] = source_stale_after
        row["stale"] = bool(age is not None and age > source_stale_after)
        if row["stale"]:
            stale_sources.append(source)

    rest = sources.get("rest_snapshot") or {}
    ws = sources.get("ws_entry_scan") or {}
    rest_keys = set(rest.get("topRadarKeys") or [])
    ws_keys = set(ws.get("topRadarKeys") or [])
    both_fresh = bool(rest and ws and not rest.get("stale") and not ws.get("stale"))
    divergence = sorted(rest_keys.symmetric_difference(ws_keys)) if both_fresh else []
    component_errors = [
        name for name, row in components.items()
        if row.get("healthy") is False
    ]
    try:
        from app.services.upstox import get_market_phase

        market_phase = str(get_market_phase())
    except Exception:
        market_phase = "UNKNOWN"
    live_market = market_phase == "LIVE_MARKET"
    try:
        from app.routers.market import latency_stats
        from app.services.upstox_ws import ws_status

        websocket = ws_status()
        cadence = latency_stats()
    except Exception as exc:
        websocket = {"statusError": str(exc)}
        cadence = {"statusError": str(exc)}
    alerts: list[dict[str, str]] = []
    if live_market:
        if websocket.get("streamStale"):
            alerts.append({
                "severity": "critical",
                "code": "WS_STREAM_STALE",
                "message": "WebSocket is connected but market messages are stale",
            })
        if websocket.get("connected") and not websocket.get("hasRecentTicks"):
            alerts.append({
                "severity": "critical",
                "code": "TICK_FEED_STALE",
                "message": "WebSocket has no recent option ticks",
            })
        # rest_snapshot is a BACKUP source; the live trading path runs off the WS entry
        # scan. A lagging REST backup while the primary WS feed is fresh is a degraded-
        # backup notice (info), NOT a radar-unhealthy condition — otherwise normal REST
        # rebuild-cadence jitter flips the whole system unhealthy for no trading impact.
        ws_fresh = bool(ws and not ws.get("stale"))
        for source in stale_sources:
            severity = "warning"
            if source == "rest_snapshot" and ws_fresh:
                severity = "info"
            alerts.append({
                "severity": severity,
                "code": "RADAR_SCAN_STALE",
                "message": f"{source} has exceeded its expected scan cadence",
            })
        if divergence:
            alerts.append({
                "severity": "warning",
                "code": "REST_WS_DIVERGENCE",
                "message": "Fresh REST and WS scans disagree on the top radar contract",
            })
        if cadence.get("fullRestRebuildRunning") and cadence.get("buildInProgress"):
            alerts.append({
                "severity": "info",
                "code": "REST_REBUILD_ACTIVE",
                "message": "A full REST chain rebuild is currently in progress",
            })
    for component in component_errors:
        alerts.append({
            "severity": "warning",
            "code": "RADAR_COMPONENT_ERROR",
            "message": f"{component} reported a persistence or analysis error",
        })
    healthy = not any(
        alert["severity"] in {"critical", "warning"}
        for alert in alerts
    )
    return {
        "healthy": healthy,
        "at": current.isoformat(),
        "marketPhase": market_phase,
        "staleAfterSeconds": stale_after,
        "staleSources": stale_sources,
        "sourceDivergence": {
            "active": bool(divergence),
            "keys": divergence,
            "restTopRadarKeys": sorted(rest_keys),
            "wsTopRadarKeys": sorted(ws_keys),
        },
        "sources": sources,
        "components": components,
        "backup": backup,
        "counters": counters,
        "feed": websocket,
        "cadence": cadence,
        "alerts": alerts,
    }


def reset_health_for_tests() -> None:
    with _lock:
        _state["sources"].clear()
        _state["components"].clear()
        _state["backup"].clear()
        _state["counters"].clear()
