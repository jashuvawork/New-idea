"""Options 1m CSV session analysis (Nexus-aligned anchors)."""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ANCHORS = ("09:15", "10:50", "13:05", "15:15", "15:30")


def parse_csv(path: Path) -> dict[tuple, list[dict]]:
    by: dict[tuple, list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            k = (
                row["date"],
                row["index"],
                row["type"],
                int(float(row["strike"])),
            )
            by[k].append(
                {
                    "time": row["time_ist"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"] or 0),
                    "oi": float(row["oi"] or 0),
                    "expiry": row["expiry"],
                }
            )
    for k in by:
        by[k].sort(key=lambda b: b["time"])
    return by


def series_stats(bars: list[dict]) -> dict | None:
    if not bars:
        return None
    session_low = min(b["low"] for b in bars)
    session_high = max(b["high"] for b in bars)
    first = bars[0]["open"]
    last = bars[-1]["close"]
    anchors = {}
    for label in ANCHORS:
        hit = next((b for b in bars if b["time"] == label), None)
        if not hit:
            continue
        prem = hit["close"]
        off_low = (prem - session_low) / session_low * 100 if session_low > 0 else 0.0
        anchors[label] = {
            "premium": round(prem, 2),
            "offSessionLowPct": round(off_low, 2),
        }
    mfe = (session_high - first) / first * 100 if first > 0 else 0
    mae = (first - session_low) / first * 100 if first > 0 else 0
    day_ret = (last - first) / first * 100 if first > 0 else 0
    return {
        "bars": len(bars),
        "sessionLow": round(session_low, 2),
        "sessionHigh": round(session_high, 2),
        "sessionRangePct": round((session_high - session_low) / first * 100, 2) if first > 0 else 0,
        "dayReturnPct": round(day_ret, 2),
        "mfeFromOpenPct": round(mfe, 2),
        "maeFromOpenPct": round(mae, 2),
        "anchors": anchors,
        "totalVolume": int(sum(b["volume"] for b in bars)),
        "maxOi": int(max(b["oi"] for b in bars)),
    }


def base_rip_heuristic(stats: dict | None, side: str) -> str | None:
    if not stats:
        return None
    a = stats.get("anchors") or {}
    t1050 = a.get("10:50")
    if not t1050:
        return "NO_ANCHOR"
    off = t1050.get("offSessionLowPct", 99)
    if off <= 12 and stats.get("mfeFromOpenPct", 0) >= 8:
        return "BASE_RIP_LIKE"
    if off <= 25:
        return "NEAR_BASE"
    return "EXTENDED"


def _pctile(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    xs = sorted(vals)
    idx = int(round(q * (len(xs) - 1)))
    return round(xs[idx], 2)


def build_training_profile(series_list: list[dict]) -> dict[str, Any]:
    """Distill learnable priors for gate tuning (not live ML retrain)."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in series_list:
        key = f"{r['index']}:{r['type']}"
        buckets[key].append(r)

    by_key: dict[str, Any] = {}
    for key, rows in buckets.items():
        mfe = [r["mfeFromOpenPct"] for r in rows]
        mae = [r["maeFromOpenPct"] for r in rows]
        off1050 = [
            r["anchors"]["10:50"]["offSessionLowPct"]
            for r in rows
            if r.get("anchors", {}).get("10:50")
        ]
        wins = [r for r in rows if r.get("mfeFromOpenPct", 0) >= 15]
        base_rip = [r for r in rows if r.get("baseRipHeuristic") == "BASE_RIP_LIKE"]
        by_key[key] = {
            "samples": len(rows),
            "mfeP50": _pctile(mfe, 0.5),
            "mfeP90": _pctile(mfe, 0.9),
            "maeP50": _pctile(mae, 0.5),
            "offSessionLow1050P50": _pctile(off1050, 0.5),
            "bigLegRatePct": round(100 * len(wins) / len(rows), 1) if rows else 0,
            "baseRipLikeRatePct": round(100 * len(base_rip) / len(rows), 1) if rows else 0,
        }

    global_mfe = [r["mfeFromOpenPct"] for r in series_list]
    return {
        "profileVersion": 1,
        "trainedSeries": len(series_list),
        "byIndexSide": by_key,
        "globalMfeP50": _pctile(global_mfe, 0.5),
        "globalMfeP90": _pctile(global_mfe, 0.9),
        "recommendedEntryOffLowCeilingPct": _pctile(
            [r["anchors"]["10:50"]["offSessionLowPct"] for r in series_list if r.get("baseRipHeuristic") == "BASE_RIP_LIKE" and r.get("anchors", {}).get("10:50")],
            0.75,
        )
        or 12.0,
    }


def analyze_csv_file(path: Path, out_dir: Path, *, include_all_series: bool = True) -> dict[str, Any]:
    by = parse_csv(path)
    series_list: list[dict] = []
    by_date: dict[str, list] = defaultdict(list)
    by_index: dict[str, int] = defaultdict(int)

    for key, bars in sorted(by.items()):
        date, index, typ, strike = key
        st = series_stats(bars)
        if not st:
            continue
        entry = {
            "date": date,
            "index": index,
            "type": typ,
            "strike": strike,
            "expiry": bars[0]["expiry"],
            **st,
            "baseRipHeuristic": base_rip_heuristic(st, typ),
        }
        series_list.append(entry)
        by_date[date].append(entry)
        by_index[index] += 1

    dates = sorted(by_date)
    daily_top = []
    for d in dates:
        day_rows = sorted(by_date[d], key=lambda r: -r["mfeFromOpenPct"])[:5]
        daily_top.append({"date": d, "topMfe": day_rows})

    base_rip_like = [r for r in series_list if r["baseRipHeuristic"] == "BASE_RIP_LIKE"]
    near_base = [r for r in series_list if r["baseRipHeuristic"] == "NEAR_BASE"]

    macro = {
        "sourceFile": str(path),
        "seriesCount": len(series_list),
        "dates": dates,
        "dateCount": len(dates),
        "rowsInCsv": sum(len(v) for v in by.values()),
        "byIndex": dict(by_index),
        "baseRipLikeCount": len(base_rip_like),
        "nearBaseCount": len(near_base),
        "avgSessionRangePct": round(
            statistics.mean(r["sessionRangePct"] for r in series_list), 2
        )
        if series_list
        else 0,
        "medianOffLowAt1050": round(
            statistics.median(
                r["anchors"]["10:50"]["offSessionLowPct"]
                for r in series_list
                if r.get("anchors", {}).get("10:50")
            ),
            2,
        )
        if any(r.get("anchors", {}).get("10:50") for r in series_list)
        else None,
    }

    training = build_training_profile(series_list)

    report: dict[str, Any] = {
        "generatedAt": datetime.now(IST).isoformat(),
        "macro": macro,
        "training": training,
        "baseRipLikeSamples": base_rip_like[:50],
        "dailyTopMfe": daily_top,
    }
    if include_all_series:
        report["allSeries"] = series_list

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    json_path = out_dir / f"{stem}_full_analysis.json"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["artifacts"] = {"json": str(json_path)}
    return report