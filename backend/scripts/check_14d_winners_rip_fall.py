#!/usr/bin/env python3
"""Verify last-N-day winners would not hit explosion_session_rip_fall_entry_blocked.

Uses live entry mom5 from trade entryContext when session peak/low unavailable offline.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engines.explosion_entry_guards import explosion_session_rip_fall_entry_blocked
from app.models.schemas import Side
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _event_from_trade(t: dict) -> object:
    from types import SimpleNamespace

    meta = (t.get("entryContext") or {}).get("liveEntryScoreMeta") or {}
    return SimpleNamespace(
        symbol=t.get("symbol"),
        side=Side(t["side"]) if t.get("side") in ("CALL", "PUT") else t.get("side"),
        strike=float(t.get("strike") or 0),
        premium=float(t.get("entryPremium") or 0),
        velocity_3s=float(meta.get("velocity3s") or 0),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--api",
        default="http://65.0.136.146:8000/api/auto-trader/history/trades/closed?limit=200",
    )
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--out", default="/opt/cursor/artifacts/winners-rip-fall-check.json")
    args = ap.parse_args()
    with urllib.request.urlopen(args.api, timeout=30) as resp:
        trades = json.load(resp).get("trades") or []
    cut = datetime.now(IST) - timedelta(days=args.days)
    settings = settings_mock()
    rows: list[dict] = []
    for t in trades:
        pnl = float(t.get("pnlInr") or 0)
        if pnl <= 0:
            continue
        closed = t.get("closedAt") or ""
        try:
            dt = datetime.fromisoformat(closed.replace("Z", "+00:00")).astimezone(IST)
        except (TypeError, ValueError):
            continue
        if dt < cut:
            continue
        ev = _event_from_trade(t)
        meta_ec = (t.get("entryContext") or {}).get("liveEntryScoreMeta") or {}
        mom5 = meta_ec.get("premiumMomentum5Pct")
        blocked, reason, rip_meta = explosion_session_rip_fall_entry_blocked(
            ev,
            settings=settings,
            momentum5_pct=float(mom5) if mom5 is not None else None,
        )
        rows.append({
            "closedAt": closed,
            "leg": f"{t.get('symbol')} {t.get('side')} {t.get('strike')}",
            "pnlInr": pnl,
            "entryPremium": t.get("entryPremium"),
            "mom5": mom5,
            "ripFallWouldBlock": blocked,
            "reason": reason,
            "ripMeta": rip_meta,
        })
    blocked_n = sum(1 for r in rows if r["ripFallWouldBlock"])
    out = {"days": args.days, "winners": len(rows), "wouldBlock": blocked_n, "rows": rows}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps({"winners": len(rows), "wouldBlock": blocked_n, "out": args.out}))
    return 1 if blocked_n else 0


if __name__ == "__main__":
    raise SystemExit(main())