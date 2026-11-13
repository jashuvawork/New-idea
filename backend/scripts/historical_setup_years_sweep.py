#!/usr/bin/env python3
"""Sample multi-year setup analysis via Nexus API (Upstox on server)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def first_business_day(year: int, month: int) -> date:
    d = date(year, month, 1)
    _, last = monthrange(year, month)
    while d.month == month and d.weekday() >= 5:
        d += timedelta(days=1)
    return d if d.month == month else date(year, month, last)


def iter_sample_dates(
    start: date,
    end: date,
    *,
    cadence: str,
) -> list[date]:
    out: list[date] = []
    if cadence == "monthly":
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            d = first_business_day(y, m)
            if start <= d <= end:
                out.append(d)
            m += 1
            if m > 12:
                m = 1
                y += 1
        return out
    if cadence == "weekly":
        d = start
        while d <= end:
            if d.weekday() < 5:
                out.append(d)
            d += timedelta(days=7)
        return out
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def fetch_json(url: str, timeout: float = 60.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://65.0.136.146:8000")
    parser.add_argument("--from", dest="from_", default="2022-01-01")
    parser.add_argument("--to", default=date.today().isoformat())
    parser.add_argument("--cadence", choices=["monthly", "weekly", "daily"], default="monthly")
    parser.add_argument("--anchor", default="10:50:00")
    parser.add_argument("--side", default="PUT")
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--pause", type=float, default=0.4)
    parser.add_argument("--out", default="/opt/cursor/artifacts/historical-setup-years-sweep.json")
    args = parser.parse_args()

    start = datetime.strptime(args.from_, "%Y-%m-%d").date()
    end = datetime.strptime(args.to, "%Y-%m-%d").date()
    dates = iter_sample_dates(start, end, cadence=args.cadence)
    base = args.api_base.rstrip("/")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for i, d in enumerate(dates):
        qs = urllib.parse.urlencode(
            {
                "at": args.anchor,
                "side": args.side,
                "symbol": args.symbol,
            }
        )
        url = f"{base}/api/ai/historical-setup-analysis/{d.isoformat()}?{qs}"
        try:
            payload = fetch_json(url, timeout=90.0)
            idx = payload.get("indexSession") or {}
            br = payload.get("baseRip") or {}
            chart = payload.get("indexChart") or {}
            mtf = payload.get("indexMtf") or {}
            rows.append(
                {
                    "date": d.isoformat(),
                    "offSessionLowPct": idx.get("offSessionLowPct"),
                    "spotAtAnchor": idx.get("spotAtAnchor"),
                    "baseRipVerdict": br.get("verdict"),
                    "baseRipSignals": br.get("signals"),
                    "mtfAligned": br.get("mtfAligned"),
                    "chartDirection": chart.get("direction"),
                    "mtf1m": (mtf.get("1m") or {}).get("direction"),
                    "alignedWithChart": payload.get("alignedWithChart"),
                }
            )
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
            errors.append({"date": d.isoformat(), "error": str(exc)})
        if args.pause > 0 and i + 1 < len(dates):
            time.sleep(args.pause)

    summary = {
        "generatedAt": datetime.now(IST).isoformat(),
        "apiBase": base,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "cadence": args.cadence,
        "sampleCount": len(rows),
        "errorCount": len(errors),
        "baseRipSetupPct": round(
            100.0
            * sum(1 for r in rows if r.get("baseRipVerdict") == "BASE_RIP_SETUP")
            / len(rows),
            1,
        )
        if rows
        else 0,
        "avgOffSessionLowPct": round(
            sum(float(r["offSessionLowPct"] or 0) for r in rows) / len(rows), 2
        )
        if rows
        else None,
        "rows": rows,
        "errors": errors,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k != "rows"}, indent=2))
    print(f"wrote {out_path} ({len(rows)} samples)")
    return 1 if errors and not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
