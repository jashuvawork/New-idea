#!/usr/bin/env python3
"""Recompute tradesAtBasePadLe22 for days listed in base-truth-historical-validation.json."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT = Path("/opt/cursor/artifacts/base-truth-historical-validation.json")


def _pad_at_base(trades: list[dict]) -> int:
    n = 0
    for t in trades:
        pad = float(t.get("offBasePct") or t.get("baseRelPct") or 999)
        if pad <= 22:
            n += 1
    return n


def main() -> int:
    os.environ.setdefault("TRADE_STORE_DIR", "/tmp/nexusquant/trades")
    if not REPORT.is_file():
        print("Missing", REPORT)
        return 1
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    from app.config import _cached_get_settings
    from app.engines.eod_local_base_replay import replay_local_base_day

    total_at_base = 0
    for i, sess in enumerate(data.get("sessions") or []):
        date = sess["date"]
        prev = int(sess.get("replay", {}).get("tradeCount") or 0)
        if prev <= 0:
            continue
        print(f"[{i + 1}] {date}...", flush=True)
        _cached_get_settings.cache_clear()
        r = replay_local_base_day(date)
        at = _pad_at_base(r.get("trades") or [])
        total_at_base += at
        sess.setdefault("replay", {})["tradesAtBasePadLe22"] = at
    data["rollup"]["replayTradesAtBasePadLe22"] = total_at_base
    REPORT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    md = Path("/opt/cursor/artifacts/base-truth-historical-validation.md")
    if md.is_file():
        text = md.read_text(encoding="utf-8")
        text = text.replace(
            "Replay entries with pad ≤22%: **0**",
            f"Replay entries with pad ≤22%: **{total_at_base}**",
        )
        md.write_text(text, encoding="utf-8")
    print("replayTradesAtBasePadLe22", total_at_base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())