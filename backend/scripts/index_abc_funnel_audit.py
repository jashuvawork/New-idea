#!/usr/bin/env python3
"""Classify production funnel gates for Index PR stack (#936–#940) + ABC open policy."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

ABC_OPEN = re.compile(
    r"open_caution|open_index_lane|open_side|open_setup|open_structural",
    re.I,
)
INDEX_RANK_HINTS = re.compile(
    r"index_|dominant|flip|aligned_book|participation|slide_capture_lane",
    re.I,
)
FTV_ELITE = re.compile(
    r"elite_|ftv_|explosion_near_miss|exec_premium",
    re.I,
)


def _load_funnel(path: Path | None, date: str, api_base: str) -> dict:
    if path and path.exists():
        return json.loads(path.read_text())
    url = f"{api_base.rstrip('/')}/api/ai/radar-funnel/{date}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        return json.loads(resp.read())


def _parse_ts(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except (TypeError, ValueError):
        return None


def _in_open_caution(dt: datetime) -> bool:
    m = dt.hour * 60 + dt.minute
    return (9 * 60 + 15) <= m < (9 * 60 + 45)


def _in_side_align(dt: datetime) -> bool:
    m = dt.hour * 60 + dt.minute
    return (9 * 60 + 15) <= m < (9 * 60 + 30)


def audit(funnel: dict) -> dict:
    gate_counts: Counter[str] = Counter()
    abc_counts: Counter[str] = Counter()
    by_window: Counter[str] = Counter()
    contracts_abc: defaultdict[str, int] = defaultdict(int)
    rows = funnel.get("rows") or []
    for row in rows:
        key = str(row.get("key") or "")
        for ev in row.get("timeline") or []:
            if ev.get("event") != "GATED" and not str(ev.get("stage") or "").endswith("BLOCK"):
                continue
            reason = str(ev.get("reason") or "unknown")
            gate_counts[reason] += 1
            ts = _parse_ts(str(ev.get("ts") or ""))
            if ts and _in_open_caution(ts):
                by_window["open_caution_0915_0945"] += 1
                if _in_side_align(ts):
                    by_window["side_align_0915_0930"] += 1
                else:
                    by_window["open_lane_0930_0945"] += 1
            else:
                by_window["outside_open_caution"] += 1
            if ABC_OPEN.search(reason):
                abc_counts[reason] += 1
                contracts_abc[key] += 1
    return {
        "date": funnel.get("date"),
        "summary": {
            k: funnel.get(k)
            for k in (
                "detected",
                "blocked",
                "selected",
                "entered",
                "closedWins",
            )
        },
        "gateEvents": sum(gate_counts.values()),
        "topGates": gate_counts.most_common(25),
        "abcGates": abc_counts.most_common(20),
        "abcGateSharePct": round(
            sum(abc_counts.values()) / max(1, sum(gate_counts.values())) * 100, 1
        ),
        "windowSplit": dict(by_window),
        "contractsMostAbcBlocks": sorted(
            contracts_abc.items(), key=lambda x: -x[1]
        )[:12],
        "ftvEliteGateSharePct": round(
            sum(
                n
                for r, n in gate_counts.items()
                if FTV_ELITE.search(r)
            )
            / max(1, sum(gate_counts.values()))
            * 100,
            1,
        ),
        "prStackNotes": {
            "936_ABC": "Open side-align ends 09:30; PUT needs slide off high (ABC-B); slide lane PM (ABC-C)",
            "937": "Aligned book — selector rank (not in funnel GATED reasons)",
            "938_939": "Flip risk — selector rank (not funnel hard gate)",
            "940": "Participation — selector rank + HUD (not funnel hard gate)",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-11-13")
    parser.add_argument("--funnel", type=Path, default=None)
    parser.add_argument(
        "--api",
        default="https://api.jashuvatrade.xyz",
        help="API base for live funnel fetch",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/opt/cursor/artifacts/index-abc-funnel-audit.json"),
    )
    args = parser.parse_args()
    funnel = _load_funnel(args.funnel, args.date, args.api)
    report = audit(funnel)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
