"""Durable CE/PE flat-to-vertical calibration from archived premium tape."""

from __future__ import annotations

import json
import os
import threading
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.radar_learning import premium_tape_path, read_premium_tape

IST = ZoneInfo("Asia/Kolkata")
HORIZON_SECONDS = (60, 180, 300, 900)
HORIZON_MINUTES = (1, 3, 5, 15)
_build_lock = threading.Lock()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(IST)


def _contract_parts(key: str) -> tuple[str, str] | None:
    parts = str(key or "").split(":")
    if len(parts) < 3:
        return None
    symbol, side = parts[0].upper(), parts[1].upper()
    if side not in {"CALL", "PUT"}:
        return None
    return symbol, side


def _bucket(ts: datetime, minutes: int) -> str:
    absolute = ts.hour * 60 + ts.minute
    floor = absolute // minutes * minutes
    return f"{floor // 60:02d}:{floor % 60:02d}"


def _series_for_date(date: str) -> dict[str, list[tuple[datetime, float]]]:
    series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for batch in read_premium_tape(date):
        ts = _timestamp(batch.get("ts"))
        if ts is None:
            continue
        for contract in batch.get("contracts") or []:
            key = str(contract.get("key") or "")
            premium = _number(contract.get("premium"))
            if _contract_parts(key) and premium > 0:
                series[key].append((ts, premium))
    for rows in series.values():
        rows.sort(key=lambda row: row[0])
    return series


def extract_premium_observations(
    date: str,
    series: Mapping[str, list[tuple[datetime, float]]],
    *,
    flat_window_seconds: int,
    flat_max_range_pct: float,
    vertical_move_pct: float,
    sample_seconds: int,
    bucket_minutes: int,
) -> list[dict[str, Any]]:
    """Create leakage-safe horizon labels from compressed option-premium bases."""
    observations: list[dict[str, Any]] = []
    for key, rows in series.items():
        parts = _contract_parts(key)
        if not parts or len(rows) < 5:
            continue
        symbol, side = parts
        timestamps = [ts for ts, _ in rows]
        all_premiums = [premium for _, premium in rows]
        left = 0
        last_anchor: Optional[datetime] = None
        for index in range(3, len(rows) - 1):
            anchor_ts, anchor_premium = rows[index]
            if last_anchor and (anchor_ts - last_anchor).total_seconds() < sample_seconds:
                continue
            cutoff = anchor_ts - timedelta(seconds=flat_window_seconds)
            while left < index and rows[left][0] < cutoff:
                left += 1
            base = rows[left : index + 1]
            if len(base) < 4:
                continue
            premiums = [premium for _, premium in base]
            low = min(premiums)
            if low <= 0:
                continue
            base_range_pct = (max(premiums) - low) / low * 100.0
            if base_range_pct > flat_max_range_pct:
                continue

            labels: dict[str, int] = {}
            complete = True
            for minutes, seconds in zip(HORIZON_MINUTES, HORIZON_SECONDS):
                horizon_end = anchor_ts + timedelta(seconds=seconds)
                end_index = bisect_right(
                    timestamps, horizon_end, lo=index + 1,
                )
                future = all_premiums[index + 1 : end_index]
                if not future or timestamps[-1] < horizon_end:
                    complete = False
                    break
                move_pct = (max(future) - anchor_premium) / anchor_premium * 100.0
                labels[str(minutes)] = int(move_pct >= vertical_move_pct)
            if not complete:
                continue
            observations.append({
                "date": date,
                "symbol": symbol,
                "side": side,
                "bucket": _bucket(anchor_ts, bucket_minutes),
                "baseRangePct": round(base_range_pct, 4),
                "labels": labels,
            })
            last_anchor = anchor_ts
    return observations


def _counts(
    observations: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    rates: dict[str, Any] = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(lambda: {"wins": 0, "samples": 0})
        )
    )
    buckets: dict[str, Any] = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(lambda: {"wins": 0, "samples": 0})
            )
        )
    )
    for row in observations:
        symbol, side, bucket = row["symbol"], row["side"], row["bucket"]
        for horizon, won in (row.get("labels") or {}).items():
            rates[symbol][side][horizon]["samples"] += 1
            rates[symbol][side][horizon]["wins"] += int(bool(won))
            buckets[symbol][bucket][side][horizon]["samples"] += 1
            buckets[symbol][bucket][side][horizon]["wins"] += int(bool(won))
    return rates, buckets


def _probability(wins: int, samples: int, fallback: float = 0.0) -> float:
    # Ten fallback-centered pseudo-observations keep sparse time cells sane.
    return (wins + fallback * 10.0) / (samples + 10.0) if samples >= 0 else fallback


