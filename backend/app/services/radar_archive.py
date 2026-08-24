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
SCHEMA_VERSION = 2
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ARCHIVE_RE = re.compile(r"^radar-(\d{4}-\d{2}-\d{2})\.zip$")
_TIER_RANK = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}


class RadarArchiveCorruptError(RuntimeError):
    """Raised when an existing archive cannot be read without risking data loss."""


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


_DATA_PURGE_STATE_FILE = "data_purge.state"


def _data_purge_state_path() -> Path:
    return get_archive_dir() / _DATA_PURGE_STATE_FILE


def _read_data_purge_date() -> "datetime.date | None":
    try:
        raw = _data_purge_state_path().read_text(encoding="utf-8").strip()[:10]
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (OSError, ValueError):
        return None


def _write_data_purge_date(now: datetime) -> None:
    try:
        _data_purge_state_path().write_text(now.date().isoformat(), encoding="utf-8")
    except OSError:
        pass


def data_purge_due(
    now: datetime | None = None,
    *,
    interval_days: int | None = None,
) -> bool:
    """True when >= interval_days have passed since the last full radar-data purge.

    First run seeds the timer (writes the state file, returns False) so a deploy never
    triggers a surprise wipe — the first purge lands one interval later.
    """
    settings = get_settings()
    if not bool(getattr(settings, "radar_data_purge_enabled", True)):
        return False
    interval = int(
        interval_days
        if interval_days is not None
        else getattr(settings, "radar_data_purge_interval_days", 6) or 6
    )
    if interval <= 0:
        return False
    current = now or _now()
    last = _read_data_purge_date()
    if last is None:
        _write_data_purge_date(current)
        return False
    return (current.date() - last).days >= interval


def purge_all_radar_data(now: datetime | None = None) -> dict[str, Any]:
    """Delete EVERY radar data file (archive zips, premium/alert tapes, telemetry).

    The tapes/archives exist only for end-of-day replay & review — the LIVE detector never
    reads them — so a periodic full wipe caps disk usage without affecting trading. Scoped
    to the radar-archive directory only; trade records elsewhere are untouched. The purge
    timer state file itself is preserved so the cadence keeps running.
    """
    current = now or _now()
    directory = get_archive_dir()
    state_path = _data_purge_state_path()
    removed = 0
    freed = 0
    errors = 0
    for path in directory.rglob("*"):
        if path == state_path or not path.is_file():
            continue
        try:
            freed += path.stat().st_size
            path.unlink()
            removed += 1
        except OSError:
            errors += 1
    _write_data_purge_date(current)
    logger.info(
        "radar_data_purge: removed %d files, freed %.1f MB (%d errors)",
        removed,
        freed / 1_000_000.0,
        errors,
    )
    return {
        "removed": removed,
        "freedBytes": freed,
        "errors": errors,
        "at": current.isoformat(),
    }


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


def _instrument_key(snap: Any, alert: Mapping[str, Any]) -> str | None:
    strike = _number(alert.get("strike"))
    side = str(alert.get("side") or "").upper()
    for row in getattr(snap, "heatmap", None) or []:
        if abs(_number(getattr(row, "strike", None)) - strike) >= 1:
            continue
        value = (
            getattr(row, "callInstrumentKey", None)
            if side == "CALL"
            else getattr(row, "putInstrumentKey", None)
        )
        return str(value) if value else None
    return None


def _review_rank(alert: Mapping[str, Any]) -> tuple[float, ...]:
    tier = str(alert.get("tier") or "WATCH").upper()
    return (
        float(_TIER_RANK.get(tier, 0)),
        1.0 if alert.get("tradeable") else 0.0,
        1.0 if alert.get("ictFirstLift") else 0.0,
        1.0 if alert.get("ictEliteBaseReady") else 0.0,
        1.0 if alert.get("ictArmedBaseLaunch") else 0.0,
        1.0 if alert.get("ictBaseArmed") else 0.0,
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
        or alert.get("ictEliteBaseReady")
        or alert.get("ictArmedBaseLaunch")
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
        "velocity9s": alert.get("velocity9s"),
        "volumeSurge": alert.get("volumeSurge"),
        "ictFirstLift": alert.get("ictFirstLift"),
        "ictBaseArmed": alert.get("ictBaseArmed"),
        "ictEliteBaseReady": alert.get("ictEliteBaseReady"),
        "ictArmedBaseLaunch": alert.get("ictArmedBaseLaunch"),
        "ictArmedBaseSamples": alert.get("ictArmedBaseSamples"),
        "ictArmedBaseSpanSeconds": alert.get("ictArmedBaseSpanSeconds"),
        "ictArmedBaseRangePct": alert.get("ictArmedBaseRangePct"),
        "ictBaseArmedAt": alert.get("ictBaseArmedAt"),
        "ictBaseExpiresAt": alert.get("ictBaseExpiresAt"),
        "ictVolumeAwakening": alert.get("ictVolumeAwakening"),
        "ictBasePremium": alert.get("ictBasePremium"),
        "ictBaseRelativeMovePct": alert.get("ictBaseRelativeMovePct"),
        "momentType": alert.get("momentType"),
        "tradeable": alert.get("tradeable"),
    })


def _should_append_detection_milestone(
    previous: Mapping[str, Any],
    alert: Mapping[str, Any],
    seen_at: str,
) -> bool:
    """Retain causal tradeable moments even when an older alert has a higher rank."""
    if not (
        alert.get("tradeable")
        or alert.get("ictFirstLift")
        or alert.get("ictArmedBaseLaunch")
    ):
        return False
    milestones = list(previous.get("milestones") or [])
    if not milestones:
        return True
    try:
        current = datetime.fromisoformat(seen_at)
        prior = datetime.fromisoformat(str(milestones[-1].get("seenAt")))
        return (current - prior).total_seconds() >= 30.0
    except (TypeError, ValueError):
        return True


