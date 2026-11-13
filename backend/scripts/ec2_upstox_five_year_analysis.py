#!/usr/bin/env python3
"""Run on EC2: download ~5y Upstox index data to TRADE_STORE_DIR and analyze."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engines.upstox_five_year_pipeline import (
    get_five_year_job_status,
    run_five_year_pipeline,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="EC2 five-year Upstox download + analysis")
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--no-resume", action="store_true", help="Re-fetch all minute chunks")
    parser.add_argument("--store-dir", default=os.environ.get("TRADE_STORE_DIR", "/opt/nexusquant/data/trades"))
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("TRADE_STORE_DIR", args.store_dir)
    store = Path(args.store_dir)

    if args.status_only:
        print(json.dumps(get_five_year_job_status(args.symbol, store), indent=2, default=str))
        return 0

    try:
        report = asyncio.run(
            run_five_year_pipeline(
                symbol=args.symbol,
                years=args.years,
                resume=not args.no_resume,
                store_dir=store,
            )
        )
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("status") == "completed" else 1
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
