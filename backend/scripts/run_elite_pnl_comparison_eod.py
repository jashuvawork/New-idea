#!/usr/bin/env python3
"""P&L comparison across entry policies — 90% capital cap + max lots every trade.

Replays radar-archive outcomes (12 days, ~533 moments) and sizes each taken trade at
90% of the sizing book (default ₹200k → ₹180k notional budget) with max affordable
lots. Exit uses the archive outcome model: +target% when target-before-stop, −stop%
when stopped out, else last mark-to-market move%.
"""

from __future__ import annotations

import json
import statistics
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.capital_allocator import lot_multiplier, max_lots_for_capital_pct
from app.engines.chop_day_guards import _day_mode_label
from app.engines.day_type_grade_policy import (
    fast_moving_grade_c_waiver,
    resolve_day_type_min_grade,
)
from app.engines.day_adaptive_engine import classify_day_type
from app.engines.entry_timing import assess_entry_timing, timing_blocks_entry
from app.engines.ict_breakout_monitor import ICTBreakoutSignal
from app.engines.missed_trade_explainer import _candidate_from_alert
from app.engines.elite_score_engine import (
    STAGE_RANK,
    SETUP_PRIORITY,
    compute_elite_score,
    elite_entry_allowed,
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

IST = ZoneInfo("Asia/Kolkata")
ARCHIVE_DIR = Path("/tmp/eod_audit_archives")
OUT_PATH = Path("/opt/cursor/artifacts/elite_pnl_comparison_90pct_maxlots.json")
CAPITAL_PCT = 0.90


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


def _exit_move_pct(outcome: dict[str, Any]) -> float:
    if bool(outcome.get("targetBeforeStop")):
        return float(outcome.get("targetPct") or 20.0)
    if str(outcome.get("status") or "").upper() == "LOSER" and outcome.get("stopAt"):
        return -float(outcome.get("stopPct") or 10.0)
    return float(outcome.get("lastMovePct") or 0.0)


def _size_trade(symbol: str, premium: float, settings: Settings) -> dict[str, Any]:
    sym = symbol.upper()
    mult = lot_multiplier(sym)
    with patch("app.config.get_settings", return_value=settings):
        lots = max(1, max_lots_for_capital_pct(sym, premium, CAPITAL_PCT))
    notional = premium * lots * mult
    cap_inr = float(getattr(settings, "max_sizing_capital_inr", 200_000.0) or 200_000.0)
    budget = cap_inr * CAPITAL_PCT
    return {
        "lots": lots,
        "lotMultiplier": mult,
        "entryPremium": round(premium, 2),
        "notionalInr": round(notional, 0),
        "budgetInr": round(budget, 0),
        "capitalPct": CAPITAL_PCT,
    }


def _pnl_inr(row: dict[str, Any], settings: Settings) -> dict[str, Any]:
    alert = row.get("_alert") or {}
    outcome = row.get("_outcome") or {}
    sym = str(row.get("symbol") or alert.get("symbol") or "SENSEX").upper()
    premium = float(outcome.get("entryPremium") or alert.get("premium") or 0)
    if premium <= 0:
        return {"pnlInr": 0.0, "lots": 0, "exitMovePct": 0.0}

    sizing = _size_trade(sym, premium, settings)
    move_pct = _exit_move_pct(outcome)
    pnl_pts = premium * (move_pct / 100.0)
    pnl_inr = pnl_pts * sizing["lots"] * sizing["lotMultiplier"]
    return {
        **sizing,
        "exitMovePct": round(move_pct, 2),
        "pnlInr": round(pnl_inr, 0),
        "pnlPoints": round(pnl_pts, 2),
        "win": pnl_inr > 0,
    }


def _row_from_archive(
    date: str,
    row: dict[str, Any],
    settings: Settings,
    *,
    legacy_settings: Settings,
) -> dict[str, Any] | None:
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

    timing = assess_entry_timing(candidate.explosion_event, ict=ict, snap=snap)
    timing_assessment = str(timing.get("assessment") or "")
    timing_action = str(timing.get("action") or timing.get("timingAction") or "").lower()
    timing_ok = timing_assessment in ("GOOD", "OK") and not timing_blocks_entry(timing)[0]
    ev = {
        **ev,
        "timingAssessment": timing_assessment,
        "timingAction": timing_action,
    }
    milestones = row.get("milestones") or alert.get("milestones") or []
    if milestones:
        ev["milestoneCount"] = len(milestones)

    day_mode = _infer_day_mode(snap.timestamp, snap)
    min_grade = resolve_top_moment_min_grade(min_grade="A", day_mode=day_mode, settings=legacy_settings)
    with patch("app.config.get_settings", return_value=legacy_settings):
        legacy_ok, _, _ = top_moment_entry_allowed(
            ev,
            ranking,
            top_moments_only_enabled=True,
            min_grade="A",
            day_mode=day_mode,
        )
    with patch("app.config.get_settings", return_value=settings):
        elite_ok, _, _ = elite_entry_allowed(
            ev,
            ranking,
            settings=settings,
            day_mode=day_mode,
            snapshots={sym: snap},
        )

    grade_rank = {"S": 0, "A": 1, "B": 2, "C": 3}.get(str(ranking.get("grade") or "C").upper(), 9)
    min_rank = {"S": 0, "A": 1, "B": 2, "C": 3}.get(min_grade, 1)
    grade_ok = grade_rank <= min_rank

    current_pass = legacy_ok and grade_ok and not timing_blocks_entry(timing)[0]
    user_pass = (
        setup in ("FTV", "V", "EXPLOSIVE")
        and score >= float(getattr(settings, "elite_trade_min_score", 90.0) or 90.0)
        and STAGE_RANK.get(stage, 0) >= STAGE_RANK["ARMED"]
        and local <= float(getattr(settings, "elite_trade_max_local_base_pct", 20.0) or 20.0)
        and timing_ok
    )
    day_type = classify_day_type(day_mode, "MEDIUM", {sym: snap})

    return {
        "date": date,
        "week": _parse_ts(row.get("ts"), date).strftime("%G-W%V"),
        "ts": _parse_ts(row.get("ts"), date).isoformat(),
        "symbol": sym,
        "side": str(alert.get("side") or ""),
        "strike": float(alert.get("strike") or 0),
        "setup": setup,
        "stage": stage,
        "eliteScore": score,
        "eliteBand": band,
        "localBasePct": round(local, 1),
        "dayMode": day_mode,
        "dayType": day_type,
        "grade": str(ranking.get("grade") or "C").upper(),
        "momentType": moment,
        "_rankScore": float(ranking.get("rankScore") or 0),
        "mfe": mfe,
        "mae": mae,
        "good15": mfe >= 15,
        "home50": mfe >= 50,
        "lossLike": mfe < 15 and mae <= -10,
        "currentPass": current_pass,
        "eliteEnginePass": elite_ok,
        "userPass": user_pass,
        "setupPriority": SETUP_PRIORITY.get(setup, 9),
        "_alert": alert,
        "_outcome": outcome,
    }


def _apply_weekly_cap(rows: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    by_week: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if not r["userPass"]:
            continue
        by_week[r["week"]].append(r)
    taken: list[dict[str, Any]] = []
    for _, pool in sorted(by_week.items()):
        best_by_key: dict[tuple[str, str, float, str], dict[str, Any]] = {}
        for r in pool:
            key = (r["date"], r["symbol"], r["strike"], r["side"])
            if key not in best_by_key or r["eliteScore"] > best_by_key[key]["eliteScore"]:
                best_by_key[key] = r
        ranked = sorted(
            best_by_key.values(),
            key=lambda x: (-x["eliteScore"], x["setupPriority"], x["ts"]),
        )
        taken.extend(ranked[:cap])
    return taken


def _apply_hybrid_cap(
    rows: list[dict[str, Any]],
    *,
    weekly_cap: int,
    ftv_a_plus_min: float = 95.0,
) -> list[dict[str, Any]]:
    pool = [r for r in rows if r["userPass"]]
    by_week: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in pool:
        by_week[r["week"]].append(r)

    taken: list[dict[str, Any]] = []
    for _, week_rows in sorted(by_week.items()):
        best_by_key: dict[tuple[str, str, float, str], dict[str, Any]] = {}
        for r in week_rows:
            key = (r["date"], r["symbol"], r["strike"], r["side"])
            if key not in best_by_key or r["eliteScore"] > best_by_key[key]["eliteScore"]:
                best_by_key[key] = r
        rows_sorted = sorted(best_by_key.values(), key=lambda x: x["ts"])

        must_take = [
            r for r in rows_sorted
            if r["eliteScore"] >= ftv_a_plus_min and r["setup"] == "FTV"
        ]
        taken_keys = {(r["date"], r["symbol"], r["strike"], r["side"]) for r in must_take}
        taken.extend(must_take)

        count = len(must_take)
        for r in rows_sorted:
            if count >= weekly_cap:
                break
            key = (r["date"], r["symbol"], r["strike"], r["side"])
            if key in taken_keys:
                continue
            taken.append(r)
            taken_keys.add(key)
            count += 1
    return taken


def _daily_best(rows: list[dict[str, Any]], per_day: int = 2) -> list[dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["userPass"]:
            by_date[r["date"]].append(r)
    taken: list[dict[str, Any]] = []
    for _, pool in sorted(by_date.items()):
        pool.sort(key=lambda x: (-x["eliteScore"], x["setupPriority"]))
        taken.extend(pool[:per_day])
    return taken


_STRICT_DAY_MODES = frozenset({"CHOP DAY", "CHOP (PRE-10)", "EXPIRY WORST", "EXPIRY DAY"})
_BLOCK_WORST_DAY_TYPES = frozenset({"WORST"})
_MOMENTUM_RALLY_DAY_MODE = "MOMENTUM RALLY"


def _grade_passes_day_policy(row: dict[str, Any], settings: Settings) -> bool:
    grade = str(row.get("grade") or "C").upper()
    if grade == "REJECT":
        return False
    day_mode = str(row.get("dayMode") or "")
    effective_min = resolve_day_type_min_grade(min_grade="A", day_mode=day_mode, settings=settings)
    min_rank = {"S": 0, "A": 1, "B": 2, "C": 3}.get(effective_min, 1)
    grade_rank = {"S": 0, "A": 1, "B": 2, "C": 3}.get(grade, 9)
    if grade_rank <= min_rank:
        return True
    evidence = {
        "tier": row.get("_tier", ""),
        "velocity3s": row.get("_velocity3s", 0),
        "vRipReady": row.get("_vRipReady", False),
        "flatThenVertical": row.get("_flatThenVertical", False),
        "activeBreakout": row.get("_activeBreakout", False),
    }
    ranking = {"grade": grade, "rankScore": row.get("_rankScore", 0)}
    return fast_moving_grade_c_waiver(
        evidence,
        ranking,
        row.get("momentType"),
        day_mode=day_mode,
        settings=settings,
    )


def _filter_day_type_grade(rows: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    return [r for r in rows if _grade_passes_day_policy(r, settings)]


def _filter_block_strict_day_modes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("dayMode") or "") not in _STRICT_DAY_MODES]


def _filter_block_worst_day_type(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("dayType") or "") not in _BLOCK_WORST_DAY_TYPES]


def _filter_block_momentum_rally_worst(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Live gate: block MOMENTUM RALLY + WORST; keep CHOP+RALLY/WORST and GOOD."""
    return [
        r for r in rows
        if not (
            str(r.get("dayType") or "").upper() == "WORST"
            and str(r.get("dayMode") or "").upper() == _MOMENTUM_RALLY_DAY_MODE
        )
    ]


def _filter_chop_score_boost(rows: list[dict[str, Any]], boost_min: float = 95.0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        mode = str(r.get("dayMode") or "")
        if mode in _STRICT_DAY_MODES and float(r.get("eliteScore") or 0) < boost_min:
            continue
        out.append(r)
    return out


def _enrich_day_meta(rows: list[dict[str, Any]], all_rows: list[dict[str, Any]]) -> None:
    """Attach ranking evidence stubs for day-grade waiver checks."""
    meta_by_key = {}
    for r in all_rows:
        alert = r.get("_alert") or {}
        key = (r["date"], r["symbol"], r["strike"], r["side"], r["ts"])
        meta_by_key[key] = {
            "_tier": str(alert.get("tier") or "").upper(),
            "_velocity3s": float(alert.get("velocity3s") or 0),
            "_vRipReady": bool(alert.get("ictVRipReady")),
            "_flatThenVertical": bool(alert.get("ictFlatThenVertical")),
            "_activeBreakout": bool(alert.get("ictBreakout")),
            "_rankScore": float(r.get("_rankScore") or 0),
        }
    for r in rows:
        key = (r["date"], r["symbol"], r["strike"], r["side"], r["ts"])
        r.update(meta_by_key.get(key, {}))


def _pnl_summary(rows: list[dict[str, Any]], settings: Settings, label: str) -> dict[str, Any]:
    if not rows:
        return {
            "label": label,
            "trades": 0,
            "totalPnlInr": 0,
            "avgPnlInr": 0,
            "winRatePct": 0,
            "wins": 0,
            "losses": 0,
            "medianPnlInr": 0,
            "bestTradeInr": 0,
            "worstTradeInr": 0,
            "totalNotionalInr": 0,
            "avgLots": 0,
            "good15Pct": 0,
            "home50Pct": 0,
            "lossLikePct": 0,
        }

    enriched = [{**r, **_pnl_inr(r, settings)} for r in rows]
    pnls = [float(r["pnlInr"]) for r in enriched]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    n = len(enriched)
    return {
        "label": label,
        "trades": n,
        "totalPnlInr": round(sum(pnls), 0),
        "avgPnlInr": round(statistics.mean(pnls), 0),
        "medianPnlInr": round(statistics.median(pnls), 0),
        "winRatePct": round(100 * wins / n, 1),
        "wins": wins,
        "losses": losses,
        "bestTradeInr": round(max(pnls), 0),
        "worstTradeInr": round(min(pnls), 0),
        "totalNotionalInr": round(sum(float(r["notionalInr"]) for r in enriched), 0),
        "avgLots": round(statistics.mean(float(r["lots"]) for r in enriched), 1),
        "good15Pct": round(100 * sum(r["good15"] for r in enriched) / n, 1),
        "home50Pct": round(100 * sum(r["home50"] for r in enriched) / n, 1),
        "lossLikePct": round(100 * sum(r["lossLike"] for r in enriched) / n, 1),
        "sampleTrades": [
            {
                "date": r["date"],
                "contract": f"{r['symbol']} {r['side']} {r['strike']}",
                "setup": r["setup"],
                "eliteScore": r["eliteScore"],
                "lots": r["lots"],
                "pnlInr": r["pnlInr"],
                "exitMovePct": r["exitMovePct"],
                "mfe": r["mfe"],
            }
            for r in sorted(enriched, key=lambda x: -float(x["pnlInr"]))[:8]
        ],
    }


def main() -> int:
    settings = Settings(
        elite_trade_engine_enabled=True,
        max_sizing_capital_inr=200_000.0,
        fallback_capital_inr=200_000.0,
        per_trade_capital_pct=CAPITAL_PCT,
        use_upstox_capital_for_sizing=False,
    )
    legacy_settings = Settings(
        elite_trade_engine_enabled=False,
        top_moments_day_type_grade_policy_enabled=True,
        max_sizing_capital_inr=200_000.0,
        fallback_capital_inr=200_000.0,
        per_trade_capital_pct=CAPITAL_PCT,
        use_upstox_capital_for_sizing=False,
    )

    # Seed capital snapshot for max_lots_for_capital_pct
    from app.engines.capital_allocator import set_manual_capital_limit

    set_manual_capital_limit(float(settings.max_sizing_capital_inr))

    dates = sorted(
        p.stem.replace("radar-", "")
        for p in ARCHIVE_DIR.glob("radar-*.zip")
        if p.stat().st_size > 5000
    )

    all_rows: list[dict[str, Any]] = []
    for date in dates:
        for row in _load_radars(date):
            rec = _row_from_archive(date, row, settings, legacy_settings=legacy_settings)
            if rec:
                all_rows.append(rec)

    _enrich_day_meta(all_rows, all_rows)

    elite_all = [r for r in all_rows if r["eliteEnginePass"]]
    user_all = [r for r in all_rows if r["userPass"]]

    elite_day_grade = _filter_day_type_grade(elite_all, settings)
    user_day_grade = _filter_day_type_grade(user_all, settings)
    user_no_worst = _filter_block_worst_day_type(user_all)
    user_no_momentum_rally_worst = _filter_block_momentum_rally_worst(user_all)
    elite_no_chop_modes = _filter_block_strict_day_modes(elite_all)
    elite_chop95 = _filter_chop_score_boost(elite_all, 95.0)
    elite_day_grade_no_worst = _filter_block_worst_day_type(elite_day_grade)

    policies = {
        "currentLegacy": [r for r in all_rows if r["currentPass"]],
        "eliteEngineLive": elite_all,
        "elitePlusDayGrade": elite_day_grade,
        "elitePlusDayGradeNoWorst": elite_day_grade_no_worst,
        "eliteBlockWorstDayType": user_no_worst,
        "eliteBlockMomentumRallyWorst": user_no_momentum_rally_worst,
        "eliteBlockChopExpiryModes": _filter_block_strict_day_modes(user_all),
        "eliteChopScore95": elite_chop95,
        "userModelAll": user_all,
        "userPlusDayGrade": user_day_grade,
        "weeklyCap5": _apply_weekly_cap(all_rows, 5),
        "weeklyCap8": _apply_weekly_cap(all_rows, 8),
        "weeklyCap8DayGrade": _apply_weekly_cap(
            [{**r, "userPass": r["userPass"] and _grade_passes_day_policy(r, settings)} for r in all_rows],
            8,
        ),
        "hybridCap5": _apply_hybrid_cap(all_rows, weekly_cap=5),
        "hybridCap8": _apply_hybrid_cap(all_rows, weekly_cap=8),
        "hybridCap8DayGrade": _apply_hybrid_cap(
            [{**r, "userPass": r["userPass"] and _grade_passes_day_policy(r, settings)} for r in all_rows],
            weekly_cap=8,
        ),
        "dailyBest2": _daily_best(all_rows, 2),
    }

    comparison = {
        key: _pnl_summary(rows, settings, key)
        for key, rows in policies.items()
    }

    # Weekly P&L for top policies
    weekly_pnl: dict[str, dict[str, float]] = {}
    for policy_key in ("eliteBlockMomentumRallyWorst", "eliteBlockWorstDayType", "eliteEngineLive", "currentLegacy"):
        by_week: dict[str, float] = defaultdict(float)
        for r in policies[policy_key]:
            pnl = _pnl_inr(r, settings)["pnlInr"]
            by_week[r["week"]] += pnl
        weekly_pnl[policy_key] = dict(sorted(by_week.items()))

    out = {
        "runAt": datetime.now(IST).isoformat(),
        "assumptions": {
            "capitalInr": settings.max_sizing_capital_inr,
            "capitalPctPerTrade": CAPITAL_PCT,
            "budgetPerTradeInr": settings.max_sizing_capital_inr * CAPITAL_PCT,
            "sizing": "max_lots_for_capital_pct (90% book, max affordable lots)",
            "exitModel": "targetBeforeStop→+targetPct; LOSER+stop→−stopPct; else lastMovePct",
            "dates": dates,
            "momentsWithOutcome": len(all_rows),
        },
        "comparison": comparison,
        "weeklyPnlInr": weekly_pnl,
        "rankedByTotalPnl": sorted(
            comparison.values(),
            key=lambda x: float(x.get("totalPnlInr") or 0),
            reverse=True,
        ),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))

    cap = settings.max_sizing_capital_inr * CAPITAL_PCT
    print("=== P&L COMPARISON — 90% cap + max lots per trade ===")
    print(f"Capital book ₹{settings.max_sizing_capital_inr:,.0f} | per-trade budget ₹{cap:,.0f} (90%)")
    print(f"Dates: {len(dates)} | moments: {len(all_rows)}\n")
    print(f"{'Policy':<22} {'Trades':>6} {'Total P&L':>12} {'Avg/trade':>10} {'Win%':>6} {'W/L':>8} {'Med P&L':>10}")
    print("-" * 82)
    for row in out["rankedByTotalPnl"]:
        print(
            f"{row['label']:<22} {row['trades']:>6} "
            f"₹{row['totalPnlInr']:>10,.0f} ₹{row['avgPnlInr']:>8,.0f} "
            f"{row['winRatePct']:>5.1f}% {row['wins']:>3}/{row['losses']:<3} "
            f"₹{row['medianPnlInr']:>8,.0f}"
        )
    print(f"\nFull JSON: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
