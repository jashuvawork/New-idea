#!/usr/bin/env python3
"""Replay all local radar ZIPs with current code; compare to prior report snapshot."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ZIP_SRC = Path("/cursor/stores/self/artifacts/radar-zips")
ARCHIVE_DIR = Path("/tmp/nexusquant/trades/radar_archives")
BASELINE = Path("/opt/cursor/artifacts/nifty-pre-expiry-offline-report.json")
OUT = Path("/opt/cursor/artifacts/replay-compare-new-code.json")

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


def _ensure_zips() -> list[str]:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dates: list[str] = []
    for z in sorted(ZIP_SRC.glob("radar-20*.zip")):
        date = z.stem.replace("radar-", "")
        dest = ARCHIVE_DIR / z.name
        if not dest.exists():
            dest.symlink_to(z.resolve())
        dates.append(date)
    return dates


def _replay_day(date: str, *, parity: bool) -> dict:
    os.environ["TRADE_STORE_DIR"] = "/tmp/nexusquant/trades"
    if parity:
        os.environ["NIFTY_EXPIRY_SENSEX_PARITY_ENABLED"] = "true"
    else:
        os.environ.pop("NIFTY_EXPIRY_SENSEX_PARITY_ENABLED", None)
    from app.config import get_settings

    from app.config import _cached_get_settings

    _cached_get_settings.cache_clear()
    from app.engines.eod_local_base_replay import replay_local_base_day

    r = replay_local_base_day(date)
    tr = r.get("trades") or []
    return {
        "status": r.get("status"),
        "legs": int(r.get("tradeCount") or 0),
        "netInr": r.get("netPnlInr"),
        "mix": dict(Counter(f"{t.get('symbol')}_{t.get('side')}" for t in tr)),
        "trades": [
            {
                "symbol": t.get("symbol"),
                "side": t.get("side"),
                "strike": t.get("strike"),
                "pnlInr": t.get("pnlInr"),
                "entryTime": t.get("entryTime"),
            }
            for t in tr
        ],
    }


def main() -> None:
    dates = _ensure_zips()
    baseline: dict = {}
    if BASELINE.is_file():
        baseline = json.loads(BASELINE.read_text())
    prior = {s["date"]: s.get("replay") for s in baseline.get("sessions", [])}

    rows = []
    changes_default = []
    for i, date in enumerate(dates):
        print(f"[{i+1}/{len(dates)}] {date} default...", flush=True)
        rep_def = _replay_day(date, parity=False)
        rep_par = rep_def
        if date in NIFTY_EXPIRY:
            print(f"  {date} parity on...", flush=True)
            rep_par = _replay_day(date, parity=True)
        old = prior.get(date) or {}
        changed = (
            old.get("netInr") != rep_def.get("netInr")
            or old.get("legs") != rep_def.get("legs")
            or old.get("mix") != rep_def.get("mix")
        )
        if changed:
            changes_default.append(
                {
                    "date": date,
                    "old": old,
                    "new": {
                        "legs": rep_def["legs"],
                        "netInr": rep_def["netInr"],
                        "mix": rep_def["mix"],
                    },
                }
            )
        rows.append(
            {
                "date": date,
                "niftyExpiry": date in NIFTY_EXPIRY,
                "replayDefault": rep_def,
                "replayParityOn": rep_par,
                "priorReplay": old,
                "changedVsPrior": changed,
                "parityDeltaInr": (
                    round((rep_par.get("netInr") or 0) - (rep_def.get("netInr") or 0), 2)
                    if date in NIFTY_EXPIRY
                    else None
                ),
            }
        )

    out = {
        "dates": len(dates),
        "codeBranch": "cursor/nifty-expiry-day-pack-f5cb @ main+#928",
        "parityDefaultOff": True,
        "changedVsPriorReport": changes_default,
        "rollupDefaultNetInr": round(
            sum(float(r["replayDefault"].get("netInr") or 0) for r in rows), 2
        ),
        "rollupParityOnNiftyExpiry": round(
            sum(
                float(r["replayParityOn"].get("netInr") or 0)
                for r in rows
                if r["niftyExpiry"]
            ),
            2,
        ),
        "rollupDefaultNiftyExpiry": round(
            sum(
                float(r["replayDefault"].get("netInr") or 0)
                for r in rows
                if r["niftyExpiry"]
            ),
            2,
        ),
        "sessions": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "changed": len(changes_default), "rollup": out["rollupDefaultNetInr"]}, indent=2))


if __name__ == "__main__":
    main()
