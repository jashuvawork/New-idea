#!/usr/bin/env python3
"""Sep 2 afternoon replay — day-type policy + session pause bypass validation."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings

OUT_PATH = Path("/opt/cursor/artifacts/sep02_day_mode_replay.json")
DATE = "2026-09-02"
WINDOW_START = "12:00:00"
WINDOW_END = "14:30:00"


def _replay(settings: Settings, *, label: str) -> dict:
    from app.engines.eod_local_base_replay import replay_local_base_day

    report = replay_local_base_day(
        DATE,
        settings=settings,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        side_filter="CALL",
    )
    trades = list(report.get("trades") or [])
    gates = dict(report.get("gateStats") or {})
    return {
        "label": label,
        "status": report.get("status"),
        "tradeCount": len(trades),
        "netPnlInr": float(report.get("netPnlInr") or 0),
        "topGates": sorted(gates.items(), key=lambda row: -int(row[1]))[:10],
        "trades": trades[:20],
    }


def main() -> int:
    base = Settings()
    base.radar_archive_dir = "/tmp/eod_audit_archives"
    base.trade_store_dir = "/tmp/eod_audit_archives/trades"
    base.eod_replay_live_session_gates_enabled = True
    base.session_loss_pause_enabled = True
    base.session_large_loss_pause_bypass_enabled = True
    base.top_moments_day_type_grade_policy_enabled = True
    base.top_moments_fast_day_grade_c_enabled = True

    off = deepcopy(base.model_dump())
    off["top_moments_day_type_grade_policy_enabled"] = False
    off["top_moments_fast_day_grade_c_enabled"] = False
    off["session_large_loss_pause_bypass_enabled"] = False
    off["top_moments_exploding_elite_grade_b_enabled"] = False
    off["top_moments_momentum_rally_grade_b_enabled"] = False

    on = deepcopy(base.model_dump())
    on["top_moments_day_type_grade_policy_enabled"] = True
    on["top_moments_fast_day_grade_c_enabled"] = True
    on["session_large_loss_pause_bypass_enabled"] = True

    print(f"Replay {DATE} {WINDOW_START}–{WINDOW_END} CALL (requires radar archive)...", flush=True)
    try:
        off_result = _replay(Settings(**off), label="policy_off")
        on_result = _replay(Settings(**on), label="policy_on")
    except Exception as exc:
        out = {"error": str(exc), "hint": "Download radar-2026-09-02.zip to /tmp/eod_audit_archives/"}
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
        return 1

    out = {
        "date": DATE,
        "window": [WINDOW_START, WINDOW_END],
        "side": "CALL",
        "off": off_result,
        "on": on_result,
        "deltaPnlInr": round(on_result["netPnlInr"] - off_result["netPnlInr"], 2),
        "deltaTrades": on_result["tradeCount"] - off_result["tradeCount"],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
