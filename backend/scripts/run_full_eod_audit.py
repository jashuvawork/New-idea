#!/usr/bin/env python3
"""Full EOD audit — radar gate pass rates + premium-tape replay OLD vs NEW."""

from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.eod_local_base_replay import replay_local_base_day
from app.engines.missed_trade_explainer import _gate_checks
from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence
from app.models.schemas import AutoTraderState, Breadth, MarketPhase, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://jashuvatrade.xyz"
ARCHIVE_DIR = Path("/tmp/eod_audit_archives")
ARTIFACT_DIR = Path("/opt/cursor/artifacts")
OUT_PATH = ARTIFACT_DIR / "eod_full_audit.json"

AUDIT_DATES = ["2026-08-19", "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"]

OLD_SETTINGS = {
    "aggressive_min_explosion_score": 45,
    "first_lift_trade_min_score": 62.0,
    "first_lift_trade_min_quality": 65.0,
    "pretrade_min_rank_score": 65.0,
    "best_trades_min_rank_score": 62.0,
    "grade_a_ftv_first_lift_min_explosion_score": 28.0,
    "bullish_local_base_pad_min_explosion_score": 12.0,
    "explosion_top_must_take_min_score": 62.0,
    "top_signal_session_lift_enabled": False,
    "last_n_top_signal_bypass_enabled": False,
    "whipsaw_top_signal_bypass_enabled": False,
    "controlled_cap_top_signal_bypass_enabled": False,
}

# Modules bind ``get_settings`` at import time — patch each copy, not only app.config.
PATCH_TARGETS = (
    "app.config.get_settings",
    "app.engines.eod_local_base_replay.get_settings",
    "app.services.radar_archive.get_settings",
    "app.services.radar_learning.get_settings",
    "app.engines.missed_trade_explainer.get_settings",
    "app.engines.pretrade_validator.get_settings",
    "app.engines.ict_breakout_monitor.get_settings",
    "app.engines.bullish_local_base.get_settings",
    "app.engines.early_catch_gates.get_settings",
    "app.engines.top_signal_session_lift.get_settings",
    "app.engines.chop_day_guards.get_settings",
    "app.engines.whipsaw_guards.get_settings",
    "app.engines.worst_day_guard.get_settings",
    "app.engines.expiry_day_guards.get_settings",
    "app.engines.elite_never_block.get_settings",
    "app.engines.top_ftv_v_expiry_bypass.get_settings",
    "app.engines.grade_a_ftv_capture.get_settings",
    "app.engines.pad_lane_capture.get_settings",
    "app.engines.building_ftv_gates.get_settings",
    "app.engines.local_base_chart_bypass.get_settings",
    "app.engines.explosion_profit.get_settings",
    "app.engines.capital_allocator.get_settings",
)


def _download(date: str) -> Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / f"radar-{date}.zip"
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    print(f"  downloading {date}...", flush=True)
    urllib.request.urlretrieve(f"{BASE_URL}/api/ai/radar-archives/{date}", dest)
    return dest


def _cfg(old: bool) -> Settings:
    c = Settings()
    c.radar_archive_dir = str(ARCHIVE_DIR)
    c.trade_store_dir = str(ARCHIVE_DIR.parent / "trades")
    if old:
        for k, v in OLD_SETTINGS.items():
            setattr(c, k, v)
    return c


def _with_cfg(cfg: Settings):
    stack = ExitStack()
    for target in PATCH_TARGETS:
        stack.enter_context(patch(target, return_value=cfg))
    return stack


def _has_tape(path: Path) -> bool:
    with zipfile.ZipFile(path) as zf:
        return "premium_tape.jsonl" in zf.namelist()


def _snap(row: dict) -> SymbolSnapshot:
    ctx, alert = row.get("context") or {}, row.get("alert") or {}
    sc = ctx.get("spotChart") or {}
    return SymbolSnapshot(
        symbol=str(row.get("symbol") or alert.get("symbol") or "SENSEX"),
        timestamp=datetime.fromisoformat(str(row.get("ts") or "2026-08-27T12:00:00+05:30")),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=float(ctx.get("spot") or 0),
        breadth=Breadth(bias=str((ctx.get("breadth") or {}).get("bias") or "NEUTRAL")),
        spotChart=SpotChart(direction=str(sc.get("direction") or "NEUTRAL"), spot=float(ctx.get("spot") or 0)),
        tradeQualityScore=float(ctx.get("tradeQualityScore") or 55),
        explosionAlerts=[alert],
    )


