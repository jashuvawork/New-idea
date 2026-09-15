#!/usr/bin/env python3
"""Replay user's Elite Score model on radar archive EOD outcomes.

Model:
  Setup type: FTV | V | EXPLOSIVE (priority FTV > V > EXPLOSIVE)
  Stage: BASE | ARMED | TRIGGERED | EXPANDING
  EliteScore 0-100 from structure + flow components
  Bands: 95+ A+, 90-94 Elite, 80-89 Watch, <80 skip
  Trade: score>=90, stage>=ARMED, near-base<=25%, timing GOOD/OK
  Weekly cap: 5 trades (take highest scores first per week)
"""

from __future__ import annotations

import json
import statistics
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.chop_day_guards import _day_mode_label
from app.engines.entry_timing import assess_entry_timing, timing_blocks_entry
from app.engines.ict_breakout_monitor import ICTBreakoutSignal
from app.engines.missed_trade_explainer import _candidate_from_alert
from app.engines.elite_score_engine import (
    STAGE_RANK,
    SETUP_PRIORITY,
    compute_elite_score,
    infer_setup_type,
    infer_stage,
)
from app.engines.top_moment_gate import (
    classify_top_moment_type,
    resolve_top_moment_min_grade,
    top_moment_entry_allowed,
)
from app.engines.trade_ranking import rank_entry_candidate
from app.models.schemas import Breadth, MarketPhase, SpotChart, SymbolSnapshot
from scripts.run_elite_pnl_comparison_eod import dedupe_same_moment_top1

IST = ZoneInfo("Asia/Kolkata")
ARCHIVE_DIR = Path("/tmp/eod_audit_archives")
OUT_PATH = Path("/opt/cursor/artifacts/user_elite_model_eod.json")


def _load_radars(date: str) -> list[dict[str, Any]]:
    path = ARCHIVE_DIR / f"radar-{date}.zip"
    if not path.exists() or path.stat().st_size < 1000:
        return []
    with zipfile.ZipFile(path) as zf:
        if "all_radars.json" not in zf.namelist():
            return []
        return json.loads(zf.read("all_radars.json"))


def _parse_ts(raw: Any, fallback_date: str = "") -> datetime:
    if raw:
        ts = datetime.fromisoformat(str(raw))
        return ts.replace(tzinfo=IST) if ts.tzinfo is None else ts.astimezone(IST)
    if fallback_date:
        return datetime.fromisoformat(f"{fallback_date}T12:00:00+05:30")
    return datetime.now(IST)


def _snap(row: dict[str, Any], date: str = "") -> SymbolSnapshot:
    ctx, alert = row.get("context") or {}, row.get("alert") or {}
    sc = ctx.get("spotChart") or {}
    spot_chart = (
        SpotChart(**{k: sc[k] for k in sc if k in SpotChart.model_fields})
        if sc
        else SpotChart(direction="NEUTRAL", spot=float(ctx.get("spot") or 0))
    )
    sym = str(row.get("symbol") or alert.get("symbol") or "SENSEX")
    return SymbolSnapshot(
        symbol=sym,
        timestamp=_parse_ts(row.get("ts"), date),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=float(ctx.get("spot") or 0),
        breadth=Breadth(bias=str((ctx.get("breadth") or {}).get("bias") or "NEUTRAL")),
        spotChart=spot_chart,
        tradeQualityScore=float(ctx.get("tradeQualityScore") or 55),
        explosionAlerts=[alert],
    )


