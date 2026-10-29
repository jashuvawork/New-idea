#!/usr/bin/env python3
"""First-trade timing sweep using Yahoo Finance 1m index bars as option proxy."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from scripts.first_trade_timing_sweep import (  # noqa: E402
    IST,
    _index_funnel_events,
    _load_funnel,
    _next_selected,
    _replay_forced_entry,
)

YAHOO = {"NIFTY": "^NSEI", "SENSEX": "^BSESN"}

# Live anchors (Oct 29) to pin extrinsic at known fills
CALIBRATION: dict[str, tuple[str, float, str, float]] = {
    "SENSEX:CALL:73000": ("2026-10-29T13:01:26+05:30", 753.5, "SENSEX", 73000.0),
    "NIFTY:CALL:22700": ("2026-10-29T13:32:09+05:30", 248.45, "NIFTY", 22700.0),
    "NIFTY:CALL:22650": ("2026-10-29T09:15:33+05:30", 155.2, "NIFTY", 22650.0),
    "NIFTY:CALL:22800": ("2026-10-29T11:46:16+05:30", 129.55, "NIFTY", 22800.0),
    "SENSEX:CALL:73700": ("2026-10-29T10:11:11+05:30", 146.1, "SENSEX", 73700.0),
    "SENSEX:CALL:73400": ("2026-10-29T09:43:34+05:30", 211.2, "SENSEX", 73400.0),
}


def _fetch_1m(date: str) -> dict[str, pd.DataFrame]:
    start = date
    end = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    out: dict[str, pd.DataFrame] = {}
    for name, ticker in YAHOO.items():
        df = yf.Ticker(ticker).history(start=start, end=end, interval="1m")
        if df.empty:
            raise RuntimeError(f"Yahoo returned no 1m data for {ticker} on {date}")
        if df.index.tz is None:
            df = df.tz_localize("UTC")
        df = df.tz_convert(IST).sort_index()
        out[name] = df
    return out


def _spot_at(df: pd.DataFrame, t: datetime) -> float | None:
    sub = df[df.index <= t]
    if sub.empty:
        return None
    return float(sub.iloc[-1]["Close"])


def _extrinsic(side: str, spot: float, strike: float, premium: float) -> float:
    if side.upper() == "CALL":
        intrinsic = max(0.0, spot - strike)
    else:
        intrinsic = max(0.0, strike - spot)
    return max(0.0, premium - intrinsic)


def _premium_from_index(
    side: str, spot: float, strike: float, extrinsic: float, *, min_p: float = 5.0
) -> float:
    if side.upper() == "CALL":
        intrinsic = max(0.0, spot - strike)
    else:
        intrinsic = max(0.0, strike - spot)
    return max(min_p, intrinsic + extrinsic)


def build_yahoo_premium_series(
    key: str,
    index_bars: dict[str, pd.DataFrame],
    funnel_row: dict[str, Any] | None,
) -> list[tuple[datetime, float, float]]:
    sym, side, strike_s = key.split(":")
    strike = float(strike_s)
    idx_name = sym if sym in index_bars else "NIFTY"
    df = index_bars[idx_name]

    cal = CALIBRATION.get(key)
    if cal:
        ts_s, prem, _, _ = cal
        t_cal = datetime.fromisoformat(ts_s)
        spot_cal = _spot_at(df, t_cal)
        if spot_cal is None:
            spot_cal = float(df.iloc[0]["Close"])
        extr = _extrinsic(side, spot_cal, strike, prem)
    else:
        # Radar detection entry fallback
        ro = (funnel_row or {}).get("radarOutcome") or {}
        t_cal = datetime.fromisoformat(ro["entryAt"]) if ro.get("entryAt") else df.index[0].to_pydatetime()
        prem = float(ro.get("entryPremium") or 100.0)
        spot_cal = _spot_at(df, t_cal) or float(df.iloc[0]["Close"])
        extr = _extrinsic(side, spot_cal, strike, prem)

    series: list[tuple[datetime, float, float]] = []
    for ts, row in df.iterrows():
        t = ts.to_pydatetime()
        spot = float(row["Close"])
        p = _premium_from_index(side, spot, strike, extr)
        series.append((t, p, spot))
    return series


def run_yahoo_sweep(
    funnel: dict[str, Any],
    index_bars: dict[str, pd.DataFrame],
    *,
    date: str,
) -> list[dict[str, Any]]:
    events_by_key = _index_funnel_events(funnel)
    rows_by_key = {r["key"]: r for r in funnel.get("rows") or []}
    series_cache: dict[str, list[tuple[datetime, float, float]]] = {}

    def ser(key: str) -> list[tuple[datetime, float, float]]:
        if key not in series_cache:
            series_cache[key] = build_yahoo_premium_series(
                key, index_bars, rows_by_key.get(key)
            )
        return series_cache[key]

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
                "dataSource": "yahoo_1m_index_proxy",
            }
            if not pick:
                rec.update({"status": "no_pick", "pnlInr": 0})
                results.append(rec)
                continue
            ts_sel, key, raw = pick
            sym, side, strike_s = key.split(":")
            entry_t = max(t, ts_sel)
            s = ser(key)
            start_i = next((i for i, (st, _, _) in enumerate(s) if st >= entry_t), len(s) - 2)
            trade = _replay_forced_entry(
                symbol=sym,
                side=side,
                strike=float(strike_s),
                tier=str(raw.get("tier") or "ELITE"),
                series=s,
                start_i=start_i,
            )
            rec.update({
                "status": "ok" if trade else "replay_miss",
                "selectedAt": ts_sel.strftime("%H:%M:%S"),
                "key": key,
                "yahooSpotAtEntry": round(s[start_i][2], 2) if start_i < len(s) else None,
            })
            if trade:
                rec.update({k: trade[k] for k in (
                    "entryAt", "entryPremium", "exitAt", "pnlInr", "peakPct", "exitReason"
                )})
            else:
                rec["pnlInr"] = 0
            results.append(rec)
        t += timedelta(minutes=3)

    # Fixed clocks on core strikes (15m grid through 15:00)
    for key in [
        "SENSEX:CALL:73000",
        "NIFTY:CALL:22700",
        "NIFTY:CALL:22650",
        "SENSEX:CALL:73700",
    ]:
        s = ser(key)
        sym, side, strike_s = key.split(":")
        t0 = day.replace(hour=9, minute=20, second=0)
        for step in range(0, 6 * 60 + 40, 15):  # 09:20 → ~15:00
            entry_t = t0 + timedelta(minutes=step)
            if entry_t.hour > 15 or (entry_t.hour == 15 and entry_t.minute > 5):
                continue
            sim_id += 1
            start_i = next((i for i, (st, _, _) in enumerate(s) if st >= entry_t), len(s) - 2)
            trade = _replay_forced_entry(
                symbol=sym,
                side=side,
                strike=float(strike_s),
                tier="ELITE",
                series=s,
                start_i=start_i,
            )
            results.append({
                "simId": sim_id,
                "policy": "yahoo_fixed_clock",
                "earliestEntryIst": entry_t.strftime("%H:%M:%S"),
                "key": key,
                "dataSource": "yahoo_1m_index_proxy",
                "status": "ok" if trade else "replay_miss",
                **({k: trade[k] for k in ("entryAt", "pnlInr", "peakPct", "exitReason")} if trade else {"pnlInr": 0}),
            })

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-10-29")
    parser.add_argument("--funnel", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("/opt/cursor/artifacts/first_trade_yahoo_timing_sweep.json"))
    args = parser.parse_args()

    funnel = _load_funnel(args.funnel)
    bars = _fetch_1m(args.date)
    results = run_yahoo_sweep(funnel, bars, date=args.date)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": args.date,
        "dataSource": "Yahoo Finance 1m ^NSEI / ^BSESN; option premium = intrinsic + calibrated extrinsic",
        "simulationCount": len(results),
        "indexBars": {
            k: {"rows": len(v), "from": str(v.index.min()), "to": str(v.index.max())}
            for k, v in bars.items()
        },
        "results": results,
    }
    args.out.write_text(json.dumps(payload, indent=2))

    ok = [r for r in results if r.get("status") == "ok" and r.get("pnlInr") is not None]
    ok.sort(key=lambda r: float(r["pnlInr"]), reverse=True)
    print(f"Yahoo sweep: {len(results)} sims, {len(ok)} with PnL")
    for r in ok[:15]:
        print(
            f"  #{r['simId']} {r.get('policy')} earliest={r.get('earliestEntryIst')} "
            f"{r.get('key')} ₹{float(r.get('pnlInr')):,.0f} spot={r.get('yahooSpotAtEntry')} "
            f"{r.get('exitReason')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