def _ftv(alert: dict) -> tuple[bool, str]:
    ev = {
        "mode": "explosion",
        "tier": str(alert.get("tier") or "").upper(),
        "explosionScore": float(alert.get("explosionScore") or 0),
        "flatVerticalQuality": float(alert.get("flatVerticalQuality") or 55),
        "velocity3s": float(alert.get("velocity3s") or 0),
        "velocity9s": float(alert.get("velocity9s") or 0),
        "localBaseMovePct": float(alert.get("localBaseMovePct") or alert.get("ictBaseRelativeMovePct") or 0),
        "firstLift": bool(alert.get("ictFirstLift")),
        "flatThenVertical": bool(alert.get("ictFlatThenVertical")),
        "activeBreakout": bool(alert.get("ictBreakout")),
        "armedBaseLaunch": bool(alert.get("ictArmedBaseLaunch")),
        "bullishLocalBaseActive": bool(alert.get("bullishLocalBaseActive")),
        "fastBullishLocalBase": bool(alert.get("fastBullishLocalBaseReady")),
        "volumeAwaken": bool(alert.get("volumeAwaken")),
        "orderflowPositive": bool(alert.get("optionCvdBuying")),
        "vRipReady": bool(alert.get("ictVRipReady")),
        "buildingRipReady": bool(alert.get("ictBuildingRipReady")),
        "earlyRadarPadCapture": bool(alert.get("earlyRadarPadCapture")),
        "flatVerticalGrade": str(alert.get("flatVerticalGrade") or ""),
    }
    ranking = rank_trade_evidence(ev)
    d = ftv_authorization_policy(ev, ranking, snapshot_available=True, atm_itm_allowed=True, require_allocation_rank_one=False)
    return d.allowed, str(d.mode or d.reason)


def audit_radar(date: str, path: Path, *, old: bool) -> dict[str, Any]:
    cfg = _cfg(old)
    with _with_cfg(cfg):
        with zipfile.ZipFile(path) as zf:
            rows = json.loads(zf.read("all_radars.json"))
    rank = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}
    moments = [r for r in rows if rank.get(str((r.get("alert") or {}).get("tier", "")).upper(), 0) >= 3]
    n = len(moments)
    state = AutoTraderState()
    gp = fp = full = 0
    blockers: Counter[str] = Counter()
    for row in moments:
        alert = row.get("alert") or {}
        sym = str(row.get("symbol") or "SENSEX")
        snap = _snap(row)
        with _with_cfg(cfg):
            gate = _gate_checks(sym, snap, alert, state, {sym: snap})
            ok_ftv, ftv_mode = _ftv(alert)
        g_ok = bool(gate.get("wouldPass"))
        if g_ok:
            gp += 1
        else:
            blockers[gate.get("primaryBlocker") or "unknown"] += 1
        if ok_ftv:
            fp += 1
        elif g_ok:
            blockers[f"ftv:{ftv_mode}"] += 1
        if g_ok and ok_ftv:
            full += 1
    return {
        "date": date,
        "config": "OLD" if old else "NEW",
        "topMoments": n,
        "gatePassPct": round(100 * gp / n, 1) if n else 0,
        "ftvPassPct": round(100 * fp / n, 1) if n else 0,
        "fullPassPct": round(100 * full / n, 1) if n else 0,
        "topBlockers": blockers.most_common(8),
    }


def replay_tape(date: str, *, old: bool) -> dict[str, Any]:
    cfg = _cfg(old)
    with _with_cfg(cfg):
        rep = replay_local_base_day(date, settings=cfg)
    taken = rep.get("trades") or []
    wins = sum(1 for t in taken if float(t.get("pnlInr") or 0) > 0)
    return {
        "date": date,
        "config": "OLD" if old else "NEW",
        "status": rep.get("status"),
        "tradeCount": int(rep.get("tradeCount") or len(taken)),
        "wins": wins,
        "winRatePct": round(100 * wins / len(taken), 1) if taken else 0,
        "netPnlInr": float(rep.get("netPnlInr") or 0),
        "gateStats": dict(list((rep.get("gateStats") or {}).items())[:10]),
        "trades": [
            {
                "entryAt": t.get("entryAt"),
                "pnlInr": t.get("pnlInr"),
                "side": t.get("side"),
                "strike": t.get("strike"),
            }
            for t in taken[:6]
        ],
    }


