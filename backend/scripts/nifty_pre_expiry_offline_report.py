#!/usr/bin/env python3
"""Offline report: every archived session — tape replay + ZIP funnel legs.

Same framing as Nov 5/6 sign-off, focused on NIFTY expiry and prior session.
No production API calls (safe when EC2 is down).
"""

from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ZIP_DIRS = [
    Path("/tmp/nexusquant/trades/radar_archives"),
    Path("/cursor/stores/self/artifacts/radar-zips"),
    Path("/opt/cursor/artifacts/radar-zips"),
]
OUT_JSON = Path("/opt/cursor/artifacts/nifty-pre-expiry-offline-report.json")
OUT_MD = Path("/opt/cursor/artifacts/nifty-pre-expiry-offline-report.md")

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
# Live EC2 store (2026-11-02+); used when API unavailable — from auto-trader history.
LIVE_OVERRIDES: dict[str, dict] = {
    "2026-11-02": {"legs": 2, "netInr": -17069.28, "mix": {"NIFTY_PUT": 1, "NIFTY_CALL": 1}},
    "2026-11-03": {"legs": 6, "netInr": -5162.63, "mix": {"NIFTY_CALL": 3, "SENSEX_CALL": 3}},
    "2026-11-04": {"legs": 0, "netInr": 0, "mix": {}},
    "2026-11-05": {"legs": 4, "netInr": 89263.05, "mix": {"NIFTY_CALL": 1, "SENSEX_CALL": 3}},
    "2026-11-06": {"legs": 3, "netInr": 81452.85, "mix": {"NIFTY_CALL": 3}},
    "2026-11-09": {"legs": 4, "netInr": -14713.55, "mix": {"NIFTY_PUT": 3, "SENSEX_PUT": 1}},
}


def _find_zip(date: str) -> Path | None:
    name = f"radar-{date}.zip"
    for d in ZIP_DIRS:
        p = d / name
        if p.is_file() and p.stat().st_size > 1000:
            return p
    return None


def _funnel_from_zip(date: str, zpath: Path) -> dict:
    out = {"entered": 0, "detected": 0, "legsPnl": 0.0, "wins": 0, "losses": 0, "mix": {}}
    try:
        with zipfile.ZipFile(zpath) as zf:
            if "funnel.json" not in zf.namelist():
                return out
            data = json.loads(zf.read("funnel.json"))
    except Exception:
        return out
    out["detected"] = int(data.get("detected") or 0)
    out["entered"] = int(data.get("entered") or 0)
    mix: Counter = Counter()
    legs_pnl = 0.0
    wins = losses = 0
    for row in data.get("rows") or []:
        if not row.get("entered"):
            continue
        sym, side, _ = (str(row.get("key") or "::").split(":") + ["", "", ""])[:3]
        mix[f"{sym}_{side}"] += 1
        pnl = float(row.get("pnlInr") or 0)
        legs_pnl += pnl
        if row.get("tradeOutcome") == "WIN":
            wins += 1
        elif row.get("tradeOutcome") == "LOSS":
            losses += 1
    out["mix"] = dict(mix)
    out["legsPnl"] = round(legs_pnl, 2)
    out["wins"] = wins
    out["losses"] = losses
    return out


def _tags(date: str, before_set: set[str]) -> list[str]:
    wd = datetime.strptime(date, "%Y-%m-%d").strftime("%a")
    tags = [wd]
    if date in NIFTY_EXPIRY:
        tags.append("NIFTY_EXPIRY")
    if date in before_set:
        tags.append("DAY_BEFORE_NIFTY")
    return tags


