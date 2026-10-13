#!/usr/bin/env python3
"""Re-run every archived session's live entries through the current book + exit engine.

The premium tape has no volume, so a tape-only replay cannot rebuild the elite /
top-moment scores that chose live entries. This script anchors entries on the live
funnel instead (``ENTERED`` events, optionally ``RANKED_OUT`` legs whose leader was on
the other side — the slots the dual-side book opens) and lets the current rules decide:
side slots, explosion stop cooldown, open-side confirmation, ``check_explosion_entry``
(chart / breadth / Smart Ichimoku + index-rally bypass), session gates, daily loss
stop, and the explosion exit engine walking the premium tape.

Usage (from backend/):
    PYTHONPATH=. .venv/bin/python scripts/replay_anchored_live_entries.py \
        --archives /tmp/hist/zips --out /opt/cursor/artifacts/anchored_replay
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from replay_current_book_all_sessions import _settings  # noqa: E402

RANKED_OUT_DEDUPE_SECONDS = 300
TIER_LOOKBACK_SECONDS = 120
TIER_RANK = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}
RUNS = (
    ("before_oct13", "entered"),
    ("current", "entered"),
    ("current", "entered+opposite"),
)


def _funnel_events(zip_path: Path) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(zip_path) as zf, zf.open("funnel_events.jsonl") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (KeyError, FileNotFoundError, zipfile.BadZipFile):
        return []


def _ts(raw: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _best_recent_tier(seen: list[tuple[datetime, str]], ts: datetime) -> str | None:
    recent = [t for at, t in seen if 0 <= (ts - at).total_seconds() <= TIER_LOOKBACK_SECONDS]
    return max(recent, key=lambda t: TIER_RANK.get(t, 0)) if recent else None


def live_anchors(events: list[dict[str, Any]], *, with_opposite: bool) -> list[dict[str, Any]]:
    """Live entries (+ optional opposite-side ranked-out legs) as replay anchors."""
    tiers: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    last_ranked: dict[str, datetime] = {}
    anchors: list[dict[str, Any]] = []
    for ev in sorted(events, key=lambda e: str(e.get("ts") or "")):
        key = str(ev.get("key") or "")
        kind = ev.get("event")
        ts = _ts(ev.get("ts"))
        if not key or ts is None:
            continue
        if kind == "DETECTED" and ev.get("tier"):
            tiers[key].append((ts, str(ev["tier"]).upper()))
            continue
        base = {
            "symbol": ev.get("symbol"),
            "side": ev.get("side"),
            "strike": ev.get("strike"),
            "ts": ts,
            "tier": _best_recent_tier(tiers[key], ts),
        }
        if kind == "ENTERED":
            anchors.append({
                **base,
                "source": "live_entered",
                "tradeId": ev.get("tradeId"),
                "liveGated": True,
            })
        elif with_opposite and kind == "RANKED_OUT":
            leader_side = str(ev.get("leaderKey") or "::").split(":")[1]
            if leader_side == str(ev.get("side") or "") or ev.get("causalGrade") not in {"S", "A"}:
                continue
            prev = last_ranked.get(key)
            if prev is not None and (ts - prev).total_seconds() < RANKED_OUT_DEDUPE_SECONDS:
                continue
            last_ranked[key] = ts
            anchors.append({**base, "source": "ranked_out_opposite"})
    return anchors


def live_closes(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(ev.get("tradeId")): ev
        for ev in events
        if ev.get("event") == "CLOSED" and ev.get("tradeId")
    }


def _run(date: str, profile: str, variant: str, archives: Path, store: Path,
         events: list[dict[str, Any]]) -> dict[str, Any]:
    from app.engines.eod_local_base_replay import replay_local_base_day

    anchors = live_anchors(events, with_opposite=variant == "entered+opposite")
    closes = live_closes(events)
    s = _settings(profile, archives, store)
    t0 = time.time()
    report = replay_local_base_day(date, settings=s, anchored_entries=anchors)
    trades = list(report.get("trades") or [])
    by_anchor = {(t.get("anchorTs"), f"{t['symbol']}:{t['side']}:{t['strike']:g}"): t for t in trades}
    rows = []
    for a, out in zip(anchors, report.get("anchors") or []):
        trade = by_anchor.get((out["ts"], out["key"])) if out["outcome"] == "entered" else None
        live = closes.get(str(a.get("tradeId"))) if a.get("tradeId") else None
        rows.append({
            **out,
            "replayEntryPremium": trade.get("entryPremium") if trade else None,
            "replayPnlPoints": (
                round(float(trade["exitPremium"]) - float(trade["entryPremium"]), 2) if trade else None
            ),
            "replayPnlInr": trade.get("pnlInr") if trade else None,
            "replayExit": f"{trade['exitAt']} {trade['exitReason']}" if trade else None,
            "replayPeakPct": trade.get("peakPct") if trade else None,
            "concurrentWith": trade.get("concurrentWith") if trade else None,
            "livePnlPoints": round(float(live["pnlPoints"]), 2) if live else None,
            "livePnlInr": round(float(live["pnlInr"])) if live else None,
            "liveExit": (
                f"{str(live.get('ts'))[11:19]} {live.get('exitReason')}" if live else None
            ),
        })
    pnl = [float(t.get("pnlInr") or 0) for t in trades]
    return {
        "date": date,
        "profile": profile,
        "variant": variant,
        "status": report.get("status"),
        "seconds": round(time.time() - t0, 1),
        "anchorCount": len(anchors),
        "tradeCount": len(trades),
        "wins": sum(1 for p in pnl if p > 0),
        "netPnlInr": round(sum(pnl)),
        "concurrentLegs": sum(1 for t in trades if t.get("concurrentWith")),
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
        "exitReasons": dict(Counter(str(t.get("exitReason")) for t in trades)),
        "anchors": rows,
        "trades": trades,
    }


def _summary(days: list[dict[str, Any]]) -> dict[str, Any]:
    trades = [t for d in days for t in d["trades"]]
    pnl = [float(t.get("pnlInr") or 0) for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    equity = peak = max_dd = 0.0
    for d in days:
        equity += d["netPnlInr"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    by_side: dict[str, dict[str, float]] = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in trades:
        row = by_side[f"{t['symbol']}:{t['side']}"]
        row["trades"] += 1
        row["wins"] += 1 if float(t.get("pnlInr") or 0) > 0 else 0
        row["pnl"] += float(t.get("pnlInr") or 0)
    blocked = Counter(
        r["outcome"] for d in days for r in d["anchors"]
        if r["outcome"] != "entered" and r.get("source") == "live_entered"
    )
    paired = [
        r for d in days for r in d["anchors"]
        if r.get("livePnlPoints") is not None and r.get("replayPnlPoints") is not None
    ]
    return {
        "sessions": len(days),
        "trades": len(trades),
        "winRatePct": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
        "netPnlInr": round(sum(pnl)),
        "profitFactor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
        "avgWinInr": round(sum(wins) / len(wins)) if wins else 0,
        "avgLossInr": round(sum(losses) / len(losses)) if losses else 0,
        "maxDrawdownInr": round(max_dd),
        "greenSessions": sum(1 for d in days if d["netPnlInr"] > 0),
        "redSessions": sum(1 for d in days if d["netPnlInr"] < 0),
        "concurrentLegs": sum(d["concurrentLegs"] for d in days),
        "liveEntriesBlocked": dict(blocked.most_common()),
        "exitReasons": dict(Counter(str(t.get("exitReason")) for t in trades).most_common()),
        "bySideIndex": {k: {**v, "pnl": round(v["pnl"])} for k, v in sorted(by_side.items())},
        "pairedLiveVsReplay": {
            "count": len(paired),
            "livePointsSum": round(sum(r["livePnlPoints"] for r in paired), 1),
            "replayPointsSum": round(sum(r["replayPnlPoints"] for r in paired), 1),
            "replayBetter": sum(1 for r in paired if r["replayPnlPoints"] > r["livePnlPoints"] + 0.5),
            "replayWorse": sum(1 for r in paired if r["replayPnlPoints"] < r["livePnlPoints"] - 0.5),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archives", default="/tmp/hist/zips")
    ap.add_argument("--out", default="/opt/cursor/artifacts/anchored_replay")
    ap.add_argument("--dates", default="")
    ap.add_argument(
        "--aggregate",
        action="store_true",
        help="only rebuild summary.json from the per-session files already in --out",
    )
    args = ap.parse_args()

    archives = Path(args.archives)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    store = Path("/tmp/nexusquant/replay_store")
    store.mkdir(parents=True, exist_ok=True)
    dates = [d for d in args.dates.split(",") if d] or sorted(
        p.stem.replace("radar-", "") for p in archives.glob("radar-*.zip")
    )
    rows: list[dict[str, Any]] = []
    if args.aggregate:
        rows = [
            json.loads(p.read_text())
            for p in sorted(out.glob("20*.json"))
            if p.name.split(".")[0] in dates
        ]
        dates = []
    for date in dates:
        events = _funnel_events(archives / f"radar-{date}.zip")
        for profile, variant in RUNS:
            day = _run(date, profile, variant, archives, store, events)
            rows.append(day)
            (out / f"{date}.{profile}.{variant}.json").write_text(
                json.dumps(day, indent=2, default=str)
            )
            print(
                f"{date} {profile:12s} {variant:16s} {day['status']:8s} anchors={day['anchorCount']:3d} "
                f"trades={day['tradeCount']:2d} wins={day['wins']:2d} pnl=₹{day['netPnlInr']:>9,} "
                f"conc={day['concurrentLegs']} {day['outcomes']} ({day['seconds']}s)",
                flush=True,
            )
    summary = {
        "runAt": datetime.now().isoformat(),
        "runs": {
            f"{profile}|{variant}": _summary(
                [r for r in rows if r["profile"] == profile and r["variant"] == variant
                 and r["status"] == "ok"]
            )
            for profile, variant in RUNS
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