def _roll_tape(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    t = sum(r[key]["tradeCount"] for r in rows)
    w = sum(r[key]["wins"] for r in rows)
    p = sum(float(r[key]["netPnlInr"] or 0) for r in rows)
    return {
        "days": len(rows),
        "trades": t,
        "wins": w,
        "winRatePct": round(100 * w / t, 1) if t else 0,
        "netPnlInr": round(p),
    }


def _roll_radar(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    tot = sum(r[key]["topMoments"] for r in rows)
    gp = sum(round(r[key]["gatePassPct"] * r[key]["topMoments"] / 100) for r in rows)
    fp = sum(round(r[key]["ftvPassPct"] * r[key]["topMoments"] / 100) for r in rows)
    full = sum(round(r[key]["fullPassPct"] * r[key]["topMoments"] / 100) for r in rows)
    return {"days": len(rows), "topMoments": tot, "gatePassEst": gp, "ftvPassEst": fp, "fullPassEst": full}


def _build_summary(radar_rows: list[dict], tape_rows: list[dict]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "runAt": datetime.now(IST).isoformat(),
        "branch": "cursor/top-signal-session-gaps-f5cb",
        "radarGateAudit": radar_rows,
        "tapeReplay": tape_rows,
        "rollup": {
            "radarOld": _roll_radar(radar_rows, "old"),
            "radarNew": _roll_radar(radar_rows, "new"),
        },
    }
    if tape_rows:
        summary["rollup"]["tapeOld"] = _roll_tape(tape_rows, "old")
        summary["rollup"]["tapeNew"] = _roll_tape(tape_rows, "new")
        summary["rollup"]["tapeDelta"] = {
            "trades": summary["rollup"]["tapeNew"]["trades"] - summary["rollup"]["tapeOld"]["trades"],
            "netPnlInr": summary["rollup"]["tapeNew"]["netPnlInr"] - summary["rollup"]["tapeOld"]["netPnlInr"],
        }
    return summary


def _save(summary: dict[str, Any]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 70, flush=True)
    print("EOD AUDIT — OLD vs NEW (top-signal-session-gaps branch)", flush=True)
    print("=" * 70, flush=True)

    radar_rows: list[dict[str, Any]] = []
    tape_rows: list[dict[str, Any]] = []

    for date in AUDIT_DATES:
        print(f"\n[{date}]", flush=True)
        path = _download(date)
        tape = _has_tape(path)
        print(f"  size={path.stat().st_size // 1024}KB tape={tape}", flush=True)

        old_r = audit_radar(date, path, old=True)
        new_r = audit_radar(date, path, old=False)
        radar_rows.append({"date": date, "old": old_r, "new": new_r})
        print(
            f"  RADAR full-pass OLD {old_r['fullPassPct']}% -> NEW {new_r['fullPassPct']}%  (n={new_r['topMoments']})",
            flush=True,
        )

        day_tape: dict[str, Any] | None = None
        if tape:
            print("  tape replay OLD...", flush=True)
            old_t = replay_tape(date, old=True)
            print(
                f"    OLD {old_t['tradeCount']}t {old_t['winRatePct']}% win ₹{old_t['netPnlInr']:,.0f}",
                flush=True,
            )
            print("  tape replay NEW...", flush=True)
            new_t = replay_tape(date, old=False)
            print(
                f"    NEW {new_t['tradeCount']}t {new_t['winRatePct']}% win ₹{new_t['netPnlInr']:,.0f}",
                flush=True,
            )
            day_tape = {"date": date, "old": old_t, "new": new_t}
            tape_rows.append(day_tape)
            print(
                f"  TAPE Δ {new_t['tradeCount'] - old_t['tradeCount']:+d} trades "
                f"₹{new_t['netPnlInr'] - old_t['netPnlInr']:+,.0f}",
                flush=True,
            )

        _save(_build_summary(radar_rows, tape_rows))

    summary = _build_summary(radar_rows, tape_rows)
    _save(summary)

    print("\n" + "=" * 70, flush=True)
    print("ROLLUP", flush=True)
    ro, rn = summary["rollup"]["radarOld"], summary["rollup"]["radarNew"]
    print(
        f"Radar moments: OLD gate~{ro['gatePassEst']}/{ro['topMoments']} "
        f"FTV~{ro['ftvPassEst']} full~{ro['fullPassEst']}",
        flush=True,
    )
    print(
        f"               NEW gate~{rn['gatePassEst']}/{rn['topMoments']} "
        f"FTV~{rn['ftvPassEst']} full~{rn['fullPassEst']}",
        flush=True,
    )
    if tape_rows:
        to, tn = summary["rollup"]["tapeOld"], summary["rollup"]["tapeNew"]
        d = summary["rollup"]["tapeDelta"]
        print(f"Tape replay ({to['days']} days): OLD {to['trades']}t {to['winRatePct']}% win ₹{to['netPnlInr']:,.0f}", flush=True)
        print(f"                    NEW {tn['trades']}t {tn['winRatePct']}% win ₹{tn['netPnlInr']:,.0f}", flush=True)
        print(f"                    Δ {d['trades']:+d} trades ₹{d['netPnlInr']:+,.0f}", flush=True)
    print(f"Report: {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
