#!/usr/bin/env python3
"""Batch: live store + premium-tape replay for all archived sessions.

Highlights NIFTY expiry and the **prior archived session** (day-before), same method as
Nov 5/6 sign-off: live legs first, then local ``replay_local_base_day`` on radar ZIP.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from collections import Counter
from datetime import datetime

API = os.environ.get("NQ_API", "https://api.jashuvatrade.xyz/api")
STORE = Path(os.environ.get("TRADE_STORE_DIR", "/tmp/nexusquant/trades"))
ZIP_DIR = STORE / "radar_archives"
# Production safety: never burst heavy endpoints (replay, EOD, scorecard).
REQUEST_DELAY_S = float(os.environ.get("NQ_API_DELAY_S", "2.5"))

NIFTY_EXPIRY = frozenset(
    {
        "2026-10-14",
        "2026-10-21",
        "2026-10-28",
        "2026-11-03",
        "2026-11-04",
        "2026-11-09",
    }
)


def _get(path: str, timeout: float = 60.0) -> dict:
    time.sleep(REQUEST_DELAY_S)
    try:
        with urllib.request.urlopen(f"{API.rstrip('/')}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as exc:
        return {"_error": str(exc)}


def _download_zip(date: str) -> Path | None:
    ZIP_DIR.mkdir(parents=True, exist_ok=True)
    dest = ZIP_DIR / f"radar-{date}.zip"
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    try:
        with urllib.request.urlopen(
            f"{API}/ai/radar-archives/{date}", timeout=180
        ) as r:
            dest.write_bytes(r.read())
        return dest
    except Exception as exc:
        print(f"  zip download skip {date}: {exc}", flush=True)
        return None


def _day_before_nifty(archived_dates: list[str]) -> dict[str, str]:
    """Map NIFTY expiry date -> previous session in archive (IST trading gap aware)."""
    ordered = sorted(archived_dates)
    prev_map: dict[str, str] = {}
    for i, d in enumerate(ordered):
        if d not in NIFTY_EXPIRY or i == 0:
            continue
        prev_map[d] = ordered[i - 1]
    return prev_map


def _live_row(date: str) -> dict:
    live = _get(f"/auto-trader/history/{date}")
    closed = [t for t in live.get("trades") or [] if t.get("status") == "CLOSED"]
    s = live.get("summary") or {}
    net = float(
        s.get("netPnlInr") or sum(float(t.get("pnlInr") or 0) for t in closed)
    )
    mix = Counter(f"{t.get('symbol')}_{t.get('side')}" for t in closed)
    nifty_ce = sum(
        float(t.get("pnlInr") or 0)
        for t in closed
        if t.get("symbol") == "NIFTY" and t.get("side") == "CALL"
    )
    nifty_pe = sum(
        float(t.get("pnlInr") or 0)
        for t in closed
        if t.get("symbol") == "NIFTY" and t.get("side") == "PUT"
    )
    return {
        "liveLegs": len(closed),
        "liveNetInr": round(net, 2),
        "liveMix": dict(mix),
        "liveNiftyCeInr": round(nifty_ce, 2),
        "liveNiftyPeInr": round(nifty_pe, 2),
        "liveWin": net > 0 and len(closed) > 0,
    }


def _replay_row(date: str) -> dict:
    from app.engines.eod_local_base_replay import replay_local_base_day

    r = replay_local_base_day(date)
    trades = r.get("trades") or []
    mix = Counter(f"{t.get('symbol')}_{t.get('side')}" for t in trades)
    net = float(r.get("netPnlInr") or 0)
    return {
        "replayStatus": r.get("status"),
        "replayLegs": int(r.get("tradeCount") or 0),
        "replayNetInr": round(net, 2),
        "replayMix": dict(mix),
        "replayWin": net > 0 and len(trades) > 0,
    }


def main() -> None:
    arch = _get("/ai/radar-archives?limit=120")
    dates = sorted(a["date"] for a in arch.get("archives") or [] if a.get("date"))
    before = _day_before_nifty(dates)
    day_before_set = set(before.values())

    rows: list[dict] = []
    for date in dates:
        print(f"processing {date}...", flush=True)
        wd = datetime.strptime(date, "%Y-%m-%d").strftime("%a")
        tags: list[str] = [wd]
        if date in NIFTY_EXPIRY:
            tags.append("NIFTY_EXPIRY")
        if date in day_before_set:
            tags.append("DAY_BEFORE_NIFTY")
        row = {
            "date": date,
            "tags": tags,
            "beforeNiftyExpiryOn": (
                [k for k, v in before.items() if v == date] or None
            ),
        }
        row.update(_live_row(date))
        if _download_zip(date) is not None:
            row.update(_replay_row(date))
        else:
            row.update(
                {
                    "replayStatus": "no_zip",
                    "replayLegs": 0,
                    "replayNetInr": 0,
                    "replayMix": {},
                    "replayWin": False,
                }
            )
        rows.append(row)

    def _rollup(tag: str) -> dict:
        sel = [r for r in rows if tag in r["tags"]]
        live_net = sum(r["liveNetInr"] for r in sel)
        live_legs = sum(r["liveLegs"] for r in sel)
        rep_net = sum(r["replayNetInr"] for r in sel)
        rep_legs = sum(r["replayLegs"] for r in sel)
        live_wins = sum(1 for r in sel if r["liveWin"])
        rep_wins = sum(1 for r in sel if r["replayWin"])
        return {
            "sessions": len(sel),
            "liveLegs": live_legs,
            "liveNetInr": round(live_net, 2),
            "liveGreenDays": live_wins,
            "replayLegs": rep_legs,
            "replayNetInr": round(rep_net, 2),
            "replayGreenDays": rep_wins,
            "dates": [r["date"] for r in sel],
        }

    out = {
        "archivedSessions": len(rows),
        "dayBeforeMap": before,
        "niftyExpiry": _rollup("NIFTY_EXPIRY"),
        "dayBeforeNifty": _rollup("DAY_BEFORE_NIFTY"),
        "referenceSuccess": {
            "2026-11-05": next((r for r in rows if r["date"] == "2026-11-05"), {}),
            "2026-11-06": next((r for r in rows if r["date"] == "2026-11-06"), {}),
        },
        "sessions": rows,
    }
    out_path = Path("/opt/cursor/artifacts/nifty-pre-expiry-batch.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("\n=== DAY BEFORE NIFTY (live + replay) ===")
    for r in rows:
        if "DAY_BEFORE_NIFTY" not in r["tags"]:
            continue
        print(
            f"{r['date']} → before {r['beforeNiftyExpiryOn']} | "
            f"live {r['liveLegs']} ₹{r['liveNetInr']:,.0f} {r['liveMix']} | "
            f"replay {r['replayLegs']} ₹{r['replayNetInr']:,.0f} {r['replayMix']}"
        )
    print("\n=== NIFTY EXPIRY (live + replay) ===")
    for r in rows:
        if "NIFTY_EXPIRY" not in r["tags"]:
            continue
        print(
            f"{r['date']} | live {r['liveLegs']} ₹{r['liveNetInr']:,.0f} "
            f"NIFTY CE/PE ₹{r['liveNiftyCeInr']:,.0f}/{r['liveNiftyPeInr']:,.0f} | "
            f"replay {r['replayLegs']} ₹{r['replayNetInr']:,.0f} {r['replayMix']}"
        )
    print("\nRollups:", json.dumps({k: out[k] for k in ("niftyExpiry", "dayBeforeNifty")}, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
