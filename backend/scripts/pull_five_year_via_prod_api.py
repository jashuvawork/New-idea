#!/usr/bin/env python3
"""Chunked 5y Upstox pull through deployed years-index-analysis (live token on EC2)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

IST_OFFSET_DAYS = 28


def _add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


def _get(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://65.0.136.146:8000")
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--from", dest="from_", default="2022-01-01")
    parser.add_argument("--to", default=date.today().isoformat())
    parser.add_argument("--out-dir", default="/opt/cursor/artifacts/upstox_prod_chunks")
    parser.add_argument("--pause", type=float, default=1.0)
    args = parser.parse_args()

    lo = date.fromisoformat(args.from_)
    end = date.fromisoformat(args.to)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = args.api_base.rstrip("/")
    chunk_reports: list[dict] = []
    idx = 0

    while lo <= end:
        hi = min(end, _add_days(lo, IST_OFFSET_DAYS - 1))
        qs = urllib.parse.urlencode(
            {
                "symbol": args.symbol,
                "minute_from": lo.isoformat(),
                "minute_to": end.isoformat(),
                "max_minute_chunks": "1",
                "include_yahoo_daily": "false",
                "include_upstox_minutes": "true",
            }
        )
        url = f"{base}/api/ai/years-index-analysis?{qs}"
        tag = f"{lo.isoformat()}_{hi.isoformat()}"
        try:
            report = _get(url, timeout=180.0)
            path = out_dir / f"chunk_{idx:03d}_{tag}.json"
            path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            um = report.get("upstoxMinutes") or {}
            chunk_reports.append(
                {
                    "chunk": idx,
                    "from": lo.isoformat(),
                    "to": hi.isoformat(),
                    "candleCount": um.get("candleCount"),
                    "path": str(path),
                }
            )
            print(json.dumps(chunk_reports[-1]))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            chunk_reports.append({"chunk": idx, "from": lo.isoformat(), "error": str(exc)})
            print(json.dumps(chunk_reports[-1]), file=sys.stderr)
        idx += 1
        lo = _add_days(hi, 1)
        if args.pause > 0 and lo <= end:
            time.sleep(args.pause)

    summary = {
        "chunks": len(chunk_reports),
        "ok": sum(1 for c in chunk_reports if "error" not in c),
        "details": chunk_reports,
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["ok"] == summary["chunks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