def _infer_day_mode(ts: datetime, snap: SymbolSnapshot) -> str:
    breadth = {
        snap.symbol.upper(): {
            "bias": (snap.breadth.bias or "NEUTRAL").upper(),
            "regime": snap.spotChart.direction
            if snap.spotChart and snap.spotChart.direction in ("BULLISH", "BEARISH")
            else "RANGE_BOUND",
        }
    }
    biases = [b["bias"] for b in breadth.values()]
    n = len(biases)
    chop = n > 0 and (
        sum(1 for b in biases if b == "NEUTRAL") >= (n + 1) // 2
        or sum(1 for b in breadth.values() if b.get("regime") == "RANGE_BOUND")
        >= max(1, (2 * n + 2) // 3)
    )
    h, m = ts.hour, ts.minute
    momentum = h == 11 or h == 12 or (h == 13 and m <= 45)
    before_primary = h < 10 or (h == 10 and m == 0)
    mode, _, _ = _day_mode_label(
        chop=chop, momentum=momentum, breadth=breadth, before_primary=before_primary
    )
    return mode


def _ict(alert: dict[str, Any]) -> ICTBreakoutSignal:
    return ICTBreakoutSignal(
        active=bool(alert.get("ictBreakout") or alert.get("ictFlatThenVertical")),
        pattern=str(alert.get("momentType") or alert.get("ictPattern") or ""),
        score=float(alert.get("flatVerticalQuality") or 0),
        reasons=[],
        premium_fvg=bool(alert.get("ictPremiumFvg") or alert.get("premiumFvgPad")),
        flat_then_vertical=bool(alert.get("ictFlatThenVertical")),
        displacement=bool(alert.get("ictDisplacement")),
        volume_awakening=bool(alert.get("ictVolumeAwakening") or alert.get("volumeAwaken")),
        session_move_pct=float(alert.get("dailyMovePct") or alert.get("peakMovePct") or 0),
        velocity_3s=float(alert.get("velocity3s") or 0),
        volume_surge=float(alert.get("volumeSurge") or 1),
        base_premium=float(alert.get("ictBasePremium") or 0),
        base_relative_move_pct=float(
            alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct") or 0
        ),
        local_swing_base=bool(alert.get("ictLocalSwingBase")),
        flat_vertical_quality=float(alert.get("flatVerticalQuality") or 0),
        flat_vertical_grade=str(alert.get("flatVerticalGrade") or ""),
        first_lift=bool(alert.get("ictFirstLift")),
        base_armed=bool(alert.get("ictBaseArmed")),
        elite_base_ready=bool(alert.get("ictEliteBaseReady")),
        v_rip_ready=bool(alert.get("ictVRipReady")),
        building_rip_ready=bool(alert.get("ictBuildingRipReady")),
        armed_base_launch=bool(alert.get("ictArmedBaseLaunch")),
        armed_base_sustained_lift=bool(alert.get("ictArmedBaseSustainedLift")),
    )


def _row_from_archive(date: str, row: dict[str, Any], settings: Settings) -> dict[str, Any] | None:
    alert = row.get("alert") or {}
    outcome = row.get("outcome") or {}
    mfe = float(outcome.get("mfePct") or 0)
    mae = float(outcome.get("maePct") or 0)
    if mfe <= 0 and mae == 0:
        return None

    sym = str(row.get("symbol") or alert.get("symbol") or "SENSEX")
    snap = _snap(row, date)
    ict = _ict(alert)
    candidate = _candidate_from_alert(sym, snap, alert)
    ranking = rank_entry_candidate(candidate)
    ev = dict(ranking.get("evidence") or {})
    ev.setdefault("tier", str(alert.get("tier") or "").upper())
    ev.setdefault("explosionScore", float(alert.get("explosionScore") or 0))
    moment = classify_top_moment_type(ev)
    setup = infer_setup_type(ev, moment=moment)
    stage = infer_stage(ev)
    score, band, parts = compute_elite_score(ev, ranking, setup=setup)
    local = float(alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct") or 999)

    day_mode = _infer_day_mode(snap.timestamp, snap)
    min_grade = resolve_top_moment_min_grade(min_grade="A", day_mode=day_mode, settings=settings)
    top_ok, _, _ = top_moment_entry_allowed(
        ev, ranking, top_moments_only_enabled=True, min_grade="A", day_mode=day_mode
    )
    timing = assess_entry_timing(candidate.explosion_event, ict=ict, snap=snap)
    timing_ok = str(timing.get("assessment") or "") in ("GOOD", "OK") and not timing_blocks_entry(timing)[0]

    grade_rank = {"S": 0, "A": 1, "B": 2, "C": 3}.get(str(ranking.get("grade") or "C").upper(), 9)
    min_rank = {"S": 0, "A": 1, "B": 2, "C": 3}.get(min_grade, 1)
    grade_ok = grade_rank <= min_rank

    current_pass = top_ok and grade_ok and not timing_blocks_entry(timing)[0]

    user_pass = (
        setup in ("FTV", "V", "EXPLOSIVE")
        and score >= 90.0
        and STAGE_RANK.get(stage, 0) >= STAGE_RANK["ARMED"]
        and local <= 25.0
        and timing_ok
    )

    armed_at = alert.get("ictBaseArmedAt") or row.get("ts") or ""
    moment_ts = _parse_ts(armed_at if armed_at else None, date)

    return {
        "date": date,
        "week": _parse_ts(row.get("ts"), date).strftime("%G-W%V"),
        "ts": _parse_ts(row.get("ts"), date).isoformat(),
        "momentKey": moment_ts.strftime("%Y-%m-%dT%H:%M:%S"),
        "symbol": sym,
        "side": str(alert.get("side") or ""),
        "strike": float(alert.get("strike") or 0),
        "setup": setup,
        "stage": stage,
        "eliteScore": score,
        "eliteBand": band,
        "scoreParts": parts,
        "localBasePct": round(local, 1),
        "timing": str(timing.get("assessment") or ""),
        "mfe": mfe,
        "mae": mae,
        "good15": mfe >= 15,
        "home50": mfe >= 50,
        "lossLike": mfe < 15 and mae <= -10,
        "currentPass": current_pass,
        "userPass": user_pass,
        "setupPriority": SETUP_PRIORITY.get(setup, 9),
    }


def _stats(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if not rows:
        return {"label": label, "n": 0}
    n = len(rows)
    return {
        "label": label,
        "n": n,
        "good15Pct": round(100 * sum(r["good15"] for r in rows) / n, 1),
        "home50Pct": round(100 * sum(r["home50"] for r in rows) / n, 1),
        "lossLikePct": round(100 * sum(r["lossLike"] for r in rows) / n, 1),
        "medianMfe": round(statistics.median(r["mfe"] for r in rows), 1),
        "avgScore": round(statistics.mean(r["eliteScore"] for r in rows), 1),
    }


def _apply_hybrid_cap(
    candidates: list[dict[str, Any]],
    *,
    weekly_cap: int = 5,
    ftv_a_plus_min: float = 95.0,
) -> list[dict[str, Any]]:
    """Hybrid: always take score≥95 FTV; fill weekly budget up to `weekly_cap` otherwise."""
    pool = dedupe_same_moment_top1(candidates, pass_fn=lambda r: r["userPass"])
    by_week: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in pool:
        by_week[r.get("week") or datetime.fromisoformat(r["ts"]).strftime("%G-W%V")].append(r)

    taken: list[dict[str, Any]] = []
    for week, rows in sorted(by_week.items()):
        # De-dupe contract per day — keep best score
        best_by_key: dict[tuple[str, str, float, str], dict[str, Any]] = {}
        for r in rows:
            key = (r["date"], r["symbol"], r["strike"], r["side"])
            if key not in best_by_key or r["eliteScore"] > best_by_key[key]["eliteScore"]:
                best_by_key[key] = r
        rows = sorted(
            best_by_key.values(),
            key=lambda x: (-x["eliteScore"], x["setupPriority"], x["ts"]),
        )

        must_take = [
            r for r in rows
            if r["eliteScore"] >= ftv_a_plus_min and r["setup"] == "FTV"
        ]
        must_keys = {
            (r["date"], r["symbol"], r["strike"], r["side"]) for r in must_take
        }
        taken_keys = set(must_keys)
        taken.extend(must_take)

        weekly_count = len(must_take)
        for r in rows:
            if weekly_count >= weekly_cap:
                break
            key = (r["date"], r["symbol"], r["strike"], r["side"])
            if key in taken_keys:
                continue
            taken.append(r)
            taken_keys.add(key)
            weekly_count += 1

    return taken


def _apply_weekly_cap(candidates: list[dict[str, Any]], cap: int = 5) -> list[dict[str, Any]]:
    """Take top `cap` user-pass rows per ISO week by score then setup priority."""
    pool = dedupe_same_moment_top1(candidates, pass_fn=lambda r: r["userPass"])
    by_week: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in pool:
        week = r.get("week") or datetime.fromisoformat(r["ts"]).strftime("%G-W%V")
        by_week[week].append(r)
    taken: list[dict[str, Any]] = []
    for week, rows in sorted(by_week.items()):
        # De-dupe: one row per contract per day (best score)
        best_by_key: dict[tuple[str, str, float, str], dict[str, Any]] = {}
        for r in rows:
            key = (r["date"], r["symbol"], r["strike"], r["side"])
            if key not in best_by_key or r["eliteScore"] > best_by_key[key]["eliteScore"]:
                best_by_key[key] = r
        rows = list(best_by_key.values())
        rows.sort(key=lambda x: (-x["eliteScore"], x["setupPriority"], x["ts"]))
        taken.extend(rows[:cap])
    return taken


def main() -> int:
    settings = Settings()
    settings.top_moments_day_type_grade_policy_enabled = True

    dates = sorted(
        p.stem.replace("radar-", "")
        for p in ARCHIVE_DIR.glob("radar-*.zip")
        if p.stat().st_size > 5000
    )

    all_rows: list[dict[str, Any]] = []
    for date in dates:
        for row in _load_radars(date):
            rec = _row_from_archive(date, row, settings)
            if rec:
                all_rows.append(rec)

    user_all = dedupe_same_moment_top1(all_rows, pass_fn=lambda r: r["userPass"])
    user_weekly = _apply_weekly_cap(all_rows, cap=5)
    user_hybrid = _apply_hybrid_cap(all_rows, weekly_cap=5, ftv_a_plus_min=95.0)
    current_all = [r for r in all_rows if r["currentPass"]]

    # Also simulate user model with score>=90 but no weekly cap (daily best)
    user_daily_best: list[dict[str, Any]] = []
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in all_rows:
        if r["userPass"]:
            by_date[r["date"]].append(r)
    for d, rows in by_date.items():
        rows.sort(key=lambda x: (-x["eliteScore"], x["setupPriority"]))
        user_daily_best.extend(rows[:2])  # max 2/day exceptional

    out = {
        "runAt": datetime.now(IST).isoformat(),
        "dates": dates,
        "totalMomentsWithOutcome": len(all_rows),
        "comparison": {
            "currentSystem": _stats(current_all, "Current (top-moment + day-grade + timing)"),
            "userModelAllPasses": _stats(user_all, "User model (all passes)"),
            "userModelWeeklyCap5": _stats(user_weekly, "User model (5/week cap)"),
            "userModelHybrid": _stats(
                user_hybrid,
                "Hybrid (5/week + always score≥95 FTV)",
            ),
            "userModelDailyBest2": _stats(user_daily_best, "User model (best 2/day)"),
        },
        "weeklyTrades": {},
        "bySetup": {
            setup: _stats([r for r in user_weekly if r["setup"] == setup], setup)
            for setup in ("FTV", "V", "EXPLOSIVE")
        },
        "sampleTrades": user_weekly[:15],
        "hybridWeeklyTrades": {},
        "sampleHybridTrades": user_hybrid[:20],
        "currentVsUser": {
            "homeRunsTotal": sum(1 for r in all_rows if r["home50"]),
            "currentCapturesHomeRuns": sum(
                1 for r in all_rows if r["home50"] and r["currentPass"]
            ),
            "userCapturesHomeRuns": sum(
                1 for r in all_rows if r["home50"] and r["userPass"]
            ),
            "userWeeklyCapturesHomeRuns": sum(1 for r in user_weekly if r["home50"]),
            "hybridCapturesHomeRuns": sum(1 for r in user_hybrid if r["home50"]),
            "lossLikeTotal": sum(1 for r in all_rows if r["lossLike"]),
            "currentKeepsLosses": sum(
                1 for r in all_rows if r["lossLike"] and r["currentPass"]
            ),
            "userKeepsLosses": sum(
                1 for r in all_rows if r["lossLike"] and r["userPass"]
            ),
            "userWeeklyKeepsLosses": sum(1 for r in user_weekly if r["lossLike"]),
            "hybridKeepsLosses": sum(1 for r in user_hybrid if r["lossLike"]),
        },
    }

    weeks_hybrid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in user_hybrid:
        weeks_hybrid[r.get("week") or datetime.fromisoformat(r["ts"]).strftime("%G-W%V")].append(r)
    out["hybridWeeklyTrades"] = {
        w: [
            {
                "date": r["date"],
                "setup": r["setup"],
                "stage": r["stage"],
                "band": r["eliteBand"],
                "score": r["eliteScore"],
                "mfe": r["mfe"],
                "lossLike": r["lossLike"],
                "mustTake95Ftv": r["eliteScore"] >= 95.0 and r["setup"] == "FTV",
                "contract": f"{r['symbol']} {r['side']} {r['strike']}",
            }
            for r in sorted(rows, key=lambda x: x["ts"])
        ]
        for w, rows in sorted(weeks_hybrid.items())
    }

    weeks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in user_weekly:
        ts = datetime.fromisoformat(r["ts"])
        weeks[ts.strftime("%G-W%V")].append(r)
    out["weeklyTrades"] = {
        w: [
            {
                "date": r["date"],
                "setup": r["setup"],
                "stage": r["stage"],
                "band": r["eliteBand"],
                "score": r["eliteScore"],
                "mfe": r["mfe"],
                "lossLike": r["lossLike"],
                "contract": f"{r['symbol']} {r['side']} {r['strike']}",
            }
            for r in sorted(rows, key=lambda x: x["ts"])
        ]
        for w, rows in sorted(weeks.items())
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))

    print("=== USER ELITE MODEL vs CURRENT (EOD radar outcomes) ===")
    print(f"Dates: {len(dates)}, moments with outcomes: {len(all_rows)}\n")
    for k, v in out["comparison"].items():
        print(v)
    print("\n=== Hybrid (5/week + always score≥95 FTV) ===")
    print(out["comparison"]["userModelHybrid"])
    print("\n=== Weekly cap (5 trades/week) ===")
    for w, trades in out["weeklyTrades"].items():
        good = sum(1 for t in trades if t["mfe"] >= 15)
        home = sum(1 for t in trades if t["mfe"] >= 50)
        losses = sum(1 for t in trades if t["lossLike"])
        print(f"  {w}: {len(trades)} trades, {good} good15, {home} home50, {losses} loss-like")
    for w, trades in sorted(out["hybridWeeklyTrades"].items()):
        good = sum(1 for t in trades if t["mfe"] >= 15)
        home = sum(1 for t in trades if t["mfe"] >= 50)
        losses = sum(1 for t in trades if t["lossLike"])
        must = sum(1 for t in trades if t["mustTake95Ftv"])
        print(
            f"  {w}: {len(trades)} trades ({must} must-take 95+ FTV) | "
            f"good15={good} home50={home} loss={losses}"
        )
    print("\n=== Capture vs losses ===")
    for k, v in out["currentVsUser"].items():
        print(f"  {k}: {v}")
    print(f"\nFull report: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