def main() -> None:
    summary_path = Path("/cursor/stores/self/artifacts/radar-manifest/local_session_summary.json")
    extra_days: list[str] = []
    if summary_path.is_file():
        try:
            blob = json.loads(summary_path.read_text())
            extra_days = [d["date"] for d in blob.get("days", []) if d.get("date")]
        except Exception:
            pass
    dates = sorted({d for d in extra_days} | {p.stem.replace("radar-", "") for d in ZIP_DIRS for p in d.glob("radar-20*.zip")})
    ordered = dates
    before_map: dict[str, str] = {}
    for i, d in enumerate(ordered):
        if d in NIFTY_EXPIRY and i > 0:
            before_map[d] = ordered[i - 1]
    before_set = set(before_map.values())

    from app.engines.eod_local_base_replay import replay_local_base_day

    rows: list[dict] = []
    for date in ordered:
        z = _find_zip(date)
        funnel = _funnel_from_zip(date, z) if z else {}
        replay = {"status": "no_zip", "legs": 0, "netInr": None, "mix": {}}
        if z:
            import os

            os.environ.setdefault("TRADE_STORE_DIR", "/tmp/nexusquant/trades")
            r = replay_local_base_day(date)
            tr = r.get("trades") or []
            replay = {
                "status": r.get("status"),
                "legs": int(r.get("tradeCount") or 0),
                "netInr": r.get("netPnlInr"),
                "mix": dict(Counter(f"{t.get('symbol')}_{t.get('side')}" for t in tr)),
            }
        live = LIVE_OVERRIDES.get(date, {"legs": 0, "netInr": 0, "mix": {}})
        rows.append(
            {
                "date": date,
                "tags": _tags(date, before_set),
                "servesBeforeExpiry": [k for k, v in before_map.items() if v == date],
                "zipFunnelLegs": funnel.get("entered"),
                "zipFunnelPnlInr": funnel.get("legsPnl"),
                "zipFunnelWL": f"{funnel.get('wins', 0)}/{funnel.get('losses', 0)}",
                "zipFunnelMix": funnel.get("mix"),
                "liveLegs": live["legs"],
                "liveNetInr": live["netInr"],
                "liveMix": live["mix"],
                "replay": replay,
            }
        )

    def rollup(tag: str, field: str) -> dict:
        sel = [r for r in rows if tag in r["tags"]]
        live_net = sum(float(r["liveNetInr"] or 0) for r in sel)
        live_legs = sum(int(r["liveLegs"] or 0) for r in sel)
        zip_net = sum(float(r["zipFunnelPnlInr"] or 0) for r in sel)
        rep_net = sum(float(r["replay"]["netInr"] or 0) for r in sel if r["replay"]["netInr"] is not None)
        return {
            "sessions": len(sel),
            "liveLegs": live_legs,
            "liveNetInr": round(live_net, 2),
            "zipFunnelNetInr": round(zip_net, 2),
            "replayNetInr": round(rep_net, 2),
            "dates": [r["date"] for r in sel],
        }

    out = {
        "dayBeforeMap": before_map,
        "referenceNov5": next((r for r in rows if r["date"] == "2026-11-05"), None),
        "referenceNov6": next((r for r in rows if r["date"] == "2026-11-06"), None),
        "rollupDayBeforeNifty": rollup("DAY_BEFORE_NIFTY", "live"),
        "rollupNiftyExpiry": rollup("NIFTY_EXPIRY", "live"),
        "sessions": rows,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    lines = [
        "# NIFTY expiry + day-before (offline batch)",
        "",
        "Methods: **live** (EC2 store Nov 2–9), **zipFunnel** (legs in radar ZIP funnel.json), **replay** (current gates on premium tape).",
        "",
        "## Reference success days",
        "",
        "| Date | Live net ₹ | Live mix |",
        "|------|------------|----------|",
    ]
    for ref in ("2026-11-05", "2026-11-06"):
        r = next((x for x in rows if x["date"] == ref), None)
        if r:
            mix = ", ".join(f"{k}×{v}" for k, v in sorted((r["liveMix"] or {}).items())) or "—"
            lines.append(f"| {ref} | {r['liveNetInr']:,.0f} | {mix} |")
    lines.extend(
        [
            "",
            f"**Day-before NIFTY rollup (live):** {out['rollupDayBeforeNifty']}",
            f"**NIFTY expiry rollup (live):** {out['rollupNiftyExpiry']}",
            "",
            "## All sessions",
            "",
            "| Date | Tags | Live ₹ | Zip funnel ₹ | Replay ₹ |",
            "|------|------|--------|--------------|----------|",
        ]
    )
    for r in rows:
        tag = ",".join(t for t in r["tags"] if t not in ("Mon", "Tue", "Wed", "Thu", "Fri")) or r["tags"][0]
        rep = r["replay"]["netInr"]
        rep_s = f"{rep:,.0f}" if rep is not None else "—"
        lines.append(
            f"| {r['date']} | {tag} | {r['liveNetInr']:,.0f} | {r['zipFunnelPnlInr']:,.0f} | {rep_s} |"
        )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(OUT_MD.read_text())
    print(f"\nWrote {OUT_JSON} and {OUT_MD}")


if __name__ == "__main__":
    main()