def _materialize_rates(
    raw_rates: Mapping[str, Any],
    raw_buckets: Mapping[str, Any],
) -> dict[str, Any]:
    symbols: dict[str, Any] = {}
    for symbol, sides in raw_rates.items():
        symbol_rates: dict[str, Any] = {}
        for side, horizons in sides.items():
            symbol_rates[side] = {}
            for horizon, counts in horizons.items():
                samples = int(counts["samples"])
                wins = int(counts["wins"])
                symbol_rates[side][horizon] = {
                    "wins": wins,
                    "samples": samples,
                    "probabilityPct": round(
                        _probability(wins, samples) * 100.0, 2,
                    ),
                }
        symbol_buckets: dict[str, Any] = {}
        for bucket, bucket_sides in (raw_buckets.get(symbol) or {}).items():
            symbol_buckets[bucket] = {}
            for side, horizons in bucket_sides.items():
                symbol_buckets[bucket][side] = {}
                for horizon, counts in horizons.items():
                    fallback = (
                        symbol_rates.get(side, {}).get(horizon, {})
                        .get("probabilityPct", 0.0) / 100.0
                    )
                    samples = int(counts["samples"])
                    wins = int(counts["wins"])
                    symbol_buckets[bucket][side][horizon] = {
                        "wins": wins,
                        "samples": samples,
                        "probabilityPct": round(
                            _probability(wins, samples, fallback) * 100.0,
                            2,
                        ),
                    }
        base_samples = sum(
            int(horizons.get("5", {}).get("samples") or 0)
            for horizons in sides.values()
        )
        symbols[symbol] = {
            "sampleCount": base_samples,
            "rates": symbol_rates,
            "buckets": symbol_buckets,
        }
    return symbols


def _rate_for(
    symbol_profile: Mapping[str, Any],
    side: str,
    horizon: str,
    bucket: str,
) -> float:
    bucket_row = (
        (symbol_profile.get("buckets") or {}).get(bucket, {})
        .get(side, {})
        .get(horizon, {})
    )
    global_row = (
        (symbol_profile.get("rates") or {}).get(side, {}).get(horizon, {})
    )
    selected = (
        bucket_row
        if int(bucket_row.get("samples") or 0) >= 5
        else global_row
    )
    return _number(selected.get("probabilityPct")) / 100.0


