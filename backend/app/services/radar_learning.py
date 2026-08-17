"""Premium tape, forward outcomes, hindsight scoring, funnel analytics, and backups."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping
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
_finalize_lock = threading.Lock()
_detector_replay_lock = threading.Lock()
_last_tape_sample: dict[str, datetime] = {}
_last_pipeline_event: dict[str, datetime] = {}
_last_funnel_event: dict[str, datetime] = {}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RadarOperationBusyError(RuntimeError):
    """Raised instead of queueing duplicate heavy radar operations."""


@contextmanager
def _exclusive_operation(lock: threading.Lock, operation: str) -> Iterator[None]:
    if not lock.acquire(blocking=False):
        raise RadarOperationBusyError(f"{operation} is already running")
    try:
        yield
    finally:
        lock.release()


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


def pipeline_history_path(date: str) -> Path:
    if not _DATE_RE.fullmatch(date):
        raise ValueError("date must use YYYY-MM-DD")
    return _telemetry_dir() / f"{date}.pipeline.jsonl"


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
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
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    line = json.dumps(payload, default=str, separators=(",", ":"))
    with _file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _read_bytes_locked(path: Path) -> bytes:
    if not path.exists():
        return b""
    with _file_lock(path):
        return path.read_bytes()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with _file_lock(path):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    return out


def record_pipeline_event(
    event: str,
    *,
    source: str,
    detail: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    throttle_key: str | None = None,
    throttle_seconds: float = 0.0,
) -> bool:
    """Persist non-secret service/data availability evidence across restarts."""
    current = _aware(now)
    date = current.strftime("%Y-%m-%d")
    key = throttle_key or ""
    with _lock:
        previous = _last_pipeline_event.get(key) if key else None
        if (
            key
            and previous
            and (current - previous).total_seconds() < max(0.0, throttle_seconds)
        ):
            return False
        _append_jsonl(
            pipeline_history_path(date),
            {
                "ts": current.isoformat(),
                "event": str(event).upper(),
                "source": source,
                "detail": dict(detail or {}),
            },
        )
        if key:
            _last_pipeline_event[key] = current
    return True


def read_pipeline_history(date: str) -> list[dict[str, Any]]:
    return _read_jsonl(pipeline_history_path(date))


def pipeline_history_summary(date: str) -> dict[str, Any]:
    rows = read_pipeline_history(date)
    counts = Counter(str(row.get("event") or "UNKNOWN") for row in rows)
    return {
        "date": date,
        "eventCount": len(rows),
        "firstEventAt": rows[0].get("ts") if rows else None,
        "lastEventAt": rows[-1].get("ts") if rows else None,
        "byEvent": dict(counts),
        "recent": rows[-20:],
    }


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
                    "instrumentKey": (
                        getattr(row, "callInstrumentKey", None)
                        if side == "CALL"
                        else getattr(row, "putInstrumentKey", None)
                    ),
                })
    return contracts


def _append_archived_tick_contracts(
    date: str,
    contracts: list[dict[str, Any]],
    *,
    max_age_seconds: float,
) -> None:
    """Keep tracking archived strikes after they rotate out of the live heatmap."""
    from app.services.tick_store import get_ltp

    current_keys = {str(row.get("key") or "") for row in contracts}
    for archived in read_archive_entries(date):
        key = str(archived.get("key") or "")
        if not key or key in current_keys:
            continue
        alert = dict(archived.get("alert") or {})
        instrument_key = str(alert.get("instrumentKey") or "")
        if not instrument_key:
            continue
        premium = get_ltp(instrument_key, max_age_seconds=max_age_seconds)
        if premium is None or premium <= 0:
            continue
        context = dict(archived.get("context") or {})
        contracts.append({
            "key": key,
            "symbol": str(archived.get("symbol") or "").upper(),
            "side": str(archived.get("side") or "").upper(),
            "strike": _number(archived.get("strike")),
            "premium": float(premium),
            "oi": 0,
            "spot": _number(context.get("spot")),
            "atmStrike": _number(context.get("atmStrike")),
            "instrumentKey": instrument_key,
            "archivedTickFallback": True,
        })
        current_keys.add(key)


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
    _append_archived_tick_contracts(
        date,
        contracts,
        max_age_seconds=max(5.0, interval * 2.0),
    )
    if not contracts:
        record_pipeline_event(
            "PREMIUM_SAMPLE_EMPTY",
            source=source,
            detail={
                "symbols": sorted(str(symbol).upper() for symbol in snapshots),
                "dataAvailableSymbols": sorted(
                    str(symbol).upper()
                    for symbol, snap in snapshots.items()
                    if bool(getattr(snap, "dataAvailable", False))
                ),
            },
            now=current,
            throttle_key=f"premium-empty:{source}",
            throttle_seconds=interval,
        )
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
    record_pipeline_event(
        "PREMIUM_SAMPLE_WRITTEN",
        source=source,
        detail={
            "symbols": sorted(str(symbol).upper() for symbol in snapshots),
            "contractCount": len(contracts),
        },
        now=current,
        throttle_key=f"premium-written:{source}",
        throttle_seconds=interval,
    )
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
    return _read_jsonl(premium_tape_path(date))


def restore_local_base_history(*, now: datetime | None = None) -> dict[str, Any]:
    """Restore only medium-horizon bases; live ticks must still confirm a trigger."""
    current = _aware(now)
    date = current.strftime("%Y-%m-%d")
    cutoff = current - timedelta(seconds=2100)
    batches = read_premium_tape(date)
    restored = 0
    keys: set[str] = set()
    from app.engines.explosion_detector import (
        _open_key,
        _record_local_base,
        _roll_session,
    )
    from app.models.schemas import Side

    # Initialize the detector's session before hydrating it. Otherwise its first live
    # tick sees an unset session date and clears the bases restored moments earlier.
    _roll_session(current)
    for batch in batches:
        ts = _parse_ts(batch.get("ts"))
        if ts is None or ts < cutoff or ts > current + timedelta(minutes=1):
            continue
        for contract in batch.get("contracts") or []:
            symbol = str(contract.get("symbol") or "").upper()
            side = str(contract.get("side") or "").upper()
            strike = _number(contract.get("strike"))
            premium = _number(contract.get("premium"))
            if not symbol or side not in {"CALL", "PUT"} or strike <= 0 or premium <= 0:
                continue
            full_key = _open_key(symbol, strike, Side(side))
            _record_local_base(full_key, ts, premium)
            keys.add(full_key)
            restored += 1
    return {
        "date": date,
        "sampleCount": restored,
        "contractCount": len(keys),
        "cutoff": cutoff.isoformat(),
    }


def _premium_series(
    date: str,
) -> tuple[
    dict[str, list[tuple[datetime, float]]],
    dict[str, dict[datetime, dict[str, Any]]],
]:
    series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    observations: dict[str, dict[datetime, dict[str, Any]]] = defaultdict(dict)
    for batch in read_premium_tape(date):
        ts = _parse_ts(batch.get("ts"))
        if ts is None:
            continue
        for contract in batch.get("contracts") or []:
            key = str(contract.get("key") or "")
            premium = _number(contract.get("premium"))
            if key and premium > 0:
                series[key].append((ts, premium))
                observations[key][ts] = dict(contract)
    for rows in series.values():
        rows.sort(key=lambda item: item[0])
    return series, observations


def _hindsight_policy_eligibility(
    event: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
    settings: Any,
) -> tuple[bool, str, dict[str, Any]]:
    """Apply scanner premium/moneyness policy at the hindsight event's base."""
    contract = dict(observation or {})
    key_parts = str(event.get("key") or "").split(":")
    symbol = str(contract.get("symbol") or (key_parts[0] if key_parts else "")).upper()
    side = str(contract.get("side") or (key_parts[1] if len(key_parts) > 1 else "")).upper()
    strike = _number(
        contract.get("strike")
        or (key_parts[2] if len(key_parts) > 2 else 0)
    )
    premium = _number(event.get("basePremium"))
    spot = _number(contract.get("spot"))
    atm = _number(contract.get("atmStrike"))
    policy = {
        "symbol": symbol,
        "side": side,
        "strike": strike,
        "basePremium": premium,
        "spot": spot,
        "atmStrike": atm,
    }

    minimum = float(getattr(settings, "min_option_premium_inr", 18.0) or 18.0)
    maximum = max(
        float(getattr(settings, "max_option_premium_inr", 300.0) or 300.0),
        float(getattr(settings, "explosion_max_premium_inr", 650.0) or 650.0),
    )
    peak_move = _number(event.get("peakMovePct"))
    cheap_minimum = float(
        getattr(settings, "explosion_cheap_rip_min_premium_inr", 12.0) or 12.0
    )
    cheap_peak = float(
        getattr(settings, "explosion_cheap_rip_min_peak_pct", 28.0) or 28.0
    )
    if peak_move >= cheap_peak:
        minimum = min(minimum, cheap_minimum)
        maximum = max(
            maximum,
            float(getattr(settings, "explosion_ict_max_premium_inr", 0.0) or 0.0),
        )
    policy["premiumBand"] = {"min": minimum, "max": maximum}
    if premium < minimum:
        return False, "premium_below_min", policy
    if premium > maximum:
        return False, "premium_above_max", policy
    if side not in {"CALL", "PUT"} or strike <= 0 or spot <= 0 or atm <= 0:
        return False, "missing_moneyness_context", policy

    from app.engines.moneyness import (
        classify_moneyness,
        steps_from_atm,
        strike_step,
    )

    money = classify_moneyness(side, strike, spot, symbol=symbol, atm=atm)
    steps = abs(steps_from_atm(strike, spot, symbol, atm=atm))
    policy.update({"moneyness": money, "strikeStepsFromAtm": steps})
    if money != "OTM" or not bool(
        getattr(settings, "explosion_scan_atm_itm_only", True)
    ):
        return True, "eligible", policy

    step = strike_step(symbol)
    tolerance = float(
        getattr(settings, "moneyness_atm_tolerance_points", step) or step
    )
    shallow_steps = int(
        getattr(settings, "explosion_shallow_otm_history_steps", 1) or 1
    )
    policy["maxShallowOtmDistance"] = tolerance + step * max(0, shallow_steps)
    if abs(strike - atm) > policy["maxShallowOtmDistance"]:
        return False, "deep_otm", policy
    return True, "eligible_shallow_otm_history", policy


