#!/usr/bin/env python3
"""
Cross-session audit using production data only (no Yahoo).

- **Live truth**: ``/api/auto-trader/history/{date}`` (executed legs + PnL)
- **Detection → entry**: ``/api/ai/radar-funnel/{date}`` (radar rows linked to live trades)
- **Tape replay (diagnostic)**: ``/api/ai/eod-local-base-replay/{date}`` — current gates on
  archived premium tape; NOT the same as live fills (use label ``replay``).

Yahoo / index-only proxies cannot replay option gates (fade, pad, FTV); use radar ZIP sessions.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_API = "https://api.jashuvatrade.xyz/api"

# NIFTY weekly/monthly expiry hints in archived window (IST session dates).
NIFTY_EXPIRY_HINTS = frozenset(
    {
        "2026-10-14",
        "2026-10-21",
        "2026-10-28",
        "2026-11-03",
        "2026-11-04",
        "2026-11-09",
    }
)
SENSEX_EXPIRY_HINTS = frozenset(
    {
        "2026-10-16",
        "2026-10-23",
        "2026-10-30",
        "2026-11-05",
        "2026-11-06",
    }
)


def _get(api_base: str, path: str, timeout: float = 90.0) -> dict:
    delay = float(os.environ.get("NQ_API_DELAY_S", "2.5"))
    time.sleep(delay)
    try:
        with urllib.request.urlopen(f"{api_base.rstrip('/')}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as exc:
        return {"_error": str(exc)}


def _live_mix(trades: list[dict]) -> dict[str, int]:
    c: Counter = Counter()
    for t in trades:
        if str(t.get("status")) != "CLOSED":
            continue
        c[f"{t.get('symbol')}_{t.get('side')}"] += 1
    return dict(c)


def _replay_mix(trades: list[dict]) -> dict[str, int]:
    c: Counter = Counter()
    for t in trades or []:
        c[f"{t.get('symbol')}_{t.get('side')}"] += 1
    return dict(c)


def _tags(date: str) -> list[str]:
    wd = datetime.strptime(date, "%Y-%m-%d").strftime("%a")
    tags = [wd]
    if date in NIFTY_EXPIRY_HINTS:
        tags.append("NIFTY_EXPIRY")
    if date in SENSEX_EXPIRY_HINTS:
        tags.append("SENSEX_EXPIRY")
    if wd == "Mon":
        tags.append("MONDAY")
    return tags


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Call eod-local-base-replay per session (slow; premium tape on server)",
    )
    parser.add_argument(
        "--replay-only",
        default="",
        help="Comma tags: NIFTY_EXPIRY,SENSEX_EXPIRY,MONDAY (default: all sessions)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/opt/cursor/artifacts/live-expiry-archive-audit.json"),
    )
    args = parser.parse_args()

    arch = _get(args.api, f"/ai/radar-archives?limit={args.limit}")
    dates = sorted(a["date"] for a in (arch.get("archives") or []) if a.get("date"))
    replay_filter = {x.strip() for x in args.replay_only.split(",") if x.strip()}

    rows: list[dict] = []
    for date in dates:
        tags = _tags(date)
        live = _get(args.api, f"/auto-trader/history/{date}")
        closed = [
            t for t in (live.get("trades") or []) if str(t.get("status")) == "CLOSED"
        ]
        summ = live.get("summary") or {}
        net = float(
            summ.get("netPnlInr")
            or sum(float(t.get("pnlInr") or 0) for t in closed)
        )

        funnel = _get(args.api, f"/ai/radar-funnel/{date}")

        row: dict = {
            "date": date,
            "tags": tags,
            "liveLegs": len(closed),
            "liveNetInr": round(net, 2),
            "liveMix": _live_mix(live.get("trades") or []),
            "radarDetected": funnel.get("detected"),
            "radarEntered": funnel.get("entered"),
            "radarDetToEntryPct": funnel.get("detectionToEntryPct"),
            "radarEntryWinPct": funnel.get("entryWinRatePct"),
        }

        do_replay = args.replay and (
            not replay_filter or any(t in replay_filter for t in tags)
        )
        if do_replay:
            replay = _get(
                args.api,
                f"/ai/eod-local-base-replay/{date}",
                timeout=180.0,
            )
            row["replay"] = {
                "tradeCount": replay.get("tradeCount"),
                "netPnlInr": replay.get("netPnlInr"),
                "wins": replay.get("wins"),
                "losses": replay.get("losses"),
                "mix": _replay_mix(replay.get("trades")),
                "error": replay.get("_error") or replay.get("error"),
            }

        rows.append(row)

    rollup: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "liveLegs": 0, "net": 0.0})
    for r in rows:
        if "NIFTY_EXPIRY" in r["tags"]:
            key = "NIFTY_EXPIRY"
        elif "SENSEX_EXPIRY" in r["tags"]:
            key = "SENSEX_EXPIRY"
        elif "MONDAY" in r["tags"]:
            key = "OTHER_MONDAY"
        else:
            key = r["tags"][0].upper() if r["tags"] else "OTHER"
        rollup[key]["sessions"] += 1
        rollup[key]["liveLegs"] += r["liveLegs"]
        rollup[key]["net"] += float(r["liveNetInr"])

    out = {
        "api": args.api,
        "archivedSessions": len(rows),
        "liveTruthNote": (
            "Live legs exist only from ~2026-11-02 in current EC2 store; "
            "older sessions are radar-only until live was armed."
        ),
        "replayNote": (
            "eod-local-base-replay uses premium tape + current gates; "
            "not a substitute for live PnL."
        ),
        "sessions": rows,
        "liveRollups": dict(rollup),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