def _walk_forward(
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    profiles: Mapping[str, Any],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    errors: list[float] = []
    absolute_calibration: list[float] = []
    grouped: dict[tuple[str, str, str], list[tuple[float, int]]] = defaultdict(list)
    for row in validation:
        symbol_profile = profiles.get(row["symbol"]) or {}
        for horizon, observed in row["labels"].items():
            predicted = _rate_for(
                symbol_profile, row["side"], horizon, row["bucket"],
            )
            grouped[(row["symbol"], row["side"], horizon)].append(
                (predicted, int(observed)),
            )
            errors.append((predicted - int(observed)) ** 2)

    for (symbol, side, horizon), rows in grouped.items():
        predicted = sum(row[0] for row in rows) / len(rows)
        observed = sum(row[1] for row in rows) / len(rows)
        absolute_calibration.append(abs(predicted - observed))
        metrics.setdefault(symbol, {}).setdefault(side, {})[horizon] = {
            "samples": len(rows),
            "brierScore": round(
                sum((p - y) ** 2 for p, y in rows) / len(rows),
                4,
            ),
            "predictedPct": round(predicted * 100.0, 2),
            "observedPct": round(observed * 100.0, 2),
            "calibrationErrorPct": round(abs(predicted - observed) * 100.0, 2),
        }
    return {
        "status": "READY" if validation else "INSUFFICIENT_VALIDATION",
        "trainSamples": len(train),
        "validationSamples": len(validation),
        "brierScore": round(sum(errors) / len(errors), 4) if errors else None,
        "meanCalibrationErrorPct": (
            round(sum(absolute_calibration) / len(absolute_calibration) * 100.0, 2)
            if absolute_calibration else None
        ),
        "metrics": metrics,
    }


def _drift(
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    *,
    warn_pp: float,
    critical_pp: float,
) -> dict[str, Any]:
    def rate(rows: list[dict[str, Any]], side: str) -> tuple[int, float]:
        labels = [
            int(row["labels"]["5"])
            for row in rows
            if row["side"] == side and "5" in row["labels"]
        ]
        return len(labels), sum(labels) / len(labels) * 100.0 if labels else 0.0

    sides: dict[str, Any] = {}
    worst = 0.0
    for side in ("CALL", "PUT"):
        old_n, old_rate = rate(train, side)
        recent_n, recent_rate = rate(validation, side)
        delta = abs(recent_rate - old_rate) if old_n and recent_n else 0.0
        worst = max(worst, delta)
        sides[side] = {
            "baselineSamples": old_n,
            "recentSamples": recent_n,
            "baselineWinRatePct": round(old_rate, 2),
            "recentWinRatePct": round(recent_rate, 2),
            "absoluteDeltaPctPoints": round(delta, 2),
        }
    status = (
        "DRIFT" if worst >= critical_pp
        else "WATCH" if worst >= warn_pp
        else "STABLE" if validation
        else "INSUFFICIENT_DATA"
    )
    return {"status": status, "maxDeltaPctPoints": round(worst, 2), "sides": sides}


def build_premium_calibration(
    observations: list[dict[str, Any]],
    *,
    generated_at: datetime,
    source_dates: list[str],
    drift_warn_pp: float,
    drift_critical_pp: float,
) -> dict[str, Any]:
    """Fit on older dates and validate strictly on later dates."""
    dates = sorted({row["date"] for row in observations})
    validation_days = max(1, int(round(len(dates) * 0.2))) if len(dates) >= 2 else 0
    validation_dates = set(dates[-validation_days:]) if validation_days else set()
    train = [row for row in observations if row["date"] not in validation_dates]
    validation = [row for row in observations if row["date"] in validation_dates]
    # With only one day, produce a learning profile but do not claim validation.
    validation_fit = train or observations
    validation_rates, validation_buckets = _counts(validation_fit)
    validation_profiles = _materialize_rates(
        validation_rates, validation_buckets,
    )
    walk_forward = _walk_forward(train, validation, validation_profiles)
    # After measuring strictly on later unseen dates, refit the served model on all
    # completed sessions so recent regimes are not permanently discarded.
    raw_rates, raw_buckets = _counts(observations)
    profiles = _materialize_rates(raw_rates, raw_buckets)
    drift = _drift(
        train, validation, warn_pp=drift_warn_pp, critical_pp=drift_critical_pp,
    )
    return {
        "version": 1,
        "generatedAt": generated_at.isoformat(),
        "status": "READY" if observations else "INSUFFICIENT_DATA",
        "source": "local_option_premium_tape",
        "sourceDates": source_dates,
        "observationCount": len(observations),
        "symbols": profiles,
        "walkForward": walk_forward,
        "drift": drift,
    }


def premium_calibration_path() -> Path:
    path = Path(get_settings().trade_store_dir) / "ftv_probability"
    path.mkdir(parents=True, exist_ok=True)
    return path / "premium_calibration.json"


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def load_premium_calibration() -> Optional[dict[str, Any]]:
    path = premium_calibration_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def build_and_persist_premium_calibration(
    *,
    force: bool = False,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Load a fresh durable profile or rebuild it from retained premium tape."""
    settings = get_settings()
    current = now or datetime.now(IST)
    existing = load_premium_calibration()
    cache_seconds = max(60, int(settings.ftv_probability_profile_cache_seconds))
    if existing and not force:
        generated = _timestamp(existing.get("generatedAt"))
        if generated and (current - generated).total_seconds() < cache_seconds:
            return existing

    with _build_lock:
        existing = load_premium_calibration()
        if existing and not force:
            generated = _timestamp(existing.get("generatedAt"))
            if generated and (current - generated).total_seconds() < cache_seconds:
                return existing

        history_days = max(1, int(settings.ftv_premium_calibration_history_days))
        market_closed = (
            current.hour > 15 or (current.hour == 15 and current.minute >= 30)
        )
        offsets = (
            range(history_days - 1, -1, -1)
            if force and market_closed
            else range(history_days, 0, -1)
        )
        dates = [
            (current.date() - timedelta(days=offset)).isoformat()
            for offset in offsets
            if premium_tape_path(
                (current.date() - timedelta(days=offset)).isoformat()
            ).exists()
        ]
        observations: list[dict[str, Any]] = []
        for date in dates:
            observations.extend(extract_premium_observations(
                date,
                _series_for_date(date),
                flat_window_seconds=max(
                    30, int(settings.radar_hindsight_flat_window_seconds),
                ),
                flat_max_range_pct=float(
                    settings.radar_hindsight_flat_max_range_pct,
                ),
                vertical_move_pct=float(
                    settings.ftv_premium_vertical_move_pct,
                ),
                sample_seconds=max(
                    15, int(settings.ftv_premium_calibration_sample_seconds),
                ),
                bucket_minutes=max(
                    5, int(settings.ftv_probability_time_bucket_minutes),
                ),
            ))
        payload = build_premium_calibration(
            observations,
            generated_at=current,
            source_dates=dates,
            drift_warn_pp=float(settings.ftv_probability_drift_warn_pct_points),
            drift_critical_pp=float(
                settings.ftv_probability_drift_critical_pct_points,
            ),
        )
        _atomic_write(premium_calibration_path(), payload)
        return payload
