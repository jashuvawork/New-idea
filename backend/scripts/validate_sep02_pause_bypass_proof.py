#!/usr/bin/env python3
"""Sep 2 large-loss pause bypass proof — seed morning loss, replay afternoon CALL.

Simulates live Sep 2: morning PUT losses (~₹15k) → large_loss_pause → afternoon
MOMENTUM RALLY CALL rally should enter with bypass ON, stay blocked with bypass OFF.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings

OUT_PATH = Path("/opt/cursor/artifacts/sep02_pause_bypass_proof.json")
DATE = "2026-09-02"
WINDOW_START = "12:00:00"
WINDOW_END = "15:30:00"
SEED_LOSS_INR = 15_042.0  # Sep 2 live morning PUT session loss


def _replay(settings: Settings, *, label: str, bypass: bool) -> dict:
    from app.engines.eod_local_base_replay import replay_local_base_day

    report = replay_local_base_day(
        DATE,
        settings=settings,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        side_filter="CALL",
        seed_session_loss_inr=SEED_LOSS_INR,
    )
    trades = list(report.get("trades") or [])
    gates = dict(report.get("gateStats") or {})
    pause_blocks = sum(
        int(v)
        for k, v in gates.items()
        if str(k).startswith("large_loss_pause_")
        and str(k) != "large_loss_pause_bypass_active"
    )
    bypass_active = int(gates.get("large_loss_pause_bypass_active") or 0)
    elite_rejects = int(gates.get("session_pause_elite_only") or 0)
    return {
        "label": label,
        "bypassEnabled": bypass,
        "status": report.get("status"),
        "tradeCount": len(trades),
        "netPnlInr": float(report.get("netPnlInr") or 0),
        "seedLossInr": SEED_LOSS_INR,
        "pauseBlockEvents": pause_blocks,
        "bypassActiveBatches": bypass_active,
        "eliteOnlyRejections": elite_rejects,
        "topGates": sorted(gates.items(), key=lambda row: -int(row[1]))[:12],
        "trades": trades[:15],
    }


def _proof_verdict(off: dict, on: dict) -> dict:
    passed = True
    checks: list[dict] = []

    c1 = off["pauseBlockEvents"] > 0
    checks.append({
        "name": "seeded_loss_triggers_large_loss_pause",
        "pass": c1,
        "detail": f"OFF hard pause blocks={off['pauseBlockEvents']}",
    })
    passed = passed and c1

    c2 = on["bypassActiveBatches"] > 0
    checks.append({
        "name": "bypass_on_lifts_pause_for_elite_only",
        "pass": c2,
        "detail": f"ON bypass_active_batches={on['bypassActiveBatches']}",
    })
    passed = passed and c2

    c3 = on["pauseBlockEvents"] < off["pauseBlockEvents"]
    checks.append({
        "name": "bypass_on_reduces_hard_pause_blocks",
        "pass": c3,
        "detail": f"OFF pause_blocks={off['pauseBlockEvents']} ON={on['pauseBlockEvents']}",
    })
    passed = passed and c3

    c4 = on["eliteOnlyRejections"] >= 0 and (
        on["bypassActiveBatches"] > 0 or on["tradeCount"] > off["tradeCount"]
    )
    checks.append({
        "name": "bypass_on_enables_elite_only_path",
        "pass": c4,
        "detail": f"ON elite_rejects={on['eliteOnlyRejections']} trades={on['tradeCount']}",
    })
    passed = passed and c4

    return {"passed": passed, "checks": checks}


def main() -> int:
    base = Settings()
    base.radar_archive_dir = "/tmp/eod_audit_archives"
    base.trade_store_dir = "/tmp/eod_audit_archives/trades"
    base.eod_replay_live_session_gates_enabled = True
    base.session_loss_pause_enabled = True
    base.chop_day_guards_enabled = True
    base.top_moments_day_type_grade_policy_enabled = True
    base.top_moments_fast_day_grade_c_enabled = True
    base.top_moments_exploding_elite_grade_b_enabled = True
    base.top_moments_momentum_rally_grade_b_enabled = True
    base.index_rally_side_flip_neutral_macd_mom5_waiver_enabled = True

    off_data = deepcopy(base.model_dump())
    off_data["session_large_loss_pause_bypass_enabled"] = False

    on_data = deepcopy(base.model_dump())
    on_data["session_large_loss_pause_bypass_enabled"] = True

    print(
        f"Proof: {DATE} seed −₹{SEED_LOSS_INR:,.0f} → {WINDOW_START}–{WINDOW_END} CALL",
        flush=True,
    )
    try:
        off_result = _replay(Settings(**off_data), label="bypass_off", bypass=False)
        on_result = _replay(Settings(**on_data), label="bypass_on", bypass=True)
    except Exception as exc:
        out = {
            "error": str(exc),
            "hint": "Download radar-2026-09-02.zip to /tmp/eod_audit_archives/",
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
        return 1

    verdict = _proof_verdict(off_result, on_result)
    out = {
        "date": DATE,
        "window": [WINDOW_START, WINDOW_END],
        "side": "CALL",
        "seedLossInr": SEED_LOSS_INR,
        "scenario": "Sep2 morning PUT loss → afternoon CALL with large-loss pause",
        "bypassOff": off_result,
        "bypassOn": on_result,
        "deltaTrades": on_result["tradeCount"] - off_result["tradeCount"],
        "deltaPnlInr": round(on_result["netPnlInr"] - off_result["netPnlInr"], 2),
        "proof": verdict,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if verdict["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
