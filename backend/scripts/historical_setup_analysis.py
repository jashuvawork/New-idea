#!/usr/bin/env python3
"""Historical base-rip setup analysis from Upstox V3 candles (index + optional option leg)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engines.historical_upstox_analysis import analyze_historical_setup
from app.services.upstox import UpstoxClient, UpstoxError


async def run(args: argparse.Namespace) -> int:
    client = UpstoxClient()
    try:
        payload = await analyze_historical_setup(
            client,
            symbol=args.symbol,
            session_date=args.date,
            at_ist=args.at,
            side=args.side,
            instrument_key=args.instrument_key,
        )
    except UpstoxError as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "hint": "Complete Upstox OAuth (backend/.env + /api/upstox/login-url)",
                },
                indent=2,
            )
        )
        return 2
    print(json.dumps(payload, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay Nexus chart/MTF setup at a historical IST time via Upstox",
    )
    parser.add_argument("--date", required=True, help="Session date YYYY-MM-DD")
    parser.add_argument(
        "--at",
        default="10:50:00",
        help="Anchor time IST HH:MM:SS on that date",
    )
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--side", default="PUT", choices=["CALL", "PUT"])
    parser.add_argument(
        "--instrument-key",
        default=None,
        help="Upstox option instrument key for premium MTF (historical)",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
