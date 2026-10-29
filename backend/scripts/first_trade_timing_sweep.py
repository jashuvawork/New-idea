#!/usr/bin/env python3
"""Sweep first-trade entry times for a session using funnel + radar outcome paths."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _build_premium_series(outcome: dict[str, Any]) -> list[tuple[datetime, float]]:
    """Piecewise-linear premium path from radar outcome milestones."""
    pts: list[tuple[datetime, float]] = []
    ep = _f(outcome.get("entryPremium"))
    ea = outcome.get("entryAt")
    if ea and ep > 0:
        pts.append((_parse_ts(ea), ep))
    for h in (outcome.get("horizons") or {}).values():
        if h.get("at") and h.get("premium"):
            pts.append((_parse_ts(h["at"]), _f(h["premium"])))
    if outcome.get("targetAt") and ep > 0:
        tgt = ep * (1.0 + _f(outcome.get("targetPct"), 20.0) / 100.0)
        pts.append((_parse_ts(outcome["targetAt"]), tgt))
    if outcome.get("stopAt") and ep > 0:
        stp = ep * (1.0 - _f(outcome.get("stopPct"), 10.0) / 100.0)
        pts.append((_parse_ts(outcome["stopAt"]), stp))
    # Do not append lastUpdated/lastPremium — that is monitor-end, not trade path.
    pts.sort(key=lambda x: x[0])
    if len(pts) < 2:
        return pts
    dense: list[tuple[datetime, float]] = []
    step = timedelta(seconds=10)
    for i in range(len(pts) - 1):
        t0, p0 = pts[i]
        t1, p1 = pts[i + 1]
        dense.append((t0, p0))
        t = t0 + step
        while t < t1:
            frac = (t - t0).total_seconds() / max((t1 - t0).total_seconds(), 1)
            dense.append((t, p0 + (p1 - p0) * frac))
            t += step
    dense.append(pts[-1])
    return dense


def _premium_at(series: list[tuple[datetime, float]], t: datetime) -> float | None:
    if not series:
        return None
    if t <= series[0][0]:
        return series[0][1]
    for i in range(len(series) - 1):
        t0, p0 = series[i]
        t1, p1 = series[i + 1]
        if t0 <= t <= t1:
            if t1 == t0:
                return p0
            frac = (t - t0).total_seconds() / (t1 - t0).total_seconds()
            return p0 + (p1 - p0) * frac
    return series[-1][1]


def _load_funnel(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_radars(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text())
    return {e["key"]: e for e in data}


def _index_funnel_events(funnel: dict[str, Any]) -> dict[str, list[tuple[datetime, str, dict]]]:
    by_key: dict[str, list[tuple[datetime, str, dict]]] = {}
    for row in funnel.get("rows") or []:
        k = row["key"]
        for ev in row.get("timeline") or []:
            ts = ev.get("ts")
            if not ts:
                continue
            by_key.setdefault(k, []).append((_parse_ts(ts), ev.get("event") or "", ev))
        by_key[k].sort(key=lambda x: x[0])
    return by_key


def _next_selected(
    funnel: dict[str, Any],
    after: datetime,
    *,
    side: str | None,
    respect_fade: bool,
    events_by_key: dict[str, list],
) -> tuple[datetime, str, dict] | None:
    cands: list[tuple[datetime, str, dict]] = []
    for row in funnel.get("rows") or []:
        k = row["key"]
        if side and f":{side}:" not in k:
            continue
        for ts, ev, raw in events_by_key.get(k, []):
            if ts < after or ev != "SELECTED":
                continue
            if respect_fade:
                rejected = False
                for ts2, ev2, raw2 in events_by_key.get(k, []):
                    if ts2 <= ts:
                        continue
                    if (ts2 - ts).total_seconds() > 5:
                        break
                    if ev2 == "ORDER_REJECTED" and raw2.get("reason") in (
                        "exec_premium_fading_at_execution",
                        "exec_mtf_premium_1m_fading",
                    ):
                        rejected = True
                        break
                if rejected:
                    continue
            cands.append((ts, k, raw))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    return cands[0]


def _replay_forced_entry(
    *,
    symbol: str,
    side: str,
    strike: float,
    tier: str,
    series: list[tuple[datetime, float, float]],
    start_i: int,
) -> dict[str, Any] | None:
    """Enter at ``start_i`` (selector/clock time) and run production explosion exits."""
    from app.engines.capital_allocator import lot_multiplier, max_lots_for_capital
    from app.engines.explosion_profit import evaluate_explosion_exit
    from app.engines.moment_stage_trail import build_moment_stage_plan
    from app.models.schemas import PaperTrade, Side, StrategyType

    if start_i >= len(series) - 1:
        return None
    t, ep, _ = series[start_i]
    if ep <= 0:
        return None
    units = int(lot_multiplier(symbol) or 20)
    lots = max(1, max_lots_for_capital(symbol, ep))
    win = [series[j][1] for j in range(max(0, start_i - 120), start_i + 1)]
    base = min(win) if win else ep
    off = (ep - base) / base if base > 0 else 0.0
    min_sl_pts = 16.0
    min_sl_pct = 0.18
    stop_pts = max(min_sl_pts, ep * min_sl_pct)
    plan = build_moment_stage_plan(
        entry_premium=ep,
        base_premium=base,
        velocity_3s=3.0,
        volume_surge=2.5,
        session_move_pct=30.0,
        flat_then_vertical=True,
        max_profit=True,
    )
    ctx: dict[str, Any] = {
        "momentType": "flat_then_vertical",
        "ictFlatThenVertical": True,
        "maxProfitCapture": True,
        "ictBasePremium": base,
        "eliteFullLot": True,
        "velocity3s": 3.0,
        "vBaseFtvRunner": True,
        "exitPlan": {
            "stopPoints": round(stop_pts, 2),
            "entryStopPoints": round(stop_pts, 2),
            "targetPoints": 180.0,
        },
    }
    if plan:
        ctx.update(plan)
    wnow = datetime.now(IST)
    tr = PaperTrade(
        id=f"{symbol}:{side}:{strike}",
        symbol=symbol,
        side=Side(side),
        strike=strike,
        entryPremium=ep,
        currentPremium=ep,
        lots=lots,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=wnow,
        bestPnlPoints=0.0,
        entryContext=ctx,
    )
    per_trade_cap = 15_000.0
    best = 0.0
    peak = ep
    et = t
    exit_rec = None
    for j in range(start_i + 1, len(series)):
        tj, pj, _ = series[j]
        tr.openedAt = wnow - timedelta(seconds=(tj - et).total_seconds())
        tr.currentPremium = pj
        best = max(best, pj - ep)
        tr.bestPnlPoints = best
        peak = max(peak, pj)
        v = 2.0 if pj >= peak else -0.8
        tr.entryContext["liveVelocity3s"] = v
        if per_trade_cap > 0 and (pj - ep) * lots * units <= -per_trade_cap:
            exit_rec = (tj, pj, "explosion_per_trade_loss_cap")
            break
        reason, _pnl = evaluate_explosion_exit(tr, pj, tier, units, live_velocity_3s=v)
        if reason:
            exit_rec = (tj, pj, reason)
            break
    if exit_rec is None:
        tj, pj, _ = series[-1]
        exit_rec = (tj, pj, "eod_close")
    xt, xp, reason = exit_rec
    pnl = (xp - ep) * lots * units
    return {
        "entryAt": et.strftime("%H:%M:%S"),
        "entryPremium": round(ep, 1),
        "basePremium": round(base, 1),
        "offBasePct": round(off * 100, 1),
        "lots": lots,
        "exitAt": xt.strftime("%H:%M:%S"),
        "exitPremium": round(xp, 1),
        "movePct": round((xp - ep) / ep * 100, 1),
        "peakPct": round(best / ep * 100, 1),
        "pnlInr": round(pnl, 0),
        "exitReason": reason,
    }


def _scorecard_points(sc: dict[str, Any]) -> list[tuple[datetime, float]]:
    pts: list[tuple[datetime, float]] = []
    if sc.get("baseEndAt") and sc.get("basePremium"):
        pts.append((_parse_ts(sc["baseEndAt"]), _f(sc["basePremium"])))
    if sc.get("verticalAt") and sc.get("verticalPremium"):
        pts.append((_parse_ts(sc["verticalAt"]), _f(sc["verticalPremium"])))
    if sc.get("verticalAt") and sc.get("peakPremium"):
        vt = _parse_ts(sc["verticalAt"])
        extra = _f(sc.get("baseToVerticalSeconds"), 300)
        pts.append((vt + timedelta(seconds=extra * 1.5), _f(sc["peakPremium"])))
    return pts


def run_sweep(
    funnel: dict[str, Any],
    radars: dict[str, dict[str, Any]],
    *,
    date: str,
    scorecard: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    events_by_key = _index_funnel_events(funnel)
    series_cache: dict[str, list[tuple[datetime, float, float]]] = {}

    def series_for_key(key: str) -> list[tuple[datetime, float, float]]:
        if key in series_cache:
            return series_cache[key]
        row = next((r for r in funnel["rows"] if r["key"] == key), None)
        outcome = (row or {}).get("radarOutcome") or (radars.get(key) or {}).get("outcome") or {}
        prem = _build_premium_series(outcome)
        if scorecard and key in scorecard:
            prem = sorted(set(prem + _scorecard_points(scorecard[key])), key=lambda x: x[0])
        sym, side, strike_s = key.split(":")
        strike = float(strike_s)
        spot = 73000.0 if sym == "SENSEX" else 26000.0
        ser = [(t, p, spot) for t, p in prem]
        series_cache[key] = ser
        return ser

    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=IST)
    start = day.replace(hour=9, minute=20, second=0)
    end = day.replace(hour=13, minute=5, second=0)

    results: list[dict[str, Any]] = []
    sim_id = 0

    policies = [
        ("live_fade_CALL", "CALL", True),
        ("force_entry_CALL", "CALL", False),
        ("live_fade_ALL", None, True),
        ("force_entry_ALL", None, False),
    ]

    t = start
    while t <= end:
        for pol_name, side_f, respect_fade in policies:
            pick = _next_selected(
                funnel, t, side=side_f, respect_fade=respect_fade, events_by_key=events_by_key
            )
            sim_id += 1
            rec: dict[str, Any] = {
                "simId": sim_id,
                "policy": pol_name,
                "earliestEntryIst": t.strftime("%H:%M:%S"),
                "sideFilter": side_f or "ALL",
                "respectFadeGate": respect_fade,
            }
            if not pick:
                rec.update({"status": "no_pick", "pnlInr": 0})
                results.append(rec)
                continue
            ts_sel, key, raw = pick
            sym, side, strike_s = key.split(":")
            strike = float(strike_s)
            tier = str(raw.get("tier") or (radars.get(key) or {}).get("tier") or "ELITE")
            ser = series_for_key(key)
            # Entry at selection time (or earliest allowed if later)
            entry_t = max(t, ts_sel)
            entry_p = _premium_at([(x[0], x[1]) for x in ser], entry_t)
            start_i = next((i for i, (st, _, _) in enumerate(ser) if st >= entry_t), 0)
            trade = _replay_forced_entry(
                symbol=sym,
                side=side,
                strike=strike,
                tier=tier,
                series=ser,
                start_i=start_i,
            )
            rec.update({
                "status": "ok" if trade else "replay_miss",
                "selectedAt": ts_sel.strftime("%H:%M:%S"),
                "key": key,
                "tier": tier,
                "grade": raw.get("causalGrade"),
                "entryPremiumEst": round(entry_p or 0, 2),
            })
            if trade:
                rec.update({
                    "entryAt": trade.get("entryAt"),
                    "exitAt": trade.get("exitAt"),
                    "pnlInr": trade.get("pnlInr"),
                    "peakPct": trade.get("peakPct"),
                    "exitReason": trade.get("exitReason"),
                })
            else:
                rec["pnlInr"] = 0
            results.append(rec)
        t += timedelta(minutes=3)

    # Extra: fixed-clock entries on top radar keys (WINNER labels)
    winners = [
        r["key"]
        for r in funnel.get("rows") or []
        if (r.get("radarOutcome") or {}).get("status") == "WINNER"
    ]
    for key in winners[:12]:
        for hm, mm in [(9, 43), (10, 0), (10, 30), (11, 0), (12, 0), (13, 1)]:
            sim_id += 1
            entry_t = day.replace(hour=hm, minute=mm, second=0)
            sym, side, strike_s = key.split(":")
            ser = series_for_key(key)
            start_i = next((i for i, (st, _, _) in enumerate(ser) if st >= entry_t), 0)
            trade = _replay_forced_entry(
                symbol=sym,
                side=side,
                strike=float(strike_s),
                tier=str((radars.get(key) or {}).get("tier") or "ELITE"),
                series=ser,
                start_i=start_i,
            )
            results.append({
                "simId": sim_id,
                "policy": "fixed_clock_WINNER",
                "earliestEntryIst": entry_t.strftime("%H:%M:%S"),
                "key": key,
                "status": "ok" if trade else "replay_miss",
                "pnlInr": (trade or {}).get("pnlInr", 0),
                "entryAt": (trade or {}).get("entryAt"),
                "exitReason": (trade or {}).get("exitReason"),
            })

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--funnel", type=Path, required=True)
    parser.add_argument("--radars", type=Path, required=True)
    parser.add_argument("--date", default="2026-10-29")
    parser.add_argument("--scorecard", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("/opt/cursor/artifacts/first_trade_timing_sweep.json"))
    args = parser.parse_args()

    backend = Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    funnel = _load_funnel(args.funnel)
    radars = _load_radars(args.radars)
    sc_map = None
    if args.scorecard and args.scorecard.exists():
        sc_raw = json.loads(args.scorecard.read_text())
        sc_map = {e["key"]: e for e in sc_raw.get("events") or []}
    results = run_sweep(funnel, radars, date=args.date, scorecard=sc_map)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": args.date,
        "simulationCount": len(results),
        "results": results,
    }
    args.out.write_text(json.dumps(payload, indent=2))

    ok = [r for r in results if r.get("status") == "ok" and r.get("pnlInr") is not None]
    ok.sort(key=lambda r: _f(r.get("pnlInr")), reverse=True)
    print(f"Ran {len(results)} simulations; {len(ok)} with replay PnL")
    print("Top 10:")
    for r in ok[:10]:
        print(
            f"  #{r['simId']} {r.get('policy')} earliest={r.get('earliestEntryIst')} "
            f"{r.get('key')} pnl=₹{r.get('pnlInr'):,.0f} entry={r.get('entryAt')} "
            f"sel={r.get('selectedAt','-')}"
        )
    live = [r for r in ok if r.get("key") == "SENSEX:CALL:73000" and r.get("earliestEntryIst", "").startswith("13:01")]
    print(f"\nLive-aligned 73000@13:01 sims: {live[:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
