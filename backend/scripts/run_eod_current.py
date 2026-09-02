#!/usr/bin/env python3
"""EOD replay with current branch settings only (no OLD baseline)."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_full_eod_audit import (  # noqa: E402
    ARTIFACT_DIR,
    AUDIT_DATES,
    _download,
    audit_radar,
    replay_tape,
)

IST = ZoneInfo("Asia/Kolkata")
OUT = ARTIFACT_DIR / "eod_current.json"


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    days: list[dict] = []
    print("EOD — current config", flush=True)
    for date in AUDIT_DATES:
        print(f"\n[{date}]", flush=True)
        path = _download(date)
        radar = audit_radar(date, path, old=False)
        tape = replay_tape(date, old=False)
        days.append({"date": date, "radar": radar, "tape": tape})
        print(
            f"  radar full-pass {radar['fullPassPct']}% | "
            f"tape {tape['tradeCount']}t {tape['winRatePct']}% win ₹{tape['netPnlInr']:,.0f}",
            flush=True,
        )
        summary = {
            "runAt": datetime.now(IST).isoformat(),
            "branch": "cursor/top-signal-session-gaps-f5cb",
            "config": "current",
            "days": days,
        }
        t = sum(d["tape"]["tradeCount"] for d in days)
        w = sum(d["tape"]["wins"] for d in days)
        p = sum(float(d["tape"]["netPnlInr"] or 0) for d in days)
        summary["rollup"] = {
            "trades": t,
            "wins": w,
            "winRatePct": round(100 * w / t, 1) if t else 0,
            "netPnlInr": round(p),
        }
        OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nReport: {OUT}", flush=True)


if __name__ == "__main__":
    main()