def _maximum_tree(values: list[float]) -> tuple[list[float], int]:
    size = 1
    while size < len(values):
        size *= 2
    tree = [float("-inf")] * (size * 2)
    tree[size:size + len(values)] = values
    for index in range(size - 1, 0, -1):
        tree[index] = max(tree[index * 2], tree[index * 2 + 1])
    return tree, size


def _range_maximum(
    tree: list[float],
    size: int,
    left: int,
    right: int,
) -> float:
    """Return the inclusive range maximum in O(log n)."""
    left += size
    right += size
    maximum = float("-inf")
    while left <= right:
        if left % 2 == 1:
            maximum = max(maximum, tree[left])
            left += 1
        if right % 2 == 0:
            maximum = max(maximum, tree[right])
            right -= 1
        left //= 2
        right //= 2
    return maximum


def _first_at_least(
    tree: list[float],
    size: int,
    left: int,
    right: int,
    target: float,
) -> int | None:
    """Find the first inclusive range index reaching target in O(log n)."""
    def search(node: int, node_left: int, node_right: int) -> int | None:
        if node_right < left or node_left > right or tree[node] < target:
            return None
        if node_left == node_right:
            return node_left
        midpoint = (node_left + node_right) // 2
        found = search(node * 2, node_left, midpoint)
        if found is not None:
            return found
        return search(node * 2 + 1, midpoint + 1, node_right)

    return search(1, 0, size - 1)


