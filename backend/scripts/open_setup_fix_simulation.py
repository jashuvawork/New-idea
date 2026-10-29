#!/usr/bin/env python3
"""Compare open-setup policy variants on one session (Yahoo 1m + funnel)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from scripts.first_trade_yahoo_timing_sweep import (  # noqa: E402
    CALIBRATION,
    build_yahoo_premium_series,
    _fetch_1m,
)
from scripts.first_trade_timing_sweep import (  # noqa: E402
    IST,
    _index_funnel_events,
    _load_funnel,
    _replay_forced_entry,
)

YAHOO = {"NIFTY": "^NSEI", "SENSEX": "^BSESN"}


@dataclass(frozen=True)
class Policy:
    name: str
    description: str


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _spot_series(df: pd.DataFrame) -> list[tuple[datetime, float]]:
    return [(ts.to_pydatetime(), float(row["Close"])) for ts, row in df.iterrows()]


def _spot_at(spots: list[tuple[datetime, float]], t: datetime) -> float | None:
    for ts, px in reversed(spots):
        if ts <= t:
            return px
    return spots[0][1] if spots else None


def _cash_open(spots: list[tuple[datetime, float]]) -> float:
    return spots[0][1] if spots else 0.0


def _collect_candidates(
    funnel: dict[str, Any],
    events_by_key: dict[str, list],
    after: datetime,
    before: datetime,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in funnel.get("rows") or []:
        key = row["key"]
        sym, side, strike_s = key.split(":")
        for ts, ev, raw in events_by_key.get(key, []):
            if ev != "SELECTED" or ts < after or ts > before:
                continue
            fade = False
            for ts2, ev2, raw2 in events_by_key.get(key, []):
                if ts2 <= ts:
                    continue
                if (ts2 - ts).total_seconds() > 5:
                    break
                if ev2 == "ORDER_REJECTED" and raw2.get("reason") in (
                    "exec_premium_fading_at_execution",
                    "exec_mtf_premium_1m_fading",
                ):
                    fade = True
                    break
            out.append({
                "ts": ts,
                "key": key,
                "symbol": sym,
                "side": side,
                "strike": float(strike_s),
                "tier": raw.get("tier"),
                "grade": (raw.get("causalGrade") or "").upper(),
                "rank": float(raw.get("causalRankScore") or raw.get("selectionScore") or 0),
                "fadeBlocked": fade,
                "raw": raw,
            })
    out.sort(key=lambda x: x["ts"])
    return out


def _lane_side_ok(c: dict[str, Any]) -> bool:
    """Production default: SENSEX CALL+PUT lanes; NIFTY PUT opt-in."""
    if c["symbol"] == "SENSEX" and c["side"] in ("CALL", "PUT"):
        return True
    if c["symbol"] == "NIFTY" and c["side"] == "PUT":
        return False
    return False


def _side_align_ok(c: dict[str, Any], spot: float, cash_open: float) -> bool:
    if cash_open <= 0:
        return True
    move_pct = (spot - cash_open) / cash_open * 100.0
    if move_pct >= 0.10 and c["side"] == "PUT":
        return False
    if move_pct <= -0.10 and c["side"] == "CALL":
        return False
    return True


def _itm_call(c: dict[str, Any], spot: float) -> bool:
    if c["side"] != "CALL":
        return c["side"] == "PUT" and spot < c["strike"]
    return spot >= c["strike"]


def _itm_depth_ok(c: dict[str, Any], spot: float, max_points: float = 800.0) -> bool:
    if c["side"] == "CALL":
        if spot < c["strike"]:
            return False
        return (spot - c["strike"]) <= max_points + 1e-6
    if spot > c["strike"]:
        return False
    return (c["strike"] - spot) <= min(max_points, 400.0) + 1e-6


def _combined_prod_pred(c: dict[str, Any], spot: float, op: float) -> bool:
    """Mirrors open_setup_guards production defaults."""
    if not _lane_side_ok(c):
        return False
    if not _side_align_ok(c, spot, op):
        return False
    if not _side_confirm(c, spot, op):
        return False
    if not _itm_depth_ok(c, spot, 800.0):
        return False
    return True


def _side_confirm(c: dict[str, Any], spot: float, cash_open: float) -> bool:
    if cash_open <= 0:
        return True
    if c["side"] == "CALL":
        return spot >= cash_open * 1.0002
    return spot <= cash_open * 0.9998


def _would_fill(
    c: dict[str, Any],
    *,
    fade_bypass: bool,
    fade_bypass_rank90: bool = False,
) -> bool:
    if not c["fadeBlocked"]:
        return True
    if not fade_bypass:
        return False
    if fade_bypass_rank90:
        return c["rank"] >= 90.0 or c["grade"] == "S"
    return True


def _pick_first(
    cands: list[dict[str, Any]],
    pred: Callable[[dict[str, Any]], bool],
    *,
    prefer_highest_rank: bool,
) -> dict[str, Any] | None:
    ok = [c for c in cands if pred(c)]
    if not ok:
        return None
    if prefer_highest_rank:
        return max(ok, key=lambda x: (x["rank"], -x["ts"].timestamp()))
    return ok[0]


POLICIES: list[tuple[Policy, Callable[[dict[str, Any], float, float], bool], dict[str, Any]]] = []


def _register():
    global POLICIES
    POLICIES = [
        (
            Policy("P0_baseline_live_fade", "Today-like: any SELECTED, respect fade"),
            lambda c, spot, op: True,
            {"fade_bypass": False, "prefer_rank": False, "open_only": True},
        ),
        (
            Policy("P1_open_lane_only", "SENSEX CALL lane only (09:20-09:45)"),
            lambda c, spot, op: _lane_side_ok(c),
            {"fade_bypass": False, "prefer_rank": False, "open_only": True},
        ),
        (
            Policy("P2_lane_plus_side_confirm", "P1 + index side vs cash open"),
            lambda c, spot, op: _lane_side_ok(c) and _side_confirm(c, spot, op),
            {"fade_bypass": False, "prefer_rank": False, "open_only": True},
        ),
        (
            Policy("P3_lane_side_itm", "P2 + ITM CALL on spot"),
            lambda c, spot, op: _lane_side_ok(c)
            and _side_confirm(c, spot, op)
            and _itm_call(c, spot),
            {"fade_bypass": False, "prefer_rank": False, "open_only": True},
        ),
        (
            Policy("P4_grade_S_only_open", "P3 but causal grade S only"),
            lambda c, spot, op: _lane_side_ok(c)
            and _side_confirm(c, spot, op)
            and _itm_call(c, spot)
            and c["grade"] == "S",
            {"fade_bypass": False, "prefer_rank": False, "open_only": True},
        ),
        (
            Policy("P5_rank90_plus_itm_lane", "P3 + rank score >= 90"),
            lambda c, spot, op: _lane_side_ok(c)
            and _side_confirm(c, spot, op)
            and _itm_call(c, spot)
            and c["rank"] >= 90.0,
            {"fade_bypass": False, "prefer_rank": True, "open_only": True},
        ),
        (
            Policy("P6_open_fade_bypass_ftv", "P3 + open fade bypass (simulate fill on fade)"),
            lambda c, spot, op: _lane_side_ok(c)
            and _side_confirm(c, spot, op)
            and _itm_call(c, spot),
            {"fade_bypass": True, "prefer_rank": False, "open_only": True},
        ),
        (
            Policy("P7_open_fade_bypass_rank90", "P6 + rank >= 90 only"),
            lambda c, spot, op: _lane_side_ok(c)
            and _side_confirm(c, spot, op)
            and _itm_call(c, spot)
            and c["rank"] >= 90.0,
            {"fade_bypass": True, "prefer_rank": True, "open_only": True},
        ),
        (
            Policy("P8_block_all_open_puts", "Any symbol but block PUT 09:20-09:45"),
            lambda c, spot, op: c["side"] == "CALL",
            {"fade_bypass": False, "prefer_rank": False, "open_only": True},
        ),
        (
            Policy("P9_nifty_sensex_call_itm", "Both indices CALL + ITM + side confirm"),
            lambda c, spot, op: c["side"] == "CALL"
            and _side_confirm(c, spot, op)
            and _itm_call(c, spot),
            {"fade_bypass": False, "prefer_rank": True, "open_only": True},
        ),
        (
            Policy("P10_defer_window_1000", "P3 picks but earliest fill 10:00 IST"),
            lambda c, spot, op: _lane_side_ok(c)
            and _side_confirm(c, spot, op)
            and _itm_call(c, spot),
            {"fade_bypass": False, "prefer_rank": True, "open_only": False, "defer_until": (10, 0)},
        ),
        (
            Policy("P11_defer_1000_fade_bypass90", "10:00 + P7 rules"),
            lambda c, spot, op: _lane_side_ok(c)
            and _side_confirm(c, spot, op)
            and _itm_call(c, spot)
            and c["rank"] >= 90.0,
            {"fade_bypass": True, "prefer_rank": True, "open_only": False, "defer_until": (10, 0)},
        ),
        (
            Policy("P12_open_elite_only_itm", "ELITE tier + ITM + SENSEX CALL lane"),
            lambda c, spot, op: _lane_side_ok(c)
            and _itm_call(c, spot)
            and str(c.get("tier") or "").upper() == "ELITE",
            {"fade_bypass": True, "prefer_rank": True, "open_only": True},
        ),
        (
            Policy(
                "P13_combined_production",
                "Lane + side + ITM depth + rank90 fade bypass (production bundle)",
            ),
            _combined_prod_pred,
            {
                "fade_bypass": True,
                "fade_bypass_rank90": True,
                "prefer_rank": True,
                "open_only": True,
            },
        ),
    ]


def simulate_day(
    funnel: dict[str, Any],
    index_bars: dict[str, pd.DataFrame],
    *,
    date: str,
) -> list[dict[str, Any]]:
    _register()
    events_by_key = _index_funnel_events(funnel)
    rows_by_key = {r["key"]: r for r in funnel.get("rows") or []}
    spots = {
        "NIFTY": _spot_series(index_bars["NIFTY"]),
        "SENSEX": _spot_series(index_bars["SENSEX"]),
    }
    series_cache: dict[str, list] = {}

    def ser(key: str):
        if key not in series_cache:
            series_cache[key] = build_yahoo_premium_series(
                key, index_bars, rows_by_key.get(key)
            )
        return series_cache[key]

    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=IST)
    open_start = day.replace(hour=9, minute=20, second=0)
    open_end = day.replace(hour=9, minute=45, second=0)
    session_end = day.replace(hour=15, minute=10, second=0)

    results: list[dict[str, Any]] = []
    sim_id = 0

    for policy, pred, opts in POLICIES:
        defer = opts.get("defer_until")
        if defer:
            win_start = day.replace(hour=defer[0], minute=defer[1], second=0)
            win_end = session_end
        elif opts.get("open_only"):
            win_start, win_end = open_start, open_end
        else:
            win_start, win_end = open_start, session_end

        cands = _collect_candidates(funnel, events_by_key, win_start, win_end)
        idx_spots = spots["SENSEX"]  # lane default index
        cash_open = _cash_open(idx_spots)

        # evaluate at multiple "ready" clocks within window
        clocks = []
        t = win_start
        while t <= win_end:
            clocks.append(t)
            t += timedelta(minutes=5)
        if defer:
            t = win_start
            while t <= day.replace(hour=13, minute=0):
                clocks.append(t)
                t += timedelta(minutes=15)

        for clock in clocks:
            sim_id += 1
            sub = [c for c in cands if c["ts"] >= clock]

            def _pred(c: dict[str, Any]) -> bool:
                sym = c["symbol"] if c["symbol"] in spots else "SENSEX"
                s = _spot_at(spots[sym], clock) or _cash_open(spots[sym])
                o = _cash_open(spots[sym])
                return pred(c, s, o)

            pick = _pick_first(
                sub,
                _pred,
                prefer_highest_rank=bool(opts.get("prefer_rank")),
            )
            rec: dict[str, Any] = {
                "simId": sim_id,
                "policy": policy.name,
                "policyDesc": policy.description,
                "readyClockIst": clock.strftime("%H:%M:%S"),
                "window": f"{win_start.strftime('%H:%M')}-{win_end.strftime('%H:%M')}",
            }
            if not pick:
                rec.update({"status": "no_trade", "pnlInr": 0, "fills": 0})
                results.append(rec)
                continue
            if not _would_fill(
                pick,
                fade_bypass=bool(opts.get("fade_bypass")),
                fade_bypass_rank90=bool(opts.get("fade_bypass_rank90")),
            ):
                rec.update({
                    "status": "fade_blocked",
                    "key": pick["key"],
                    "selectedAt": pick["ts"].strftime("%H:%M:%S"),
                    "pnlInr": 0,
                    "fills": 0,
                })
                results.append(rec)
                continue

            key = pick["key"]
            s = ser(key)
            entry_t = max(clock, pick["ts"])
            start_i = next((i for i, (st, _, _) in enumerate(s) if st >= entry_t), len(s) - 2)
            sym, side, strike_s = key.split(":")
            trade = _replay_forced_entry(
                symbol=sym,
                side=side,
                strike=float(strike_s),
                tier=str(pick.get("tier") or "ELITE"),
                series=s,
                start_i=start_i,
            )
            rec.update({
                "status": "filled" if trade else "replay_miss",
                "key": key,
                "grade": pick["grade"],
                "rank": pick["rank"],
                "fadeWouldBlock": pick["fadeBlocked"],
                "selectedAt": pick["ts"].strftime("%H:%M:%S"),
                "fills": 1 if trade else 0,
                "pnlInr": (trade or {}).get("pnlInr", 0),
                "entryAt": (trade or {}).get("entryAt"),
                "exitReason": (trade or {}).get("exitReason"),
                "peakPct": (trade or {}).get("peakPct"),
            })
            results.append(rec)

    return results


def aggregate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from collections import defaultdict

    by_pol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_pol[r["policy"]].append(r)
    summary = []
    for pol, rows in sorted(by_pol.items()):
        filled = [r for r in rows if r.get("status") == "filled"]
        blocked = [r for r in rows if r.get("status") == "fade_blocked"]
        best = max(filled, key=lambda x: float(x.get("pnlInr") or 0), default=None)
        summary.append({
            "policy": pol,
            "simRows": len(rows),
            "filled": len(filled),
            "fadeBlocked": len(blocked),
            "bestPnlInr": float(best["pnlInr"]) if best else 0,
            "bestClock": best.get("readyClockIst") if best else None,
            "bestKey": best.get("key") if best else None,
            "avgFilledPnl": round(
                sum(float(r.get("pnlInr") or 0) for r in filled) / max(len(filled), 1),
                0,
            ),
        })
    summary.sort(key=lambda x: x["bestPnlInr"], reverse=True)
    return summary


def main() -> int:
    date = "2026-10-29"
    funnel_path = Path("/tmp/funnel_oct29.json")
    if not funnel_path.exists():
        print("Missing funnel; fetch first")
        return 1
    funnel = _load_funnel(funnel_path)
    bars = _fetch_1m(date)
    results = simulate_day(funnel, bars, date=date)
    summary = aggregate(results)
    out = Path("/opt/cursor/artifacts/open_setup_fix_simulation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date,
        "simulationCount": len(results),
        "dataSource": "Yahoo 1m + funnel SELECT/fade + explosion exits",
        "liveActualNetInr": 25824,
        "policySummary": summary,
        "results": results,
    }
    out.write_text(json.dumps(payload, indent=2))
    print(f"Ran {len(results)} policy×clock sims")
    print("\nPolicy ranking (best single fill per policy):")
    for s in summary:
        print(
            f"  {s['policy']}: best=₹{s['bestPnlInr']:,.0f} @ {s['bestClock']} {s['bestKey']} "
            f"filled={s['filled']}/{s['simRows']} fadeBlocked={s['fadeBlocked']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
