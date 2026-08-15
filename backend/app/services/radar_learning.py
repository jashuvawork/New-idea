"""Premium tape, forward outcomes, hindsight scoring, funnel analytics, and backups."""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import zipfile
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.radar_archive import (
    add_archive_artifacts,
    archive_path,
    get_archive_dir,
    read_archive_entries,
    update_archive_outcomes,
)

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
_lock = threading.RLock()
_last_tape_sample: dict[str, datetime] = {}
_last_funnel_event: dict[str, datetime] = {}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _now() -> datetime:
    return datetime.now(IST)


def _aware(value: datetime | None = None) -> datetime:
    result = value or _now()
    if result.tzinfo is None:
        result = result.replace(tzinfo=IST)
    return result.astimezone(IST)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return parsed.astimezone(IST)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _telemetry_dir() -> Path:
    path = get_archive_dir() / "telemetry"
    path.mkdir(parents=True, exist_ok=True)
    return path


def premium_tape_path(date: str) -> Path:
    if not _DATE_RE.fullmatch(date):
        raise ValueError("date must use YYYY-MM-DD")
    return _telemetry_dir() / f"{date}.premium.jsonl"


def funnel_path(date: str) -> Path:
    if not _DATE_RE.fullmatch(date):
        raise ValueError("date must use YYYY-MM-DD")
    return _telemetry_dir() / f"{date}.funnel.jsonl"


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    line = json.dumps(payload, default=str, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()


def _contract_key(symbol: str, side: str, strike: float) -> str:
    return f"{symbol.upper()}:{side.upper()}:{strike:g}"


def _snapshot_contracts(snapshots: Mapping[str, Any]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for symbol, snap in snapshots.items():
        if not bool(getattr(snap, "dataAvailable", False)):
            continue
        for row in getattr(snap, "heatmap", None) or []:
            strike = _number(getattr(row, "strike", None))
            if strike <= 0:
                continue
            for side, ltp_name, oi_name in (
                ("CALL", "callLtp", "callOi"),
                ("PUT", "putLtp", "putOi"),
            ):
                premium = _number(getattr(row, ltp_name, None))
                if premium <= 0:
                    continue
                contracts.append({
                    "key": _contract_key(symbol, side, strike),
                    "symbol": symbol.upper(),
                    "side": side,
                    "strike": strike,
                    "premium": premium,
                    "oi": int(_number(getattr(row, oi_name, None))),
                    "spot": _number(getattr(snap, "spot", None)),
                    "atmStrike": _number(getattr(snap, "atmStrike", None)),
                })
    return contracts


def _outcome_horizons() -> list[int]:
    raw = str(get_settings().radar_outcome_horizons_seconds_csv or "")
    values: set[int] = set()
    for item in raw.split(","):
        try:
            value = int(item.strip())
        except ValueError:
            continue
        if value > 0:
            values.add(value)
    return sorted(values) or [60, 300, 900, 1800]


def _forward_outcomes(
    date: str,
    contracts: Mapping[str, Mapping[str, Any]],
    current: datetime,
) -> int:
    settings = get_settings()
    target_pct = float(settings.radar_outcome_target_pct)
    stop_pct = abs(float(settings.radar_outcome_stop_pct))
    updates: dict[str, dict[str, Any]] = {}
    for row in read_archive_entries(date):
        key = str(row.get("key") or "")
        contract = contracts.get(key)
        if not contract:
            continue
        first_seen = _parse_ts(row.get("firstSeenAt"))
        if first_seen is None or current < first_seen:
            continue
        milestones = list(row.get("milestones") or [])
        entry_premium = _number(
            (milestones[0].get("premium") if milestones else None)
            or (row.get("alert") or {}).get("premium")
        )
        premium = _number(contract.get("premium"))
        if entry_premium <= 0 or premium <= 0:
            continue
        elapsed = int((current - first_seen).total_seconds())
        move_pct = (premium - entry_premium) / entry_premium * 100.0
        outcome = dict(row.get("outcome") or {})
        outcome.setdefault("entryAt", first_seen.isoformat())
        outcome.setdefault("entryPremium", round(entry_premium, 4))
        outcome.setdefault("targetPct", target_pct)
        outcome.setdefault("stopPct", stop_pct)
        outcome["lastUpdatedAt"] = current.isoformat()
        outcome["lastPremium"] = round(premium, 4)
        outcome["lastMovePct"] = round(move_pct, 2)
        outcome["sampleCount"] = int(outcome.get("sampleCount") or 0) + 1
        outcome["mfePct"] = round(
            max(_number(outcome.get("mfePct")), move_pct),
            2,
        )
        outcome["maePct"] = round(
            min(_number(outcome.get("maePct")), move_pct),
            2,
        )
        if move_pct >= target_pct and not outcome.get("targetAt"):
            outcome["targetAt"] = current.isoformat()
        if move_pct <= -stop_pct and not outcome.get("stopAt"):
            outcome["stopAt"] = current.isoformat()

        horizons = dict(outcome.get("horizons") or {})
        for seconds in _outcome_horizons():
            label = str(seconds)
            if elapsed >= seconds and label not in horizons:
                horizons[label] = {
                    "at": current.isoformat(),
                    "elapsedSeconds": elapsed,
                    "premium": round(premium, 4),
                    "movePct": round(move_pct, 2),
                }
        outcome["horizons"] = horizons

        target_at = _parse_ts(outcome.get("targetAt"))
        stop_at = _parse_ts(outcome.get("stopAt"))
        if target_at and (not stop_at or target_at <= stop_at):
            outcome["status"] = "WINNER"
            outcome["targetBeforeStop"] = True
        elif stop_at:
            outcome["status"] = "LOSER"
            outcome["targetBeforeStop"] = False
        elif all(str(h) in horizons for h in _outcome_horizons()):
            outcome["status"] = "NO_TARGET"
            outcome["targetBeforeStop"] = None
        else:
            outcome["status"] = "TRACKING"
            outcome["targetBeforeStop"] = None
        updates[key] = outcome
    return update_archive_outcomes(date, updates, now=current)


def record_market_observations(
    snapshots: Mapping[str, Any],
    *,
    source: str,
    now: datetime | None = None,
    force: bool = False,
) -> int:
    """Persist a throttled all-strike premium sample and refresh radar outcomes."""
    settings = get_settings()
    if not settings.radar_learning_enabled:
        return 0
    current = _aware(now)
    date = current.strftime("%Y-%m-%d")
    interval = max(1, int(settings.radar_premium_tape_sample_seconds))
    contracts = _snapshot_contracts(snapshots)
    if not contracts:
        return 0
    sample_key = f"{date}:{','.join(sorted(str(symbol).upper() for symbol in snapshots))}"
    with _lock:
        previous = _last_tape_sample.get(sample_key)
        if not force and previous and (current - previous).total_seconds() < interval:
            return 0
        _append_jsonl(
            premium_tape_path(date),
            {
                "ts": current.isoformat(),
                "source": source,
                "volumeReliable": source != "ws_entry_scan",
                "contracts": contracts,
            },
        )
        _last_tape_sample[sample_key] = current
    contract_map = {str(row["key"]): row for row in contracts}
    updated = _forward_outcomes(date, contract_map, current)
    try:
        from app.services.radar_health import record_component_success

        record_component_success(
            "premiumTape",
            detail={
                "date": date,
                "contractCount": len(contracts),
                "outcomesUpdated": updated,
                "source": source,
            },
            now=current,
        )
    except Exception:
        pass
    return len(contracts)


def read_premium_tape(date: str) -> list[dict[str, Any]]:
    path = premium_tape_path(date)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _premium_series(date: str) -> dict[str, list[tuple[datetime, float]]]:
    series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for batch in read_premium_tape(date):
        ts = _parse_ts(batch.get("ts"))
        if ts is None:
            continue
        for contract in batch.get("contracts") or []:
            key = str(contract.get("key") or "")
            premium = _number(contract.get("premium"))
            if key and premium > 0:
                series[key].append((ts, premium))
    for rows in series.values():
        rows.sort(key=lambda item: item[0])
    return series


def _truth_event(
    key: str,
    samples: list[tuple[datetime, float]],
    *,
    flat_seconds: int,
    flat_range_pct: float,
    vertical_pct: float,
    lookahead_seconds: int,
) -> dict[str, Any] | None:
    if len(samples) < 5:
        return None
    base_start_index = 0
    future_right = 1
    future_max: deque[int] = deque()
    for index in range(3, len(samples) - 1):
        while (
            future_right < len(samples)
            and (samples[future_right][0] - samples[index][0]).total_seconds()
            <= lookahead_seconds
        ):
            while (
                future_max
                and samples[future_max[-1]][1] <= samples[future_right][1]
            ):
                future_max.pop()
            future_max.append(future_right)
            future_right += 1
        while future_max and future_max[0] <= index:
            future_max.popleft()
        base_end = samples[index][0]
        while (
            base_start_index < index
            and (base_end - samples[base_start_index][0]).total_seconds() > flat_seconds
        ):
            base_start_index += 1
        base_rows = samples[base_start_index: index + 1]
        if len(base_rows) < 4:
            continue
        premiums = [row[1] for row in base_rows]
        base_low = min(premiums)
        base_high = max(premiums)
        if base_low <= 0 or (base_high - base_low) / base_low * 100.0 > flat_range_pct:
            continue
        target = base_low * (1.0 + vertical_pct / 100.0)
        if not future_max or samples[future_max[0]][1] < target:
            continue
        future = [
            row for row in samples[index + 1:]
            if (row[0] - base_end).total_seconds() <= lookahead_seconds
        ]
        crossing = next((row for row in future if row[1] >= target), None)
        if crossing is None:
            continue
        peak = max(row[1] for row in future)
        return {
            "key": key,
            "baseStartAt": base_rows[0][0].isoformat(),
            "baseEndAt": base_end.isoformat(),
            "basePremium": round(base_low, 4),
            "verticalAt": crossing[0].isoformat(),
            "verticalPremium": round(crossing[1], 4),
            "peakPremium": round(peak, 4),
            "peakMovePct": round((peak - base_low) / base_low * 100.0, 2),
        }
    return None


def analyze_hindsight(
    date: str,
    *,
    flat_max_range_pct: float | None = None,
    vertical_min_move_pct: float | None = None,
    lookahead_seconds: int | None = None,
) -> dict[str, Any]:
    """Find actual FTV winners and compare them with archived radar lead time."""
    settings = get_settings()
    flat_range = (
        float(flat_max_range_pct)
        if flat_max_range_pct is not None
        else float(settings.radar_hindsight_flat_max_range_pct)
    )
    vertical = (
        float(vertical_min_move_pct)
        if vertical_min_move_pct is not None
        else float(settings.radar_hindsight_vertical_min_move_pct)
    )
    lookahead = (
        int(lookahead_seconds)
        if lookahead_seconds is not None
        else int(settings.radar_hindsight_lookahead_seconds)
    )
    series = _premium_series(date)
    archived = {
        str(row.get("key") or ""): row
        for row in read_archive_entries(date)
    }
    truths: list[dict[str, Any]] = []
    for key, samples in series.items():
        event = _truth_event(
            key,
            samples,
            flat_seconds=int(settings.radar_hindsight_flat_window_seconds),
            flat_range_pct=flat_range,
            vertical_pct=vertical,
            lookahead_seconds=lookahead,
        )
        if event is None:
            continue
        archive_row = archived.get(key)
        vertical_at = _parse_ts(event["verticalAt"])
        detection_at: datetime | None = None
        if archive_row:
            base_start = _parse_ts(event["baseStartAt"])
            candidates = [
                _parse_ts(item.get("seenAt"))
                for item in archive_row.get("milestones") or []
            ]
            candidates = [
                item for item in candidates
                if item is not None
                and (base_start is None or item >= base_start)
            ]
            detection_at = min(candidates) if candidates else None
            if detection_at is None:
                first_seen = _parse_ts(archive_row.get("firstSeenAt"))
                if first_seen and (base_start is None or first_seen >= base_start):
                    detection_at = first_seen
        if detection_at and vertical_at:
            lead = (vertical_at - detection_at).total_seconds()
            capture = "EARLY" if lead >= 0 else "LATE"
        else:
            lead = None
            capture = "MISSED"
        event.update({
            "capture": capture,
            "detectionAt": detection_at.isoformat() if detection_at else None,
            "leadSeconds": round(lead, 1) if lead is not None else None,
        })
        truths.append(event)

    counts = Counter(event["capture"] for event in truths)
    truth_keys = {event["key"] for event in truths}
    archived_keys = set(archived)
    detected_truths = counts["EARLY"] + counts["LATE"]
    by_side: dict[str, dict[str, int]] = {}
    by_symbol: dict[str, dict[str, int]] = {}
    for event in truths:
        parts = event["key"].split(":")
        symbol = parts[0] if parts else ""
        side = parts[1] if len(parts) > 1 else ""
        for bucket, label in ((by_symbol, symbol), (by_side, side)):
            row = bucket.setdefault(label, {"truth": 0, "early": 0, "late": 0, "missed": 0})
            row["truth"] += 1
            row[event["capture"].lower()] += 1

    outcomes = [dict(row.get("outcome") or {}) for row in archived.values()]
    outcome_counts = Counter(str(row.get("status") or "UNRESOLVED") for row in outcomes)
    return {
        "date": date,
        "generatedAt": _now().isoformat(),
        "thresholds": {
            "flatWindowSeconds": int(settings.radar_hindsight_flat_window_seconds),
            "flatMaxRangePct": flat_range,
            "verticalMinMovePct": vertical,
            "lookaheadSeconds": lookahead,
        },
        "truthCount": len(truths),
        "earlyDetected": counts["EARLY"],
        "lateDetected": counts["LATE"],
        "missed": counts["MISSED"],
        "recallPct": round(detected_truths / len(truths) * 100.0, 1) if truths else 0.0,
        "earlyRecallPct": round(counts["EARLY"] / len(truths) * 100.0, 1) if truths else 0.0,
        "precisionPct": round(len(truth_keys & archived_keys) / len(archived_keys) * 100.0, 1)
        if archived_keys else 0.0,
        "falseAlertCount": len(archived_keys - truth_keys),
        "archivedRadarCount": len(archived_keys),
        "outcomes": dict(outcome_counts),
        "bySymbol": by_symbol,
        "bySide": by_side,
        "events": sorted(
            truths,
            key=lambda row: (row["capture"] == "MISSED", -_number(row["peakMovePct"])),
        ),
    }


def record_funnel_state(
    snapshots: Mapping[str, Any],
    skipped: list[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> int:
    """Persist deduplicated gate blockers for radar-to-order funnel review."""
    settings = get_settings()
    if not settings.radar_learning_enabled:
        return 0
    current = _aware(now)
    date = current.strftime("%Y-%m-%d")
    dedupe_seconds = max(1, int(settings.radar_funnel_dedupe_seconds))
    written = 0
    with _lock:
        for raw in skipped:
            row = dict(raw)
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            side = str(row.get("side") or "").upper()
            strike = _number(row.get("strike"))
            if symbol != "SESSION" and (not side or strike <= 0):
                snap = snapshots.get(symbol)
                alerts = getattr(snap, "explosionAlerts", None) or []
                if alerts:
                    side = side or str(alerts[0].get("side") or "").upper()
                    strike = strike or _number(alerts[0].get("strike"))
            key = (
                "SESSION"
                if symbol == "SESSION"
                else _contract_key(symbol, side, strike)
            )
            reason = str(row.get("reason") or "unknown")
            signature = f"{date}:{key}:{reason}"
            previous = _last_funnel_event.get(signature)
            if previous and (current - previous).total_seconds() < dedupe_seconds:
                continue
            _append_jsonl(
                funnel_path(date),
                {
                    "ts": current.isoformat(),
                    "key": key,
                    "symbol": symbol,
                    "side": side or None,
                    "strike": strike or None,
                    "stage": "SESSION_BLOCK" if symbol == "SESSION" else "GATE_BLOCK",
                    "reason": reason,
                    "message": row.get("message"),
                    "mode": row.get("mode"),
                    "score": row.get("score"),
                    "tier": row.get("tier"),
                },
            )
            _last_funnel_event[signature] = current
            written += 1
    return written


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def build_funnel_report(date: str) -> dict[str, Any]:
    from app.services import trade_store

    radars = read_archive_entries(date)
    blocked_rows = _read_jsonl(funnel_path(date))
    trades = list((trade_store.get_day_detail(date) or {}).get("trades") or [])
    blockers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in blocked_rows:
        blockers[str(row.get("key") or "")].append(row)
    trades_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        symbol = str(trade.get("symbol") or "").upper()
        side = str(trade.get("side") or "").upper()
        strike = _number(trade.get("strike"))
        if symbol and side and strike > 0:
            trades_by_key[_contract_key(symbol, side, strike)].append(trade)

    rows: list[dict[str, Any]] = []
    for radar in radars:
        key = str(radar.get("key") or "")
        matched_trades = trades_by_key.get(key) or []
        matched_blocks = blockers.get(key) or []
        closed = [trade for trade in matched_trades if str(trade.get("status")) == "CLOSED"]
        rows.append({
            "key": key,
            "detectedAt": radar.get("firstSeenAt"),
            "bestTier": radar.get("tier"),
            "blocked": bool(matched_blocks),
            "blockers": sorted({
                str(item.get("reason") or "unknown")
                for item in matched_blocks
            }),
            "entered": bool(matched_trades),
            "tradeCount": len(matched_trades),
            "closed": bool(closed),
            "pnlInr": round(sum(_number(item.get("pnlInr")) for item in closed), 2),
            "tradeOutcome": (
                "WIN" if sum(_number(item.get("pnlInr")) for item in closed) > 0
                else ("LOSS" if closed else None)
            ),
            "radarOutcome": radar.get("outcome") or {},
        })
    entered = sum(1 for row in rows if row["entered"])
    blocked = sum(1 for row in rows if row["blocked"])
    wins = sum(1 for row in rows if row["tradeOutcome"] == "WIN")
    return {
        "date": date,
        "detected": len(rows),
        "blocked": blocked,
        "entered": entered,
        "closedWins": wins,
        "detectionToEntryPct": round(entered / len(rows) * 100.0, 1) if rows else 0.0,
        "entryWinRatePct": round(wins / entered * 100.0, 1) if entered else 0.0,
        "sessionBlocks": [
            row for row in blocked_rows if row.get("key") == "SESSION"
        ],
        "rows": rows,
    }


def backup_archive(path: Path) -> dict[str, Any]:
    """Copy a finalized archive to a mounted backup dir and/or S3."""
    settings = get_settings()
    destinations: list[str] = []
    errors: list[str] = []
    backup_dir = str(settings.radar_backup_dir or "").strip()
    if backup_dir:
        try:
            target_dir = Path(backup_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / path.name
            shutil.copy2(path, target)
            destinations.append(str(target))
        except OSError as exc:
            errors.append(f"directory: {exc}")

    bucket = str(settings.radar_backup_s3_bucket or "").strip()
    if bucket:
        prefix = str(settings.radar_backup_s3_prefix or "").strip("/")
        key = f"{prefix}/{path.name}" if prefix else path.name
        try:
            import boto3

            boto3.client("s3").upload_file(str(path), bucket, key)
            destinations.append(f"s3://{bucket}/{key}")
        except Exception as exc:
            errors.append(f"s3: {exc}")

    try:
        from app.services.radar_health import record_backup

        record_backup(
            destination=", ".join(destinations) or "not_configured",
            file_name=path.name,
            success=not errors,
            error="; ".join(errors) or None,
        )
    except Exception:
        pass
    return {
        "success": not errors,
        "configured": bool(backup_dir or bucket),
        "destinations": destinations,
        "errors": errors,
    }


def finalize_daily_review(date: str) -> dict[str, Any]:
    """Bundle tape, scorecard, funnel, and replay inputs into the canonical daily ZIP."""
    scorecard = analyze_hindsight(date)
    funnel = build_funnel_report(date)
    artifacts: dict[str, bytes | str] = {
        "scorecard.json": json.dumps(scorecard, indent=2),
        "funnel.json": json.dumps(funnel, indent=2),
    }
    tape = premium_tape_path(date)
    if tape.exists():
        artifacts["premium_tape.jsonl"] = tape.read_bytes()
    funnel_file = funnel_path(date)
    if funnel_file.exists():
        artifacts["funnel_events.jsonl"] = funnel_file.read_bytes()
    path = add_archive_artifacts(date, artifacts)
    backup = backup_archive(path)
    try:
        from app.services.radar_health import record_component_success

        record_component_success(
            "dailyRadarReview",
            detail={
                "date": date,
                "truthCount": scorecard["truthCount"],
                "recallPct": scorecard["recallPct"],
                "backup": backup,
            },
        )
    except Exception:
        pass
    return {
        "date": date,
        "archive": str(path),
        "scorecard": scorecard,
        "funnel": funnel,
        "backup": backup,
    }


def finalize_pending_reviews(
    *,
    now: datetime | None = None,
    limit: int = 7,
) -> list[dict[str, Any]]:
    """Crash recovery: finalize recent prior-session ZIPs missing their scorecard."""
    current_date = _aware(now).strftime("%Y-%m-%d")
    pending: list[str] = []
    for path in sorted(get_archive_dir().glob("radar-*.zip"), reverse=True):
        date = path.stem.removeprefix("radar-")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or date >= current_date:
            continue
        try:
            with zipfile.ZipFile(path, "r") as archive:
                if "scorecard.json" in archive.namelist():
                    continue
        except (OSError, zipfile.BadZipFile):
            continue
        pending.append(date)
        if len(pending) >= max(1, limit):
            break
    return [finalize_daily_review(date) for date in reversed(pending)]


def reset_learning_state_for_tests() -> None:
    with _lock:
        _last_tape_sample.clear()
        _last_funnel_event.clear()