def _load_entries(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = set(archive.namelist())
            source = "all_radars.json" if "all_radars.json" in names else "top_radars.json"
            rows = json.loads(archive.read(source))
        return {
            str(row["key"]): row
            for row in rows
            if isinstance(row, dict) and row.get("key")
        }
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        logger.warning("Failed to read radar archive %s: %s", path, exc)
        raise RadarArchiveCorruptError(
            f"Radar archive is corrupt and was preserved: {path.name}"
        ) from exc


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
    top_n = max(
        1,
        int(getattr(get_settings(), "radar_archive_top_n_per_day", 100) or 100),
    )
    top_entries = entries[:top_n]
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "date": date,
        "timezone": "Asia/Kolkata",
        "updatedAt": now.isoformat(),
        "count": len(top_entries),
        "totalDetectedCount": len(entries),
        "selection": (
            "Best observation per symbol/side/strike, ordered by tier, tradeability, "
            "first-lift/armed-launch state, flat-to-vertical quality, score, and peak move."
        ),
    }
    readme = (
        "NexusQuant daily top-radar archive\n"
        "top_radars.json contains the strongest saved observation for each option contract.\n"
        "all_radars.json preserves every qualifying contract for complete funnel review.\n"
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
                        if name not in {
                            "manifest.json",
                            "top_radars.json",
                            "all_radars.json",
                            "backup_status.json",
                            "README.txt",
                        }:
                            preserved[name] = existing.read(name)
            except (OSError, zipfile.BadZipFile):
                preserved = {}
        for name, payload in (extra_artifacts or {}).items():
            preserved[name] = payload.encode() if isinstance(payload, str) else payload
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("top_radars.json", json.dumps(top_entries, indent=2))
            archive.writestr("all_radars.json", json.dumps(entries, indent=2))
            archive.writestr("README.txt", readme)
            for name, payload in preserved.items():
                archive.writestr(name, payload)
        os.replace(tmp, path)
        path.with_suffix(".backup.json").unlink(missing_ok=True)
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
            path.with_suffix(".backup.json").unlink(missing_ok=True)


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
    detected_events: list[dict[str, Any]] = []

    with _archive_lock(directory, date):
        entries = _load_entries(path)
        changed = False
        for symbol, snap in snapshots.items():
            if not bool(getattr(snap, "dataAvailable", False)):
                continue
            context = _snapshot_context(symbol, snap, source)
            for raw_alert in getattr(snap, "explosionAlerts", None) or []:
                if not isinstance(raw_alert, Mapping) or not _worth_archiving(raw_alert):
                    continue
                alert = _jsonable(dict(raw_alert))
                alert.setdefault("instrumentKey", _instrument_key(snap, alert))
                key = _radar_key(symbol, alert)
                rank = _review_rank(alert)
                previous = entries.get(key)
                previous_rank = tuple(previous.get("_rank") or ()) if previous else ()
                if previous and rank <= previous_rank:
                    if _should_append_detection_milestone(previous, alert, seen_at):
                        milestones = list(previous.get("milestones") or [])
                        milestones.append(_milestone(alert, seen_at, source))
                        previous["milestones"] = milestones[-20:]
                        detected_events.append({
                            "event": "DETECTED",
                            "key": key,
                            "symbol": symbol.upper(),
                            "side": str(alert.get("side") or "").upper(),
                            "strike": _number(alert.get("strike")),
                            "stage": "radar",
                            "source": source,
                            "tier": alert.get("tier"),
                            "score": alert.get("explosionScore"),
                            "momentType": alert.get("momentType"),
                        })
                        changed = True
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
                detected_events.append({
                    "event": "DETECTED",
                    "key": key,
                    "symbol": symbol.upper(),
                    "side": str(alert.get("side") or "").upper(),
                    "strike": _number(alert.get("strike")),
                    "stage": "radar",
                    "source": source,
                    "tier": alert.get("tier"),
                    "score": alert.get("explosionScore"),
                    "momentType": alert.get("momentType"),
                })
                changed = True

        ordered = sorted(
            entries.values(),
            key=lambda row: tuple(row.get("_rank") or ()),
            reverse=True,
        )
        if changed:
            _write_archive(path, date, ordered, current)

    _prune_old_archives(
        directory,
        current,
        int(getattr(settings, "radar_archive_retention_days", 365) or 365),
    )
    try:
        from app.services.radar_learning import record_funnel_event
        from app.services.radar_health import (
            record_component_success,
            record_source,
        )

        top_count = min(len(ordered), top_n)
        record_source(source, snapshots, archive_count=top_count, now=current)
        record_component_success(
            "radarArchive",
            detail={
                "date": date,
                "entryCount": top_count,
                "totalDetectedCount": len(ordered),
            },
            now=current,
        )
        for event in detected_events:
            record_funnel_event(event, now=current, date=date)
    except Exception:
        pass
    return min(len(ordered), top_n)


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
                "totalDetectedCount": int(
                    manifest.get("totalDetectedCount")
                    or manifest.get("count")
                    or 0
                ),
                "updatedAt": manifest.get("updatedAt"),
                "schemaVersion": manifest.get("schemaVersion"),
            })
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            row["corrupt"] = True
        rows.append(row)
        if len(rows) >= max(1, limit):
            break
    return rows
