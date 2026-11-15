#!/usr/bin/env python3
"""Classify ~5y NIFTY/SENSEX sessions by day type + join FTV chunk stats."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.merge_years_index_chunk_profiles import merge_chunk_dir


def classify_session(*, ret_pct: float, range_pct: float) -> str:
    """Labels aligned with day_adaptive_engine buckets (index daily proxy)."""
    if range_pct >= 2.0 and ret_pct <= -0.7:
        return "WORST"
    if range_pct < 1.05 and abs(ret_pct) < 0.4:
        return "CHOP"
    if ret_pct >= 1.2 and range_pct >= 0.9:
        return "ELITE"
    if ret_pct >= 0.55:
        return "GOOD"
    if ret_pct <= -0.55:
        return "BEARISH"
    return "NORMAL"


def daily_bars(symbol: str, lo: date, hi: date) -> list[dict]:
    from app.engines.upstox_years_analysis import yahoo_daily_candles

    candles = yahoo_daily_candles(symbol)
    out = []
    for c in candles:
        d = c["ts"].date()
        if lo <= d <= hi:
            o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
            if o <= 0:
                continue
            ret = (cl - o) / o * 100.0
            rng = (h - l) / o * 100.0
            out.append(
                {
                    "date": d.isoformat(),
                    "returnPct": round(ret, 3),
                    "rangePct": round(rng, 3),
                    "dayType": classify_session(ret_pct=ret, range_pct=rng),
                }
            )
    return sorted(out, key=lambda x: x["date"])


def chunk_date_span(path: Path) -> tuple[date, date] | None:
    import re

    m = re.search(r"chunk_\d+_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", path.name)
    if not m:
        return None
    return date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))


def ftv_by_daytype(
    chunk_dir: Path,
    classified: dict[str, str],
) -> dict[str, dict[str, float]]:
    """Spread each chunk's 15m PUT/CALL bucket stats across session days in its span."""
    acc: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {s: {"wins": 0, "samples": 0} for s in ("CALL", "PUT")}
    )
    counts: dict[str, int] = defaultdict(int)
    for path in sorted(chunk_dir.glob("chunk_*.json")):
        span = chunk_date_span(path)
        if not span:
            continue
        lo, hi = span
        days_in = [d for d, t in classified.items() if lo <= date.fromisoformat(d) <= hi]
        if not days_in:
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        prof = (report.get("upstoxMinutes") or {}).get("profile") or {}
        buckets = prof.get("buckets") or {}
        share = 1.0 / len(days_in)
        for d in days_in:
            dt = classified[d]
            counts[dt] += 1
            for bucket, sides in buckets.items():
                if bucket not in ("09:45", "10:00", "10:15", "09:30", "09:15"):
                    continue
                for side in ("CALL", "PUT"):
                    cell = (sides.get(side) or {}).get("15") or {}
                    w = int(cell.get("wins") or 0)
                    s = int(cell.get("samples") or 0)
                    acc[dt][side]["wins"] += int(w * share)
                    acc[dt][side]["samples"] += int(s * share)
    out: dict[str, dict[str, float]] = {}
    for dt, sides in acc.items():
        out[dt] = {}
        for side in ("CALL", "PUT"):
            w, s = sides[side]["wins"], sides[side]["samples"]
            out[dt][f"{side}_15m_vert_pct"] = round(100.0 * w / s, 2) if s else 0.0
            out[dt][f"{side}_samples_est"] = round(s, 1)
        out[dt]["sessionDaysEst"] = counts[dt]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_", default="2022-01-01")
    parser.add_argument("--to", default="2026-11-15")
    parser.add_argument("--chunk-dir", type=Path, default=Path("/opt/cursor/artifacts/upstox_pull_desktop_nifty"))
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--out", type=Path, default=Path("/opt/cursor/artifacts/index-5y-daytype-study.json"))
    args = parser.parse_args()
    lo, hi = date.fromisoformat(args.from_), date.fromisoformat(args.to)
    bars = daily_bars(args.symbol, lo, hi)
    classified = {b["date"]: b["dayType"] for b in bars}
    dist: dict[str, int] = defaultdict(int)
    for b in bars:
        dist[b["dayType"]] += 1
    merged = merge_chunk_dir(args.chunk_dir, symbol=args.symbol)
    ftv = ftv_by_daytype(args.chunk_dir, classified)
    report = {
        "symbol": args.symbol,
        "range": {"from": args.from_, "to": args.to},
        "sessionCount": len(bars),
        "dayTypeDistribution": dict(sorted(dist.items(), key=lambda x: -x[1])),
        "dayTypePct": {k: round(100 * v / len(bars), 2) for k, v in dist.items()},
        "ftvByDayType_openBuckets_estimated": ftv,
        "mergedProfileLeaders15m": merged["profile"].get("timeOfDayLeaders15m"),
        "sessionDiscipline": merged.get("sessionDiscipline"),
        "sampleDaysByType": [b for b in bars if b["dayType"] in ("CHOP", "WORST", "ELITE", "GOOD")][:30],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("sampleDaysByType",)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())