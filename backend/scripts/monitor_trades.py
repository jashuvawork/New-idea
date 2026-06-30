#!/usr/bin/env python3
"""Poll production closed trades and summarize churn / guard signals."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime
from typing import Any


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def summarize(trades: list[dict[str, Any]], newest_first: bool = True) -> None:
    ordered = list(trades)
    if newest_first:
        ordered = list(reversed(ordered))

    print(f"\n{'='*72}")
    print(f"Trades: {len(ordered)} | fetched {datetime.now().isoformat(timespec='seconds')}")
    print(f"{'='*72}")

    prev: dict[str, Any] | None = None
    rapid = 0
    flips = 0
    low_score = 0
    bearish_calls = 0
    has_moneyness = 0

    for t in ordered:
        ctx = t.get("entryContext") or {}
        if ctx.get("moneyness"):
            has_moneyness += 1
        score = ctx.get("selectionScore") or ctx.get("tqs")
        if score is not None and float(score) < 60:
            low_score += 1
        if t.get("side") == "CALL" and ctx.get("breadth") == "BEARISH":
            bearish_calls += 1

        gap_s = ""
        if prev is not None:
            gap = (parse_ts(t["openedAt"]) - parse_ts(prev["closedAt"])).total_seconds()
            gap_s = f"gap={gap:.0f}s"
            if gap < 60:
                rapid += 1
            if prev.get("side") != t.get("side"):
                flips += 1
                gap_s += f" FLIP {prev['side']}->{t['side']}"

        mono = ctx.get("moneyness", "—")
        closed = t.get("closedAt", "")[:19]
        print(
            f"{closed} | {t['symbol']:6} {t['side']:4} {t['strike']:>7.0f} | "
            f"PnL {t['pnlInr']:>10,.0f} | {str(t.get('exitReason',''))[:22]:22} | "
            f"score={score} | {ctx.get('regime','?')}/{ctx.get('breadth','?')} | "
            f"m={mono} {gap_s}"
        )
        prev = t

    wins = sum(1 for t in ordered if t["pnlInr"] > 0)
    losses = sum(1 for t in ordered if t["pnlInr"] < 0)
    net = sum(t["pnlInr"] for t in ordered)
    print(f"\nNet: ₹{net:,.0f} | W/L {wins}/{losses}")
    print(
        f"Churn: rapid_reentry(<60s)={rapid} | CE↔PE flips={flips} | "
        f"score<60={low_score} | bearish_CALLs={bearish_calls} | "
        f"has_moneyness={has_moneyness}/{len(ordered)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://www.jashuvatrade.xyz/api/auto-trader/history/trades/closed")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--watch", action="store_true", help="Poll every N seconds")
    parser.add_argument("--interval", type=int, default=45)
    parser.add_argument("--rounds", type=int, default=6)
    args = parser.parse_args()

    seen_ids: set[str] = set()
    url = f"{args.url}?limit={args.limit}"

    for rnd in range(args.rounds if args.watch else 1):
        if args.watch and rnd:
            print(f"\n--- waiting {args.interval}s (round {rnd + 1}/{args.rounds}) ---")
            time.sleep(args.interval)

        data = fetch_json(url)
        trades = data.get("trades", [])
        new = [t for t in trades if t["id"] not in seen_ids]
        for t in trades:
            seen_ids.add(t["id"])

        if args.watch and new:
            print(f"\n*** {len(new)} NEW trade(s) since last poll ***")
            for t in new:
                ctx = t.get("entryContext") or {}
                print(
                    f"  NEW {t['id'][:8]} {t['symbol']} {t['side']} "
                    f"PnL={t['pnlInr']:,.0f} exit={t.get('exitReason')} "
                    f"score={ctx.get('selectionScore') or ctx.get('tqs')} "
                    f"moneyness={ctx.get('moneyness', '—')}"
                )

        summarize(trades)

        if args.watch:
            try:
                status = fetch_json("https://www.jashuvatrade.xyz/api/auto-trader/status")
                skipped = status.get("skipped") or []
                chop = status.get("chopGuards") or {}
                print(
                    f"Status: running={status.get('running')} | "
                    f"open={len(status.get('openPaperTrades') or [])} | "
                    f"skipped_now={len(skipped)} | "
                    f"dayMode={chop.get('dayMode')} | "
                    f"sessionPaused={chop.get('sessionPaused')}"
                )
                if skipped:
                    for s in skipped[:5]:
                        print(f"  skip: {s}")
            except Exception as exc:
                print(f"status fetch failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
