"""Daily compressed archive of the best radar observation for each option contract."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping
from zoneinfo import ZoneInfo

from app.config import get_settings

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
SCHEMA_VERSION = 1
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ARCHIVE_RE = re.compile(r"^radar-(\d{4}-\d{2}-\d{2})\.zip$")
_TIER_RANK = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}


def get_archive_dir() -> Path:
    settings = get_settings()
    configured = str(getattr(settings, "radar_archive_dir", "") or "").strip()
    path = (
        Path(configured)
        if configured
        else Path(settings.trade_store_dir) / "radar_archives"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def archive_path(date: str) -> Path:
    if not _DATE_RE.fullmatch(date):
        raise ValueError("date must use YYYY-MM-DD")
    return get_archive_dir() / f"radar-{date}.zip"


def _now() -> datetime:
    return datetime.now(IST)


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default))


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _radar_key(symbol: str, alert: Mapping[str, Any]) -> str:
    side = str(alert.get("side") or "").upper()
    strike = _number(alert.get("strike"))
    return f"{symbol.upper()}:{side}:{strike:g}"


def _review_rank(alert: Mapping[str, Any]) -> tuple[float, ...]:
    tier = str(alert.get("tier") or "WATCH").upper()
    return (
        float(_TIER_RANK.get(tier, 0)),
        1.0 if alert.get("tradeable") else 0.0,
        1.0 if alert.get("ictFirstLift") else 0.0,
        _number(alert.get("flatVerticalQuality")),
        _number(alert.get("explosionScore")),
        _number(alert.get("ictScore")),
        _number(alert.get("peakMovePct")),
        _number(alert.get("dailyMovePct") or alert.get("openPremiumMove")),
        _number(alert.get("velocity3s")),
    )


def _worth_archiving(alert: Mapping[str, Any]) -> bool:
    tier = str(alert.get("tier") or "WATCH").upper()
    return bool(
        _TIER_RANK.get(tier, 0) >= _TIER_RANK["BUILDING"]
        or alert.get("tradeable")
        or alert.get("ictFirstLift")
        or alert.get("ictBreakout")
        or alert.get("allDayExplosion")
    )


def _snapshot_context(symbol: str, snap: Any, source: str) -> dict[str, Any]:
    breadth = getattr(snap, "breadth", None)
    chart = getattr(snap, "spotChart", None)
    regime = getattr(snap, "regime", None)
    phase = getattr(snap, "marketPhase", None)
    return _jsonable({
        "symbol": symbol.upper(),
        "archiveSource": source,
        "volumeReliable": source != "ws_entry_scan",
        "timestamp": getattr(snap, "timestamp", None),
        "marketPhase": getattr(phase, "value", phase),
        "spot": getattr(snap, "spot", None),
        "atmStrike": getattr(snap, "atmStrike", None),
        "optionExpiry": getattr(snap, "optionExpiry", None),
        "tradeQualityScore": getattr(snap, "tradeQualityScore", None),
        "regime": getattr(regime, "value", regime),
        "breadth": breadth,
        "spotChart": chart,
        "pcr": getattr(snap, "pcr", None),
        "maxPain": getattr(snap, "maxPain", None),
        "indiaVix": getattr(snap, "indiaVix", None),
    })


def _milestone(
    alert: Mapping[str, Any],
    seen_at: str,
    source: str,
) -> dict[str, Any]:
    return _jsonable({
        "seenAt": seen_at,
        "source": source,
        "volumeReliable": source != "ws_entry_scan",
        "tier": alert.get("tier"),
        "premium": alert.get("premium"),
        "explosionScore": alert.get("explosionScore"),
        "ictScore": alert.get("ictScore"),
        "dailyMovePct": alert.get("dailyMovePct"),
        "peakMovePct": alert.get("peakMovePct"),
        "localBaseMovePct": alert.get("localBaseMovePct"),
        "flatVerticalQuality": alert.get("flatVerticalQuality"),
        "velocity3s": alert.get("velocity3s"),
        "volumeSurge": alert.get("volumeSurge"),
        "momentType": alert.get("momentType"),
        "tradeable": alert.get("tradeable"),
    })


def _load_entries(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        with zipfile.ZipFile(path, "r") as archive:
            rows = json.loads(archive.read("top_radars.json"))
        return {
            str(row["key"]): row
            for row in rows
            if isinstance(row, dict) and row.get("key")
        }
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        logger.warning("Failed to read radar archive %s: %s", path, exc)
        return {}


@contextmanager
def _archive_lock(directory: Path, date: str) -> Iterator[None]:
    lock_path = directory / f".radar-{date}.lock"
    with lock_path.open("a+") as handle:
        try:
            import fcntl
        except ImportError:
            yield
            return

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def _write_archive(
    path: Path,
    date: str,
    entries: list[dict[str, Any]],
    now: datetime,
    *,
    extra_artifacts: Mapping[str, bytes | str] | None = None,
) -> None:
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "date": date,
        "timezone": "Asia/Kolkata",
        "updatedAt": now.isoformat(),
        "count": len(entries),
        "selection": (
            "Best observation per symbol/side/strike, ordered by tier, tradeability, "
            "first-lift state, flat-to-vertical quality, score, and peak move."
        ),
    }
    readme = (
        "NexusQuant daily top-radar archive\n"
        "top_radars.json contains the strongest saved observation for each option contract.\n"
        "milestones preserves up to 20 improving observations for later review.\n"
    )
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        preserved: dict[str, bytes] = {}
        if path.exists():
            try:
                with zipfile.ZipFile(path, "r") as existing:
                    for name in existing.namelist():
                        if name not in {"manifest.json", "top_radars.json", "README.txt"}:
                            preserved[name] = existing.read(name)
            except (OSError, zipfile.BadZipFile):
                preserved = {}
        for name, payload in (extra_artifacts or {}).items():
            preserved[name] = payload.encode() if isinstance(payload, str) else payload
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("top_radars.json", json.dumps(entries, indent=2))
            archive.writestr("README.txt", readme)
            for name, payload in preserved.items():
                archive.writestr(name, payload)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _prune_old_archives(directory: Path, now: datetime, retention_days: int) -> None:
    if retention_days <= 0:
        return
    cutoff = now.date() - timedelta(days=retention_days)
    for path in directory.glob("radar-*.zip"):
        match = _ARCHIVE_RE.fullmatch(path.name)
        if not match:
            continue
        try:
            archive_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if archive_date < cutoff:
            path.unlink(missing_ok=True)


def record_top_radars(
    snapshots: Mapping[str, Any],
    *,
    now: datetime | None = None,
    source: str = "snapshot",
) -> int:
    """Merge improved radar observations into today's ZIP; return saved entry count."""
    settings = get_settings()
    if not bool(getattr(settings, "radar_archive_enabled", True)):
        return 0

    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    current = current.astimezone(IST)
    date = current.strftime("%Y-%m-%d")
    seen_at = current.isoformat()
    directory = get_archive_dir()
    path = archive_path(date)
    top_n = max(
        1,
        int(getattr(settings, "radar_archive_top_n_per_day", 100) or 100),
    )

    with _archive_lock(directory, date):
        entries = _load_entries(path)
        changed = not path.exists()
        for symbol, snap in snapshots.items():
            if not bool(getattr(snap, "dataAvailable", False)):
                continue
            context = _snapshot_context(symbol, snap, source)
            for raw_alert in getattr(snap, "explosionAlerts", None) or []:
                if not isinstance(raw_alert, Mapping) or not _worth_archiving(raw_alert):
                    continue
                alert = _jsonable(dict(raw_alert))
                key = _radar_key(symbol, alert)
                rank = _review_rank(alert)
                previous = entries.get(key)
                previous_rank = tuple(previous.get("_rank") or ()) if previous else ()
                if previous and rank <= previous_rank:
                    continue
                milestones = list(previous.get("milestones") or []) if previous else []
                milestones.append(_milestone(alert, seen_at, source))
                entries[key] = {
                    "key": key,
                    "firstSeenAt": (
                        previous.get("firstSeenAt")
                        if previous
                        else seen_at
                    ),
                    "bestSeenAt": seen_at,
                    "symbol": symbol.upper(),
                    "side": str(alert.get("side") or "").upper(),
                    "strike": _number(alert.get("strike")),
                    "tier": str(alert.get("tier") or "WATCH").upper(),
                    "alert": alert,
                    "context": context,
                    "milestones": milestones[-20:],
                    "outcome": dict(previous.get("outcome") or {}) if previous else {},
                    "_rank": list(rank),
                }
                changed = True

        ordered = sorted(
            entries.values(),
            key=lambda row: tuple(row.get("_rank") or ()),
            reverse=True,
        )[:top_n]
        if changed or len(ordered) != len(entries):
            _write_archive(path, date, ordered, current)

    _prune_old_archives(
        directory,
        current,
        int(getattr(settings, "radar_archive_retention_days", 365) or 365),
    )
    try:
        from app.services.radar_health import (
            record_component_success,
            record_source,
        )

        record_source(source, snapshots, archive_count=len(ordered), now=current)
        record_component_success(
            "radarArchive",
            detail={"date": date, "entryCount": len(ordered)},
            now=current,
        )
    except Exception:
        pass
    return len(ordered)


