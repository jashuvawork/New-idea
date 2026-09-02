#!/usr/bin/env python3
"""Run premium-tape window replay locally (production tape on EC2 disk)."""

from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-09-02")
    parser.add_argument("--start", default="12:07:00")
    parser.add_argument("--end", default="13:40:00")
    parser.add_argument("--side", default="CALL")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    from app.engines.eod_local_base_replay import generate_window_replay

    report = generate_window_replay(
        args.date,
        start=args.start,
        end=args.end,
        side=args.side or None,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"{args.date} {args.start}–{args.end} IST {args.side or 'ALL'}: "
            f"status={report.get('status')} trades={report.get('tradeCount')} "
            f"net=₹{report.get('netPnlInr', 0):,.0f}"
        )
        for trade in report.get("trades") or []:
            print(
                f"  {trade.get('entryAt')} {trade.get('symbol')} {trade.get('side')} "
                f"{trade.get('strike')} ₹{trade.get('pnlInr', 0):,.0f} "
                f"peak={trade.get('peakPct')}% exit={trade.get('exitReason')}"
            )
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    raise SystemExit(main())