def _truth_events(
    key: str,
    samples: list[tuple[datetime, float]],
    *,
    flat_seconds: int,
    flat_range_pct: float,
    vertical_pct: float,
    lookahead_seconds: int,
) -> list[dict[str, Any]]:
    if len(samples) < 5:
        return []
    events: list[dict[str, Any]] = []
    suppress_until: datetime | None = None
    base_start_index = 0
    future_right = 1
    premiums_all = [premium for _, premium in samples]
    maximum_tree, maximum_tree_size = _maximum_tree(premiums_all)
    for index in range(3, len(samples) - 1):
        future_right = max(future_right, index + 1)
        while (
            future_right < len(samples)
            and (samples[future_right][0] - samples[index][0]).total_seconds()
            <= lookahead_seconds
        ):
            future_right += 1
        base_end = samples[index][0]
        if suppress_until and base_end <= suppress_until:
            continue
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
        future_last = future_right - 1
        if (
            future_last <= index
            or _range_maximum(
                maximum_tree,
                maximum_tree_size,
                index + 1,
                future_last,
            ) < target
        ):
            continue
        crossing_index = _first_at_least(
            maximum_tree,
            maximum_tree_size,
            index + 1,
            future_last,
            target,
        )
        if crossing_index is None:
            continue
        crossing = samples[crossing_index]
        peak = _range_maximum(
            maximum_tree,
            maximum_tree_size,
            index + 1,
            future_last,
        )
        event = {
            "key": key,
            "baseStartAt": base_rows[0][0].isoformat(),
            "baseEndAt": base_end.isoformat(),
            "basePremium": round(base_low, 4),
            "verticalAt": crossing[0].isoformat(),
            "verticalPremium": round(crossing[1], 4),
            "baseToVerticalSeconds": round(
                (crossing[0] - base_end).total_seconds(),
                1,
            ),
            "peakPremium": round(peak, 4),
            "peakMovePct": round((peak - base_low) / base_low * 100.0, 2),
        }
        events.append(event)
        suppress_until = crossing[0] + timedelta(seconds=flat_seconds)
    return events


