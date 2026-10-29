#!/usr/bin/env python3
"""Summarize first_trade_timing_sweep.json for reporting."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/cursor/artifacts/first_trade_timing_sweep.json")
    data = json.loads(path.read_text())
    rows = [r for r in data["results"] if r.get("status") == "ok"]
    # Drop obvious interpolation artifacts (OTM blow-ups to EOD close)
    rows = [
        r
        for r in rows
        if float(r.get("pnlInr") or 0) <= 120_000
        and r.get("exitReason") != "eod_close"
        or float(r.get("pnlInr") or 0) <= 80_000
    ]

    by_pol: dict[str, list] = defaultdict(list)
    for r in rows:
        by_pol[r["policy"]].append(r)

    print("=== By policy (best earliest clock, explosion exits, capped outliers) ===")
    for pol in sorted(by_pol):
        best = max(by_pol[pol], key=lambda x: float(x.get("pnlInr") or 0))
        print(
            f"{pol}: best pnl=₹{best.get('pnlInr'):,.0f} @ earliest={best.get('earliestEntryIst')} "
            f"{best.get('key')} exit={best.get('exitReason')}"
        )

    print("\n=== live_fade_CALL: top 15 earliest clocks ===")
    lf = sorted(
        [r for r in rows if r.get("policy") == "live_fade_CALL"],
        key=lambda x: float(x.get("pnlInr") or 0),
        reverse=True,
    )[:15]
    for r in lf:
        print(
            f"  {r.get('earliestEntryIst')} sel={r.get('selectedAt')} {r.get('key')} "
            f"₹{r.get('pnlInr'):,.0f} peak={r.get('peakPct')}% {r.get('exitReason')}"
        )

    print("\n=== Same policy: bucket earliest entry hour (mean pnl) ===")
    buckets: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("policy") != "live_fade_CALL":
            continue
        h = (r.get("earliestEntryIst") or "00")[:2]
        buckets[h].append(float(r.get("pnlInr") or 0))
    for h in sorted(buckets):
        vals = buckets[h]
        print(f"  {h}:xx n={len(vals)} avg=₹{sum(vals)/len(vals):,.0f} max=₹{max(vals):,.0f}")

    keys = ["SENSEX:CALL:73000", "NIFTY:CALL:22700", "NIFTY:CALL:22650"]
    print("\n=== Key strikes: live_fade_CALL by earliest clock ===")
    for key in keys:
        sub = sorted(
            [r for r in rows if r.get("policy") == "live_fade_CALL" and r.get("key") == key],
            key=lambda x: x.get("earliestEntryIst") or "",
        )
        if not sub:
            print(f"  {key}: no sims")
            continue
        print(f"  {key}:")
        for r in sub[:: max(1, len(sub) // 8)][:9]:
            print(
                f"    earliest={r.get('earliestEntryIst')} sel={r.get('selectedAt')} "
                f"₹{r.get('pnlInr'):,.0f} entry={r.get('entryAt')}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