def read_archive_entries(date: str) -> list[dict[str, Any]]:
    """Read one day's ordered radar entries."""
    return list(_load_entries(archive_path(date)).values())


def update_archive_outcomes(
    date: str,
    outcomes: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> int:
    """Atomically merge forward outcomes into existing radar entries."""
    if not outcomes:
        return 0
    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    current = current.astimezone(IST)
    directory = get_archive_dir()
    path = archive_path(date)
    if not path.exists():
        return 0
    changed = 0
    with _archive_lock(directory, date):
        entries = _load_entries(path)
        for key, outcome in outcomes.items():
            row = entries.get(key)
            if row is None:
                continue
            normalized = _jsonable(dict(outcome))
            if row.get("outcome") == normalized:
                continue
            row["outcome"] = normalized
            changed += 1
        if changed:
            ordered = sorted(
                entries.values(),
                key=lambda row: tuple(row.get("_rank") or ()),
                reverse=True,
            )
            _write_archive(path, date, ordered, current)
    return changed


def add_archive_artifacts(
    date: str,
    artifacts: Mapping[str, bytes | str],
    *,
    now: datetime | None = None,
) -> Path:
    """Atomically add analysis/tape artifacts to a day's canonical ZIP."""
    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    current = current.astimezone(IST)
    directory = get_archive_dir()
    path = archive_path(date)
    with _archive_lock(directory, date):
        entries = _load_entries(path)
        _write_archive(
            path,
            date,
            sorted(
                entries.values(),
                key=lambda row: tuple(row.get("_rank") or ()),
                reverse=True,
            ),
            current,
            extra_artifacts=artifacts,
        )
    return path


def list_archives(limit: int = 30) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(get_archive_dir().glob("radar-*.zip"), reverse=True):
        match = _ARCHIVE_RE.fullmatch(path.name)
        if not match:
            continue
        row: dict[str, Any] = {
            "date": match.group(1),
            "fileName": path.name,
            "sizeBytes": path.stat().st_size,
            "downloadUrl": f"/api/ai/radar-archives/{match.group(1)}",
        }
        try:
            with zipfile.ZipFile(path, "r") as archive:
                manifest = json.loads(archive.read("manifest.json"))
            row.update({
                "count": int(manifest.get("count") or 0),
                "updatedAt": manifest.get("updatedAt"),
                "schemaVersion": manifest.get("schemaVersion"),
            })
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            row["corrupt"] = True
        rows.append(row)
        if len(rows) >= max(1, limit):
            break
    return rows