def _archive_was_tradeable(row: Mapping[str, Any]) -> bool:
    """Whether retained causal radar evidence ever exposed this contract to selection."""
    alert = row.get("alert")
    if isinstance(alert, Mapping) and bool(alert.get("tradeable")):
        return True
    return any(
        bool(item.get("tradeable"))
        for item in (row.get("milestones") or [])
        if isinstance(item, Mapping)
    )


def _causal_selected_keys(
    date: str,
    archived: Mapping[str, Mapping[str, Any]],
) -> tuple[set[str], int]:
    """Return archived contracts selected after their first retained detection."""
    selected: set[str] = set()
    event_count = 0
    for event in _read_jsonl(funnel_path(date)):
        if str(event.get("event") or "").upper() != "SELECTED":
            continue
        event_count += 1
        key = str(event.get("key") or "")
        archive_row = archived.get(key)
        if archive_row is None:
            continue
        selected_at = _parse_ts(event.get("ts"))
        first_seen_at = _parse_ts(archive_row.get("firstSeenAt"))
        if first_seen_at is not None and (
            selected_at is None or selected_at < first_seen_at
        ):
            continue
        selected.add(key)
    return selected, event_count


def _precision_pct(candidate_keys: set[str], truth_keys: set[str]) -> float:
    return (
        round(len(candidate_keys & truth_keys) / len(candidate_keys) * 100.0, 1)
        if candidate_keys
        else 0.0
    )


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
    series, observations = _premium_series(date)
    archived = {
        str(row.get("key") or ""): row
        for row in read_archive_entries(date)
    }
    truths: list[dict[str, Any]] = []
    excluded_truths: list[dict[str, Any]] = []
    raw_truth_count = 0
    for key, samples in series.items():
        events = _truth_events(
            key,
            samples,
            flat_seconds=int(settings.radar_hindsight_flat_window_seconds),
            flat_range_pct=flat_range,
            vertical_pct=vertical,
            lookahead_seconds=lookahead,
        )
        for event in events:
            raw_truth_count += 1
            base_end = _parse_ts(event.get("baseEndAt"))
            observation = (
                observations.get(key, {}).get(base_end)
                if base_end is not None
                else None
            )
            eligible, eligibility_reason, policy = _hindsight_policy_eligibility(
                event,
                observation,
                settings,
            )
            event["policyEligible"] = eligible
            event["policyEligibilityReason"] = eligibility_reason
            event["policy"] = policy
            if not eligible:
                event["capture"] = "EXCLUDED"
                excluded_truths.append(event)
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
    executable_keys = {
        key for key, row in archived.items()
        if _archive_was_tradeable(row)
    }
    selected_keys, selection_event_count = _causal_selected_keys(date, archived)
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
            "policyScope": "explosion premium band plus ATM/ITM and shallow-OTM history",
        },
        "rawTruthCount": raw_truth_count,
        "excludedTruthCount": len(excluded_truths),
        "excludedByReason": dict(Counter(
            event["policyEligibilityReason"] for event in excluded_truths
        )),
        "truthCount": len(truths),
        "earlyDetected": counts["EARLY"],
        "lateDetected": counts["LATE"],
        "missed": counts["MISSED"],
        "recallPct": round(detected_truths / len(truths) * 100.0, 1) if truths else 0.0,
        "earlyRecallPct": round(counts["EARLY"] / len(truths) * 100.0, 1) if truths else 0.0,
        # Compatibility aliases retain the original all-archive visibility scope.
        "precisionPct": _precision_pct(archived_keys, truth_keys),
        "falseAlertCount": len(archived_keys - truth_keys),
        "archivedRadarCount": len(archived_keys),
        "radarPrecisionPct": _precision_pct(archived_keys, truth_keys),
        "radarFalseAlertCount": len(archived_keys - truth_keys),
        "radarAlertCount": len(archived_keys),
        "executablePrecisionPct": _precision_pct(executable_keys, truth_keys),
        "executableFalseAlertCount": len(executable_keys - truth_keys),
        "executableRadarCount": len(executable_keys),
        "executableDefinition": (
            "contract had tradeable=true in its retained best alert or causal milestone"
        ),
        "visibilityOnlyCount": len(archived_keys - executable_keys),
        "selectedPrecisionPct": _precision_pct(selected_keys, truth_keys),
        "selectedFalseAlertCount": len(selected_keys - truth_keys),
        "selectedRadarCount": len(selected_keys),
        "selectionEventCount": selection_event_count,
        "selectedTelemetryAvailable": selection_event_count > 0,
        "precisionUnit": "unique option contract",
        "outcomes": dict(outcome_counts),
        "bySymbol": by_symbol,
        "bySide": by_side,
        "events": sorted(
            truths,
            key=lambda row: (row["capture"] == "MISSED", -_number(row["peakMovePct"])),
        ),
        "excludedEvents": sorted(
            excluded_truths,
            key=lambda row: -_number(row["peakMovePct"]),
        ),
    }


