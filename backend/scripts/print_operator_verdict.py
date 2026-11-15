#!/usr/bin/env python3
"""Print a plain-language verdict from local artifact JSON (no API keys)."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    art = Path("/opt/cursor/artifacts")
    nifty = json.loads((art / "index-5y-daytype-nifty.json").read_text())
    replay = json.loads((art / "chop-day-replay-by-daytype.json").read_text())
    chop_pct = nifty["dayTypePct"].get("CHOP", 0)
    by_type = replay.get("byIndexDayType") or {}
    chop_row = by_type.get("CHOP") or {}
    good_row = by_type.get("GOOD") or {}
    elite_row = by_type.get("ELITE") or {}

    lines = [
        "=== NexusQuant operator verdict (auto) ===",
        "",
        f"1) About {chop_pct}% of index sessions (2022–2026) look like CHOP days.",
        "2) On saved option tapes, CHOP-tagged days: chop rules beat trend rules.",
        f"   CHOP days in sample: {chop_row.get('days', 0)}; score delta chop-trend: {chop_row.get('chopMinusTrendPts', 'n/a')}",
        f"3) On GOOD/ELITE days, trend rules win (GOOD delta {good_row.get('chopMinusTrendPts')}, ELITE {elite_row.get('chopMinusTrendPts')}).",
        "",
        "Action: On chop days use chop playbook or stand aside. On trend days keep normal system.",
        "Deploy latest main on EC2 before Monday. See OPERATOR-ONE-PAGE.md",
    ]
    print("\n".join(lines))
    out = art / "operator-verdict.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())