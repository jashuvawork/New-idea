#!/usr/bin/env python3
"""
Fetch session data from Nexus API + run local replay/chart analysis (no UI).

1. GET {base}/api/ai/radar-funnel/{date}
2. GET {base}/api/ai/radar-archives/{date} → TRADE_STORE_DIR/radar_archives/
3. generate_window_replay(...) with production gates
4. Premium-tape spot/premium summary for one contract key

Upstox historical MTF (optional): requires OAuth in backend/.env
  → historical_setup_analysis.py --date ... --at ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IST = ZoneInfo("Asia/Kolkata")


def _get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _download(url: str, dest: Path, timeout: int = 300) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = _get(url, timeout=timeout)
    if len(data) < 1024:
        raise RuntimeError(f"Download too small ({len(data)} bytes) from {url}")
    dest.write_bytes(data)


def _nearest(
    points: list[tuple[datetime, float, float, float]],
    hour: int,
    minute: int,
    slack_min: int = 3,
) -> tuple | None:
    best = None
    best_delta = 999
    for ts, prem, spot, off in points:
        if ts.hour != hour:
            continue
        delta = abs(ts.minute - minute)
        if delta <= slack_min and delta < best_delta:
            best_delta = delta
            best = (ts.isoformat(), prem, spot, off)
    return best


def premium_tape_points(zip_path: Path, contract_key: str) -> list[tuple[datetime, float, float, float]]:
    import zipfile

    out: list[tuple[datetime, float, float, float]] = []
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("premium_tape.jsonl") as handle:
            for line in handle:
                batch = json.loads(line)
                ts = datetime.fromisoformat(batch["ts"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=IST)
                for c in batch.get("contracts") or []:
                    if c.get("key") == contract_key:
                        out.append(
                            (
                                ts,
                                float(c.get("premium") or 0),
                                float(c.get("spot") or 0),
                                float(c.get("offLowMovePct") or 0),
                            )
                        )
                        break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="API fetch + local Nexus analysis")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--api-base",
        default=os.environ.get("NQ_API_BASE", "http://65.0.136.146:8000"),
        help="Nexus API base (use direct EC2 :8000 for large ZIP downloads)",
    )
    parser.add_argument("--contract-key", default="NIFTY:PUT:25200")
    parser.add_argument(
        "--windows",
        default="10:45:00,11:05:00;13:00:00,13:15:00",
        help="Semicolon-separated IST windows start,end",
    )
    parser.add_argument(
        "--anchors",
        default="10:50:00,13:05:00",
        help="Comma-separated IST times for spot chart from tape",
    )
    parser.add_argument(
        "--trade-store",
        default=os.environ.get("TRADE_STORE_DIR", "/tmp/nexusquant/trades"),
    )
    args = parser.parse_args()

    base = args.api_base.rstrip("/")
    store = Path(args.trade_store)
    os.environ["TRADE_STORE_DIR"] = str(store)
    archive_dir = store / "radar_archives"
    zip_path = archive_dir / f"radar-{args.date}.zip"

    report: dict = {"date": args.date, "apiBase": base, "tradeStoreDir": str(store)}

    try:
        funnel = json.loads(_get(f"{base}/api/ai/radar-funnel/{args.date}", timeout=60))
        report["funnel"] = {
            "detected": funnel.get("detected"),
            "entered": funnel.get("entered"),
            "rows": len(funnel.get("rows") or []),
        }
        for row in funnel.get("rows") or []:
            if row.get("key") == args.contract_key:
                report["funnelContract"] = row
                break
    except urllib.error.URLError as exc:
        report["funnelError"] = str(exc)

    try:
        _download(f"{base}/api/ai/radar-archives/{args.date}", zip_path)
        report["archiveBytes"] = zip_path.stat().st_size
    except Exception as exc:
        report["archiveError"] = str(exc)

    if zip_path.is_file() and zip_path.stat().st_size > 10_000:
        from app.engines.eod_local_base_replay import (
            _spot_chart_from_history,
            generate_window_replay,
        )

        points = premium_tape_points(zip_path, args.contract_key)
        low = min((p[1] for p in points), default=0)
        report["premiumTape"] = {
            "samples": len(points),
            "sessionPremiumLow": low,
            "anchors": {},
        }
        for anchor in args.anchors.split(","):
            ah, am, *rest = anchor.strip().split(":")
            ah, am = int(ah), int(am)
            row = _nearest(points, ah, am)
            if row:
                ts, prem, spot, off = row
                off_calc = (prem - low) / low * 100 if low else 0
                report["premiumTape"]["anchors"][anchor] = {
                    "ts": ts,
                    "premium": prem,
                    "spot": spot,
                    "offLowMovePctTape": off,
                    "offLowMovePctCalc": round(off_calc, 2),
                }

        session_day = datetime.fromisoformat(args.date).date()
        for label in ("10:50:00", "13:05:00"):
            ah, am, *rest = label.split(":")
            sec = int(rest[0]) if rest else 0
            anchor = datetime(
                session_day.year,
                session_day.month,
                session_day.day,
                int(ah),
                int(am),
                sec,
                tzinfo=IST,
            )
            hist = [(ts, s) for ts, _, s, _ in points if ts <= anchor]
            if len(hist) >= 16:
                spot = hist[-1][1]
                sc = _spot_chart_from_history(hist, spot)
                report.setdefault("spotChartFromTape", {})[label] = {
                    "direction": sc.direction,
                    "momentum5Pct": sc.momentum5Pct,
                    "momentum15Pct": sc.momentum15Pct,
                    "rsi": sc.rsi,
                    "macdBias": sc.macdBias,
                    "spot": sc.spot,
                }

        report["windowReplays"] = []
        for chunk in args.windows.split(";"):
            start, end = chunk.split(",")
            side = "PUT" if "PUT" in args.contract_key else "CALL"
            wr = generate_window_replay(
                args.date, start=start.strip(), end=end.strip(), side=side
            )
            key_hits = [
                s
                for s in (wr.get("signals") or [])
                if args.contract_key in str(s.get("key") or "")
            ]
            blockers = {}
            for s in key_hits:
                b = s.get("blocker") or s.get("reason") or "unknown"
                blockers[b] = blockers.get(b, 0) + 1
            report["windowReplays"].append(
                {
                    "window": chunk,
                    "status": wr.get("status"),
                    "signalCount": len(wr.get("signals") or []),
                    "contractSignals": len(key_hits),
                    "topBlockers": sorted(
                        blockers.items(), key=lambda x: -x[1]
                    )[:5],
                    "gateStatsTop": sorted(
                        (wr.get("gateStats") or {}).items(),
                        key=lambda x: -x[1],
                    )[:6],
                }
            )

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