def record_funnel_state(
    snapshots: Mapping[str, Any],
    skipped: list[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    cycle_id: str | None = None,
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
                    "event": "GATED",
                    "symbol": symbol,
                    "side": side or None,
                    "strike": strike or None,
                    "stage": "SESSION_BLOCK" if symbol == "SESSION" else "GATE_BLOCK",
                    "cycleId": cycle_id,
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


def record_funnel_event(
    event: Mapping[str, Any],
    *,
    now: datetime | None = None,
    date: str | None = None,
) -> None:
    """Append one exact funnel transition such as DETECTED/SELECTED/ENTERED/CLOSED."""
    current = _aware(now)
    target_date = date or current.strftime("%Y-%m-%d")
    payload = {
        "ts": current.isoformat(),
        **dict(event),
    }
    _append_jsonl(funnel_path(target_date), payload)


def build_funnel_report(date: str) -> dict[str, Any]:
    from app.services import trade_store

    radars = read_archive_entries(date)
    blocked_rows = _read_jsonl(funnel_path(date))
    trades = list((trade_store.get_day_detail(date) or {}).get("trades") or [])
    blockers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    events_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in blocked_rows:
        key = str(row.get("key") or "")
        events_by_key[key].append(row)
        if row.get("event") == "GATED" or str(row.get("stage") or "").endswith("BLOCK"):
            blockers[key].append(row)
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
        detected_at = _parse_ts(radar.get("firstSeenAt"))

        def is_causal(row: Mapping[str, Any], timestamp_key: str) -> bool:
            if detected_at is None:
                return True
            timestamp = _parse_ts(row.get(timestamp_key))
            return timestamp is not None and timestamp >= detected_at

        matched_trades = [
            trade for trade in trades_by_key.get(key) or []
            if is_causal(trade, "openedAt")
        ]
        matched_blocks = [
            item for item in blockers.get(key) or []
            if is_causal(item, "ts")
        ]
        matched_events = [
            item for item in events_by_key.get(key) or []
            if is_causal(item, "ts")
        ]
        closed = [trade for trade in matched_trades if str(trade.get("status")) == "CLOSED"]
        rows.append({
            "key": key,
            "detectedAt": radar.get("firstSeenAt"),
            "bestTier": radar.get("tier"),
            "blocked": bool(matched_blocks),
            "selected": any(item.get("event") == "SELECTED" for item in matched_events),
            "orderRejected": any(
                item.get("event") == "ORDER_REJECTED" for item in matched_events
            ),
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
            "timeline": matched_events,
        })
    entered = sum(1 for row in rows if row["entered"])
    blocked = sum(1 for row in rows if row["blocked"])
    selected = sum(1 for row in rows if row["selected"])
    order_rejected = sum(1 for row in rows if row["orderRejected"])
    wins = sum(1 for row in rows if row["tradeOutcome"] == "WIN")
    return {
        "date": date,
        "detected": len(rows),
        "blocked": blocked,
        "selected": selected,
        "orderRejected": order_rejected,
        "entered": entered,
        "closedWins": wins,
        "detectionToEntryPct": round(entered / len(rows) * 100.0, 1) if rows else 0.0,
        "detectionToSelectionPct": round(selected / len(rows) * 100.0, 1)
        if rows else 0.0,
        "selectionToEntryPct": round(entered / selected * 100.0, 1)
        if selected else 0.0,
        "entryWinRatePct": round(wins / entered * 100.0, 1) if entered else 0.0,
        "sessionBlocks": [
            row for row in blocked_rows if row.get("key") == "SESSION"
        ],
        "rows": rows,
    }


def backup_archive(path: Path) -> dict[str, Any]:
    """Copy a finalized archive to a mounted backup dir and/or S3."""
    settings = get_settings()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    destinations: list[str] = []
    errors: list[str] = []
    attempts = 0
    backup_dir = str(settings.radar_backup_dir or "").strip()
    if backup_dir:
        try:
            target_dir = Path(backup_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / path.name
            target_matches = (
                target.exists()
                and target.stat().st_size == path.stat().st_size
                and hashlib.sha256(target.read_bytes()).hexdigest() == digest
            )
            if not target_matches:
                shutil.copy2(path, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise OSError("Local backup checksum verification failed")
            destinations.append(str(target))
        except OSError as exc:
            errors.append(f"directory: {exc}")

    bucket = str(settings.radar_backup_s3_bucket or "").strip()
    if bucket:
        prefix = str(settings.radar_backup_s3_prefix or "").strip("/")
        key = f"{prefix}/{path.name}" if prefix else path.name
        try:
            import boto3

            client = boto3.client("s3")
            remote = f"s3://{bucket}/{key}"
            verify_head = bool(
                getattr(settings, "radar_backup_verify_head", True)
            )
            already_uploaded = False
            if verify_head and hasattr(client, "head_object"):
                try:
                    head = client.head_object(Bucket=bucket, Key=key)
                    metadata = {
                        str(name).lower(): str(value)
                        for name, value in (head.get("Metadata") or {}).items()
                    }
                    already_uploaded = (
                        int(head.get("ContentLength") or -1) == path.stat().st_size
                        and metadata.get("sha256") == digest
                    )
                except Exception:
                    already_uploaded = False
            if already_uploaded:
                destinations.append(remote)
            else:
                retry_max = max(
                    1,
                    int(getattr(settings, "radar_backup_retry_max", 3) or 3),
                )
                retry_base = max(
                    0.0,
                    float(
                        getattr(settings, "radar_backup_retry_base_seconds", 1.0)
                        or 0.0
                    ),
                )
                last_error: Exception | None = None
                for attempt in range(1, retry_max + 1):
                    attempts = attempt
                    try:
                        client.upload_file(
                            str(path),
                            bucket,
                            key,
                            ExtraArgs={"Metadata": {"sha256": digest}},
                        )
                        if verify_head and hasattr(client, "head_object"):
                            head = client.head_object(Bucket=bucket, Key=key)
                            metadata = {
                                str(name).lower(): str(value)
                                for name, value in (head.get("Metadata") or {}).items()
                            }
                            if (
                                int(head.get("ContentLength") or -1) != path.stat().st_size
                                or metadata.get("sha256") != digest
                            ):
                                raise OSError("S3 upload checksum verification failed")
                        destinations.append(remote)
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc
                        if attempt < retry_max and retry_base > 0:
                            time.sleep(retry_base * (2 ** (attempt - 1)))
                if last_error is not None:
                    raise last_error
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
        "attempts": attempts,
        "sha256": digest,
    }


def _prune_learning_files(now: datetime | None = None) -> None:
    current = _aware(now)
    retention_days = max(1, int(get_settings().radar_archive_retention_days))
    cutoff = current.date() - timedelta(days=retention_days)
    for path in _telemetry_dir().glob("*.jsonl"):
        date = path.name.split(".", 1)[0]
        try:
            parsed = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if parsed < cutoff:
            path.unlink(missing_ok=True)
            path.with_suffix(path.suffix + ".lock").unlink(missing_ok=True)


def _backup_status_path(date: str) -> Path:
    return archive_path(date).with_suffix(".backup.json")


def _write_backup_status(date: str, status: Mapping[str, Any]) -> None:
    path = _backup_status_path(date)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(dict(status), indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def radar_review_is_current(date: str) -> bool:
    path = archive_path(date)
    status_path = _backup_status_path(date)
    if not path.exists() or not status_path.exists():
        return False
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return bool(status.get("success") and status.get("sha256") == digest)
    except (OSError, json.JSONDecodeError):
        return False


def finalize_daily_review(date: str) -> dict[str, Any]:
    with _exclusive_operation(_finalize_lock, "Radar finalization"):
        return _finalize_daily_review_unlocked(date)


def _finalize_daily_review_unlocked(date: str) -> dict[str, Any]:
    """Bundle tape, scorecard, funnel, and replay inputs into the canonical daily ZIP."""
    scorecard = analyze_hindsight(date)
    funnel = build_funnel_report(date)
    artifacts: dict[str, bytes | str] = {
        "scorecard.json": json.dumps(scorecard, indent=2),
        "funnel.json": json.dumps(funnel, indent=2),
    }
    if bool(getattr(get_settings(), "ftv_premium_calibration_enabled", False)):
        try:
            from app.engines.ftv_premium_calibration import (
                build_and_persist_premium_calibration,
            )

            calibration = build_and_persist_premium_calibration(force=True)
            artifacts["ftv_premium_calibration.json"] = json.dumps(
                calibration, indent=2,
            )
        except Exception as exc:
            logger.warning("FTV premium calibration refresh failed: %s", exc)
    tape = premium_tape_path(date)
    if tape.exists():
        artifacts["premium_tape.jsonl"] = _read_bytes_locked(tape)
    pipeline_file = pipeline_history_path(date)
    if pipeline_file.exists():
        artifacts["pipeline_history.jsonl"] = _read_bytes_locked(pipeline_file)
    funnel_file = funnel_path(date)
    if funnel_file.exists():
        artifacts["funnel_events.jsonl"] = _read_bytes_locked(funnel_file)
    path = add_archive_artifacts(date, artifacts)
    backup = backup_archive(path)
    _write_backup_status(
        date,
        {
            **backup,
            "date": date,
            "archive": path.name,
            "recordedAt": _now().isoformat(),
        },
    )
    _prune_learning_files()
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
    limit: int = 365,
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
                archive.testzip()
            if radar_review_is_current(date):
                continue
        except (OSError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            try:
                from app.services.radar_health import record_component_error

                record_component_error("dailyRadarRecovery", exc)
            except Exception:
                pass
            continue
        pending.append(date)
        if len(pending) >= max(1, limit):
            break
    return [finalize_daily_review(date) for date in reversed(pending)]


def run_detector_replay_isolated(date: str) -> dict[str, Any]:
    with _exclusive_operation(_detector_replay_lock, "Detector replay"):
        return _run_detector_replay_isolated_unlocked(date)


def _run_detector_replay_isolated_unlocked(date: str) -> dict[str, Any]:
    """Replay via a subprocess so production detector globals cannot affect live state."""
    premium_tape_path(date)  # strict date validation
    backend_dir = Path(__file__).resolve().parents[2]
    script = backend_dir / "scripts" / "replay_radar_day.py"
    settings = get_settings()
    env = os.environ.copy()
    env["TRADE_STORE_DIR"] = str(settings.trade_store_dir)
    env["RADAR_ARCHIVE_DIR"] = str(settings.radar_archive_dir or "")
    env["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (str(backend_dir), env.get("PYTHONPATH", ""))
        if value
    )
    with tempfile.TemporaryDirectory(prefix="radar-replay-") as directory:
        output = Path(directory) / "report.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--date",
                date,
                "--output",
                str(output),
            ],
            cwd=backend_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
        if completed.returncode != 0:
            error = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Detector replay failed: {error[:1000]}")
        return json.loads(output.read_text(encoding="utf-8"))


def reset_learning_state_for_tests() -> None:
    with _lock:
        _last_tape_sample.clear()
        _last_pipeline_event.clear()
        _last_funnel_event.clear()
