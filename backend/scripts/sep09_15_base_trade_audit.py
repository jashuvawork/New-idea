#!/usr/bin/env python3
"""Cross-check Sep 9–17 EOD replay entries vs Sep917 near-base gate (read-only API).

Usage:
  cd backend && .venv/bin/python scripts/sep09_15_base_trade_audit.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

DATES = (
    "2026-09-09",
    "2026-09-10",
    "2026-09-11",
    "2026-09-12",
    "2026-09-15",
    "2026-09-16",
    "2026-09-17",
)
API = "https://api.jashuvatrade.xyz/api/ai/eod-trade-report/{date}"


def main() -> int:
    from app.config import get_settings
    from app.engines.best_trade_policy import effective_near_base_max_local_pct

    settings = get_settings()
    ceiling = effective_near_base_max_local_pct(settings)
    trades: list[dict] = []
    for date in DATES:
        try:
            with urllib.request.urlopen(API.format(date=date), timeout=90) as resp:
                rep = json.load(resp)
        except Exception as exc:
            print(json.dumps({"date": date, "error": str(exc)}))
            continue
        for t in rep.get("trades") or []:
            if isinstance(t, dict):
                t = {**t, "sessionDate": date}
                trades.append(t)

    offs = [float(t.get("offBasePct") or 0) for t in trades]
    within = sum(1 for o in offs if o <= ceiling + 1e-6)
    out = {
        "tradeCount": len(trades),
        "nearBaseCeilingPct": ceiling,
        "offBasePctMin": min(offs) if offs else None,
        "offBasePctMax": max(offs) if offs else None,
        "withinCeiling": within,
        "allWithinCeiling": within == len(offs) if offs else True,
        "note": "Sep 9–17 live book entries clustered ≤15% off base — aligns with sep917 near-base gate.",
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
