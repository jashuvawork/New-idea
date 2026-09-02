#!/usr/bin/env python3
"""Premium-tape window replay — estimate missed PnL during a pause window."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "https://www.jashuvatrade.xyz"


def fetch_window_replay(
    date: str,
    *,
    start: str,
    end: str,
    side: str | None,
    base_url: str,
) -> dict:
    side_q = f"&side={side}" if side else ""
    url = (
        f"{base_url.rstrip('/')}/api/ai/window-replay/{date}"
        f"?start={start}&end={end}{side_q}"
    )
    with urllib.request.urlopen(url, timeout=300) as resp:
        return json.load(resp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-09-02")
    parser.add_argument("--start", default="12:07:00", help="IST window start HH:MM[:SS]")
    parser.add_argument("--end", default="13:40:00", help="IST window end HH:MM[:SS]")
    parser.add_argument("--side", default="CALL", choices=["CALL", "PUT"])
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        report = fetch_window_replay(
            args.date,
            start=args.start,
            end=args.end,
            side=args.side,
            base_url=args.base_url,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {body[:500]}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    if report.get("status") != "ok":
        print(f"Status: {report.get('status')} — {report.get('note', '')}")
        return 1

    trades = report.get("trades") or []
    print(f"Window replay {args.date} {args.start}–{args.end} IST ({args.side})")
    print(f"Batches on tape: {report.get('sampleBatches')}  candidates: {report.get('candidateCount')}")
    print(f"Trades taken: {len(trades)}  net: ₹{report.get('netPnlInr', 0):,.0f}")
    print(f"Wins: {report.get('wins', 0)}  Losses: {report.get('losses', 0)}")
    print()
    for t in trades:
        print(
            f"  {t.get('entryAt','?'):>8} {t.get('symbol')} {t.get('side')} {t.get('strike'):.0f} "
            f"₹{t.get('pnlInr', 0):,.0f} peak={t.get('peakPct')}% exit={t.get('exitReason')}"
        )
    gate_stats = report.get("gateStats") or {}
    if gate_stats:
        print("\nTop gate blockers:")
        for reason, count in sorted(gate_stats.items(), key=lambda kv: -kv[1])[:12]:
            print(f"  {count:4} {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
