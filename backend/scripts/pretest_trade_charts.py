#!/usr/bin/env python3
"""Live MTF pre-test — index + option charts from Upstox before a trade."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engines.execution_chart_monitor import monitor_trade_chart_before_execution
from app.models.schemas import Breadth, Side, SymbolSnapshot


async def run(symbol: str, side: str, strike: float, instrument_key: str | None) -> int:
    from app.services.upstox import UpstoxClient

    client = UpstoxClient()
    snap = SymbolSnapshot(
        symbol=symbol.upper(),
        timestamp="",
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        tradeQualityScore=60,
        regime="TREND_EXPANSION",
        breadth=Breadth(score=50, bias="NEUTRAL", aligned=False),
    )
    passed, reason, meta = await monitor_trade_chart_before_execution(
        client,
        symbol.upper(),
        Side(side.upper()),
        strike,
        snap,
        trade_score=65,
        instrument_key=instrument_key,
    )
    out = {
        "passed": passed,
        "reason": reason,
        "indexMtf": meta.get("indexMtf"),
        "premiumMtf": meta.get("premiumMtf"),
        "indexChart": meta.get("indexChart"),
        "premiumChart": meta.get("premiumChart"),
        "mtfPreTest": meta.get("mtfPreTest"),
        "recommendedSide": meta.get("recommendedSide"),
    }
    print(json.dumps(out, indent=2, default=str))
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-test MTF charts from Upstox")
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--side", default="CALL", choices=["CALL", "PUT"])
    parser.add_argument("--strike", type=float, default=23900)
    parser.add_argument("--instrument-key", default=None, help="Option leg Upstox key")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.symbol, args.side, args.strike, args.instrument_key))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "hint": "Ensure Upstox token is valid"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
