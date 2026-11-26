#!/usr/bin/env python3
"""Funnel + EOD replay validation for newSessionBase base-truth (all local radar ZIPs)."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ZIP_SRC = Path(os.environ.get("RADAR_ZIP_DIR", "/opt/cursor/artifacts/radar-zips"))
ARCHIVE_DIR = Path(os.environ.get("TRADE_STORE_DIR", "/tmp/nexusquant/trades")) / "radar_archives"
OUT_JSON = Path("/opt/cursor/artifacts/base-truth-historical-validation.json")
OUT_MD = Path("/opt/cursor/artifacts/base-truth-historical-validation.md")

BASE_BLOCKER_PREFIXES = (
    "first_lift_base_move_outside",
    "immature_local_base",
    "entry_window_local_low",
    "entry_window_weak_local",
    "explosion_near_miss",
)


def _ensure_archives() -> list[str]:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dates: list[str] = []
    for z in sorted(ZIP_SRC.glob("radar-*.zip")):
        date = z.stem.replace("radar-", "")
        dest = ARCHIVE_DIR / z.name
        if not dest.exists():
            dest.symlink_to(z.resolve())
        dates.append(date)
    aug25 = Path("/opt/cursor/artifacts/radar-aug25/radar-2026-08-25.zip")
    if aug25.is_file():
        date = "2026-08-25"
        dest = ARCHIVE_DIR / aug25.name
        if not dest.exists():
            dest.symlink_to(aug25.resolve())
        if date not in dates:
            dates.append(date)
    return sorted(set(dates))


def _iter_funnel_rows(zip_path: Path) -> list[dict[str, Any]]:
    import zipfile

    rows: list[dict[str, Any]] = []
    if not zip_path.is_file():
        return rows
    with zipfile.ZipFile(zip_path, "r") as zf:
        name = "funnel_events.jsonl"
        if name not in zf.namelist():
            return rows
        for line in zf.read(name).decode("utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def _classify_blocker(reason: str) -> str:
    r = (reason or "").lower()
    for p in BASE_BLOCKER_PREFIXES:
        if p in r:
            return p
    if "first_lift" in r:
        return "first_lift_other"
    if "chase" in r or "pad_chase" in r:
        return "chase"
    if "fade" in r or "fading" in r:
        return "fade"
    if "open" in r and "caution" in r:
        return "open_caution"
    return "other"


def _analyze_funnel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    events = Counter()
    base_blockers = Counter()
    gated = 0
    selected = 0
    entered = 0
    near_miss_msgs = Counter()
    for row in rows:
        ev = str(row.get("event") or row.get("kind") or "").upper()
        events[ev] += 1
        if ev == "GATED":
            gated += 1
            reason = str(row.get("reason") or row.get("blockReason") or "")
            base_blockers[_classify_blocker(reason)] += 1
        elif ev == "SELECTED":
            selected += 1
        elif ev == "ENTERED":
            entered += 1
        if row.get("reason") == "explosion_near_miss" or "explosion_near_miss" in str(
            row.get("message") or ""
        ):
            msg = str(row.get("message") or row.get("blockers") or "")[:120]
            near_miss_msgs[msg.split(",")[0].strip()[:80]] += 1
        sb = row.get("sessionBase")
        if isinstance(sb, dict) and sb.get("newSessionBase"):
            base_blockers["funnel_newSessionBase_stamp"] += 1
    return {
        "rowCount": len(rows),
        "events": dict(events),
        "gated": gated,
        "selected": selected,
        "entered": entered,
        "baseBlockers": dict(base_blockers),
        "topNearMissLead": near_miss_msgs.most_common(8),
    }


def _replay_day(date: str) -> dict[str, Any]:
    from app.config import _cached_get_settings

    _cached_get_settings.cache_clear()
    from app.engines.eod_local_base_replay import replay_local_base_day

    try:
        r = replay_local_base_day(date)
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:300]}
    trades = r.get("trades") or []
    at_base = 0
    for t in trades:
        pad = float(
            t.get("offBasePct")
            or t.get("baseRelPct")
            or (t.get("entryContext") or {}).get("localBaseMovePct")
            or (t.get("entryContext") or {}).get("ictBaseRelativeMovePct")
            or 999
        )
        if pad <= 22:
            at_base += 1
    return {
        "status": r.get("status"),
        "tradeCount": int(r.get("tradeCount") or len(trades)),
        "netPnlInr": r.get("netPnlInr"),
        "tradesAtBasePadLe22": at_base,
        "hasTape": r.get("status") != "no_data",
    }


def main() -> int:
    os.environ.setdefault("TRADE_STORE_DIR", "/tmp/nexusquant/trades")
    dates = _ensure_archives()
    if not dates:
        print("No radar ZIPs found under", ZIP_SRC)
        return 1

    sessions: list[dict[str, Any]] = []
    agg_funnel = Counter()
    agg_replay_legs = 0
    agg_replay_pnl = 0.0
    agg_base_trades = 0

    for i, date in enumerate(dates):
        zp = ARCHIVE_DIR / f"radar-{date}.zip"
        print(f"[{i + 1}/{len(dates)}] {date} funnel...", flush=True)
        funnel_rows = _iter_funnel_rows(zp)
        funnel = _analyze_funnel(funnel_rows)
        for k, v in funnel.get("baseBlockers", {}).items():
            agg_funnel[k] += int(v)

        print(f"  replay...", flush=True)
        replay = _replay_day(date)
        if replay.get("tradeCount"):
            agg_replay_legs += int(replay["tradeCount"])
            agg_replay_pnl += float(replay.get("netPnlInr") or 0)
            agg_base_trades += int(replay.get("tradesAtBasePadLe22") or 0)

        sessions.append(
            {
                "date": date,
                "funnel": funnel,
                "replay": replay,
                "zipBytes": zp.stat().st_size if zp.is_file() else 0,
            }
        )

    report = {
        "branch": "cursor/base-truth-lag-fix-f5cb",
        "zipSource": str(ZIP_SRC),
        "sessionCount": len(dates),
        "rollup": {
            "funnelRows": sum(s["funnel"]["rowCount"] for s in sessions),
            "funnelBaseBlockers": dict(agg_funnel),
            "replayLegs": agg_replay_legs,
            "replayNetPnlInr": round(agg_replay_pnl, 2),
            "replayTradesAtBasePadLe22": agg_base_trades,
            "daysWithReplayTrades": sum(
                1 for s in sessions if int(s["replay"].get("tradeCount") or 0) > 0
            ),
        },
        "sessions": sessions,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Base-truth historical validation (funnel + EOD replay)",
        "",
        f"- Sessions: **{len(dates)}**",
        f"- Funnel rows: **{report['rollup']['funnelRows']}**",
        f"- EOD replay legs: **{agg_replay_legs}** | net INR **{report['rollup']['replayNetPnlInr']}**",
        f"- Replay entries with pad ≤22%: **{agg_base_trades}**",
        "",
        "## Funnel base-related blockers (all days)",
        "",
    ]
    for k, v in agg_funnel.most_common():
        lines.append(f"- `{k}`: {v}")
    lines += ["", "## Per-day replay", ""]
    for s in sessions:
        rep = s["replay"]
        if rep.get("status") == "error":
            lines.append(f"- {s['date']}: replay error")
            continue
        lines.append(
            f"- {s['date']}: legs={rep.get('tradeCount')} net={rep.get('netPnlInr')} "
            f"base≤22%={rep.get('tradesAtBasePadLe22')} funnel_gated={s['funnel'].get('gated')}"
        )
    lines.append(f"\nJSON: `{OUT_JSON}`")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["rollup"], indent=2))
    print("Wrote", OUT_JSON, "and", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())