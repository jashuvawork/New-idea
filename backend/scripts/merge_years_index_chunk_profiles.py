#!/usr/bin/env python3
"""Merge years-index-analysis chunk JSON files into one FTV-style profile."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

HORIZONS = (1, 3, 5, 15)
_CHUNK_GLOB = "chunk_*.json"
_EARLY_BUCKETS = frozenset({"09:15", "09:30"})
_POST_0945_BUCKETS = frozenset(
    {"09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30", "11:45", "12:00"}
)


def _pct(wins: int, samples: int) -> float:
    return round(100.0 * wins / samples, 2) if samples else 0.0


def _merge_counts(
    target: dict[str, dict[str, dict[str, int]]],
    source: dict[str, Any] | None,
) -> None:
    if not source:
        return
    for bucket, sides in source.items():
        for side in ("CALL", "PUT"):
            side_row = sides.get(side) or {}
            for horizon in HORIZONS:
                h = side_row.get(str(horizon)) or {}
                cell = target[bucket][side][str(horizon)]
                cell["wins"] += int(h.get("wins") or 0)
                cell["samples"] += int(h.get("samples") or 0)


def _build_rates(bucket_counts: dict[str, dict[str, dict[str, dict[str, int]]]]) -> dict[str, Any]:
    global_counts: dict[str, dict[int, dict[str, int]]] = {
        "CALL": {h: {"wins": 0, "samples": 0} for h in HORIZONS},
        "PUT": {h: {"wins": 0, "samples": 0} for h in HORIZONS},
    }
    for sides in bucket_counts.values():
        for side in ("CALL", "PUT"):
            for horizon in HORIZONS:
                cell = sides[side][str(horizon)]
                global_counts[side][horizon]["wins"] += cell["wins"]
                global_counts[side][horizon]["samples"] += cell["samples"]

    rates: dict[str, dict[str, Any]] = {}
    for side in ("CALL", "PUT"):
        rates[side] = {}
        for horizon in HORIZONS:
            counts = global_counts[side][horizon]
            rates[side][str(horizon)] = {
                **counts,
                "probabilityPct": _pct(counts["wins"], counts["samples"]),
            }

    buckets: dict[str, Any] = {}
    for bucket, sides in bucket_counts.items():
        buckets[bucket] = {}
        for side in ("CALL", "PUT"):
            buckets[bucket][side] = {}
            for horizon in HORIZONS:
                counts = sides[side][str(horizon)]
                buckets[bucket][side][str(horizon)] = {
                    **counts,
                    "probabilityPct": _pct(counts["wins"], counts["samples"]),
                }

    leaders: dict[str, list[dict[str, Any]]] = {}
    for side in ("CALL", "PUT"):
        rows = [
            {
                "time": bucket,
                "probabilityPct": buckets[bucket][side]["15"]["probabilityPct"],
                "samples": buckets[bucket][side]["15"]["samples"],
                "wins": buckets[bucket][side]["15"]["wins"],
            }
            for bucket in buckets
            if buckets[bucket][side]["15"]["samples"] > 0
        ]
        leaders[side] = sorted(
            rows,
            key=lambda r: (r["probabilityPct"], r["samples"]),
            reverse=True,
        )[:12]

    return {"rates": rates, "buckets": buckets, "timeOfDayLeaders15m": leaders}


def _window_slice(
    buckets: dict[str, Any],
    allowed: frozenset[str],
) -> dict[str, dict[str, dict[str, int]]]:
    merged: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {s: {str(h): {"wins": 0, "samples": 0} for h in HORIZONS} for s in ("CALL", "PUT")}
    )
    for bucket in allowed:
        if bucket not in buckets:
            continue
        for side in ("CALL", "PUT"):
            for horizon in HORIZONS:
                cell = buckets[bucket][side][str(horizon)]
                out = merged[bucket][side][str(horizon)]
                out["wins"] += int(cell.get("wins") or 0)
                out["samples"] += int(cell.get("samples") or 0)
    return merged


def merge_chunk_dir(
    in_dir: Path,
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    paths = sorted(in_dir.glob(_CHUNK_GLOB))
    if not paths:
        raise FileNotFoundError(f"No {_CHUNK_GLOB} under {in_dir}")

    bucket_counts: dict[str, dict[str, dict[str, dict[str, int]]]] = defaultdict(
        lambda: {s: {str(h): {"wins": 0, "samples": 0} for h in HORIZONS} for s in ("CALL", "PUT")}
    )
    candle_total = 0
    chunk_meta: list[dict[str, Any]] = []
    sym = symbol

    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        sym = sym or str(report.get("symbol") or "UNKNOWN")
        um = report.get("upstoxMinutes") or {}
        candle_total += int(um.get("candleCount") or 0)
        prof = um.get("profile") or {}
        _merge_counts(bucket_counts, prof.get("buckets"))
        chunk_meta.append(
            {
                "file": path.name,
                "candleCount": um.get("candleCount"),
                "fromEffective": (report.get("minuteRange") or {}).get("toEffective"),
            }
        )

    merged = _build_rates(bucket_counts)
    early = _build_rates(_window_slice(merged["buckets"], _EARLY_BUCKETS))
    post = _build_rates(_window_slice(merged["buckets"], _POST_0945_BUCKETS))

    return {
        "symbol": sym,
        "sourceDir": str(in_dir.resolve()),
        "chunkFiles": len(paths),
        "minuteCandlesInProfiles": candle_total,
        "chunks": chunk_meta,
        "profile": {
            "status": "READY" if candle_total else "INSUFFICIENT_DATA",
            **merged,
        },
        "sessionDiscipline": {
            "earlyOpen09_15_09_30_15m": {
                "CALL": early["rates"]["CALL"]["15"],
                "PUT": early["rates"]["PUT"]["15"],
            },
            "post0945_morning_15m": {
                "CALL": post["rates"]["CALL"]["15"],
                "PUT": post["rates"]["PUT"]["15"],
            },
            "note": "Index 1m vertical-from-flat; supports 09:45 entry discipline vs open chop.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge years-index-analysis chunk profiles")
    parser.add_argument("--in-dir", type=Path, required=True)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--out", type=Path, default=None, help="Write merged JSON here")
    args = parser.parse_args()

    report = merge_chunk_dir(args.in_dir, symbol=args.symbol)
    payload = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())