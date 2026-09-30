#!/usr/bin/env python3
"""Read-only sweep helper for controlled-chase local % bands (EOD replay data).

Usage (when TRADE_STORE_DIR has radar ZIP for DATE):
  cd backend && .venv/bin/python scripts/chase_band_calibration.py 2026-09-30

Default production policy after Sep 9–17 vs Sep 30 review:
  - Tier A (base):     local <= 20%
  - Tier B (controlled chase): 20% < local <= 32%
  - Tier C (late chase): local > 32% or premium-at-high without base

See best_trade_controlled_chase_max_local_pct in config.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

BANDS = (15, 20, 25, 28, 32, 40, 50)


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-09-30"
    try:
        from app.config import get_settings
        from app.engines.eod_local_base_replay import generate_eod_local_base_replay

        report = generate_eod_local_base_replay(date)
    except Exception as exc:
        print(json.dumps({"date": date, "error": str(exc), "recommendedMaxLocalPct": 32.0}))
        return 0

    moments = report.get("moments") or report.get("entries") or []
    by_band: dict[str, int] = {str(b): 0 for b in BANDS}
    for m in moments if isinstance(moments, list) else []:
        if not isinstance(m, dict):
            continue
        local = float(m.get("ictBaseRelativeMovePct") or m.get("localBaseMovePct") or 0)
        if local <= 0:
            continue
        for b in BANDS:
            if local <= b:
                by_band[str(b)] += 1
                break

    out = {
        "date": date,
        "momentCount": len(moments) if isinstance(moments, list) else 0,
        "cumulativeLocalBandCounts": by_band,
        "recommendedMaxLocalPct": 32.0,
        "note": "32% caps Sep30-style late chase while allowing ELITE mega-vertical band to 27%.",
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
