#!/usr/bin/env python3
"""Run N× exit audit for a session date (local store or production API).

Examples:
  cd backend && .venv/bin/python scripts/nx_exit_audit.py 2026-11-10
  cd backend && .venv/bin/python scripts/nx_exit_audit.py --api 2026-11-10
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

API = "https://api.jashuvatrade.xyz/api/ai/eod-nx-exit-audit/{date}"


def main() -> int:
    parser = argparse.ArgumentParser(description="N× LTP exit vs post-exit tape audit")
    parser.add_argument("date", help="Session date YYYY-MM-DD")
    parser.add_argument(
        "--api",
        action="store_true",
        help="Call production API instead of local trade store + tape",
    )
    parser.add_argument(
        "--early-only",
        action="store_true",
        help="Print only trades that exited before later N× on tape",
    )
    args = parser.parse_args()

    if args.api:
        try:
            with urllib.request.urlopen(API.format(date=args.date), timeout=120) as resp:
                rep = json.load(resp)
        except Exception as exc:
            print(json.dumps({"date": args.date, "error": str(exc)}))
            return 1
    else:
        from app.engines.nx_exit_audit import generate_nx_exit_audit

        rep = generate_nx_exit_audit(args.date)

    if args.early_only:
        out = {
            "date": rep.get("date"),
            "earlyExitMissCount": rep.get("earlyExitMissCount"),
            "earlyExits": rep.get("earlyExits", []),
        }
        print(json.dumps(out, indent=2, default=str))
    else:
        print(json.dumps(rep, indent=2, default=str))

    misses = int(rep.get("earlyExitMissCount") or 0)
    return 2 if misses > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
