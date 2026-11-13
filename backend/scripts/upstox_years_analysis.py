#!/usr/bin/env python3
"""Pull multi-year index data (Upstox 1m from 2022 + Yahoo daily max) and analyze locally."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engines.upstox_years_analysis import run_years_analysis


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-year Upstox/Yahoo index analysis")
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--minute-from", default="2022-01-01")
    parser.add_argument("--minute-to", default=None)
    parser.add_argument("--max-minute-chunks", type=int, default=None,
                        help="Cap Upstox 28-day chunks (for smoke tests)")
    parser.add_argument("--no-yahoo", action="store_true")
    parser.add_argument("--no-upstox", action="store_true")
    parser.add_argument(
        "--out-dir",
        default="/opt/cursor/artifacts",
        help="Write years_analysis_{symbol}.json here",
    )
    args = parser.parse_args()

    report = asyncio.run(
        run_years_analysis(
            symbol=args.symbol,
            minute_from=args.minute_from,
            minute_to=args.minute_to,
            include_yahoo_daily=not args.no_yahoo,
            include_upstox_minutes=not args.no_upstox,
            max_minute_chunks=args.max_minute_chunks,
            out_dir=Path(args.out_dir),
        )
    )
    print(json.dumps(report, indent=2, default=str))
    if report.get("upstoxMinutesError"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
