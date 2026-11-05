#!/usr/bin/env python3
"""Exit replay: SENSEX 79000 CE Nov 5 @ 14:28 — old vs #907 ladder hold.

Premium path is reconstructed from production trade stamps + radar scorecard truth
(peak ₹519.7 on afternoon cycle). Intraday premium_tape.jsonl is not in the partial
radar ZIP while the session is still open; after 16:00 IST finalize, re-run with
read_premium_tape() for tick-exact replay.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Repo root on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.capital_allocator import lot_multiplier
from app.engines.explosion_profit import evaluate_explosion_exit
from app.models.schemas import PaperTrade, Side, StrategyType


def _parse_trade(path: Path) -> PaperTrade:
    raw = json.loads(path.read_text())
    ctx = deepcopy(raw.get("entryContext") or {})
    ep = float(raw["entryPremium"])
    opened = datetime.fromisoformat(raw["openedAt"])
    return PaperTrade(
        id=raw.get("id", "replay"),
        symbol=raw["symbol"],
        side=Side.CALL,
        strike=float(raw["strike"]),
        entryPremium=ep,
        currentPremium=ep,
        lots=int(raw.get("lots") or 29),
        openedAt=opened,
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=0.0,
        entryContext=ctx,
    )


def _premium_path() -> list[tuple[datetime, float]]:
    """Keypoints: live entry/peak/exit + scorecard peak ₹519.7 (~14:35–14:43)."""
    anchors = [
        ("2026-11-05T14:28:52+05:30", 308.98),
        ("2026-11-05T14:31:34+05:30", 374.50),
        ("2026-11-05T14:32:20+05:30", 350.45),
        ("2026-11-05T14:33:30+05:30", 390.0),
        ("2026-11-05T14:35:00+05:30", 480.0),
        ("2026-11-05T14:43:03+05:30", 519.70),
        ("2026-11-05T14:48:00+05:30", 340.0),
        ("2026-11-05T15:00:00+05:30", 400.0),
        ("2026-11-05T15:12:00+05:30", 475.0),
        ("2026-11-05T15:15:00+05:30", 465.0),
    ]
    pts = [(datetime.fromisoformat(ts), p) for ts, p in anchors]
    out: list[tuple[datetime, float]] = []
    step = timedelta(seconds=5)
    for k in range(len(pts) - 1):
        t0, p0 = pts[k]
        t1, p1 = pts[k + 1]
        t = t0
        span = max(1, int((t1 - t0).total_seconds() // 5))
        for i in range(span):
            frac = i / span
            p = p0 + (p1 - p0) * frac
            out.append((t, round(p, 2)))
            t += step
    out.append(pts[-1])
    return out


def _run_label(
    label: str,
    trade: PaperTrade,
    path: list[tuple[datetime, float]],
    settings: Settings,
) -> dict:
    from unittest.mock import patch

    units = int(lot_multiplier(trade.symbol) or 20)
    tier = str((trade.entryContext or {}).get("explosionTier") or "ELITE")
    ep = float(trade.entryPremium)
    opened = trade.openedAt
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=IST)

    tr = deepcopy(trade)
    tr.maxLtp = ep
    tr.bestPnlPoints = 0.0
    prev_p = ep
    prev_t = opened
    exit_at = None
    exit_p = None
    exit_reason = None
    timeline: list[dict] = []

    with patch("app.engines.explosion_profit.get_settings", return_value=settings), patch(
        "app.engines.moment_stage_trail.get_settings", return_value=settings
    ):
        for t, p in path:
            if t < opened:
                continue
            hold_s = (t - opened).total_seconds()
            tr.openedAt = opened
            tr.currentPremium = p
            tr.bestPnlPoints = max(float(tr.bestPnlPoints or 0), p - ep)
            if p > float(tr.maxLtp or 0):
                tr.maxLtp = p
                tr.maxLtpAt = t
            dt = max(0.001, (t - prev_t).total_seconds())
            v3 = (p - prev_p) / max(ep, 1e-9) * (3.0 / dt) * 100.0
            tr.entryContext = dict(tr.entryContext or {})
            tr.entryContext["liveVelocity3s"] = round(v3, 3)

            reason, pnl_inr = evaluate_explosion_exit(
                tr, p, tier, units, live_velocity_3s=v3,
            )
            timeline.append(
                {
                    "t": t.isoformat(),
                    "premium": p,
                    "bestPts": round(tr.bestPnlPoints, 2),
                    "v3": round(v3, 2),
                    "exitReason": reason,
                }
            )
            if reason:
                exit_at, exit_p, exit_reason = t, p, reason
                break
            prev_p, prev_t = p, t

    if exit_at is None:
        exit_at, exit_p, exit_reason = path[-1][0], path[-1][1], "session_end"

    peak = max(p for t, p in path if t >= opened)
    pnl_inr = (exit_p - ep) * tr.lots * units
    return {
        "label": label,
        "entryPremium": ep,
        "exitPremium": exit_p,
        "exitAt": exit_at.isoformat(),
        "exitReason": exit_reason,
        "peakPremiumOnPath": peak,
        "peakPts": round(peak - ep, 2),
        "pnlInr": round(pnl_inr, 0),
        "holdSeconds": round((exit_at - opened).total_seconds(), 0),
        "timelineTail": timeline[-8:],
    }


def main() -> None:
    trade_path = Path("/tmp/trade-79000.json")
    if not trade_path.is_file():
        print("Missing /tmp/trade-79000.json — fetch from /api/auto-trader/status first")
        sys.exit(1)

    trade = _parse_trade(trade_path)
    path = _premium_path()

    prod = {
        "label": "production_actual",
        "exitPremium": 374.5,
        "exitReason": "explosion_profit_ladder_peak_keep",
        "exitAt": "2026-11-05T14:32:20+05:30",
        "pnlInr": 22967,
        "peakPremiumOnPath": 519.7,
        "note": "Closed paper trade from API",
    }

    def _replay_settings(*, fix: bool) -> Settings:
        s = Settings()
        s.tp_rung_ladder_exit_enabled = False
        if fix:
            return s
        s.stage_runner_defer_unified_peak_keep_min_projected_tp = 999_999.0
        s.stage_runner_pre_stage_fall_min_seconds_after_peak = 45.0
        return s

    old_settings = _replay_settings(fix=False)
    new_settings = _replay_settings(fix=True)

    out = {
        "contract": "SENSEX:CALL:79000",
        "sessionDate": "2026-11-05",
        "entryAt": trade.openedAt.isoformat(),
        "projectedMaxTp": (trade.entryContext or {}).get("projectedMaxTp"),
        "stageSize": (trade.entryContext or {}).get("stageSize")
        or (trade.entryContext or {}).get("exitPlan", {}).get("stageSize"),
        "pathNote": "Reconstructed 5s path; replace with premium_tape.jsonl after finalize",
        "scorecardPeakInr": 519.7,
        "production": prod,
        "replayOldLadder": _run_label("old_ladder_approx", trade, path, old_settings),
        "replayFix907": _run_label("fix_907_branch", trade, path, new_settings),
    }

    artifact = Path("/opt/cursor/artifacts/replay-79000-exit-nov5.json")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
