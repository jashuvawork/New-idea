#!/usr/bin/env python3
"""60+ day local eval: SENSEX CALL + NIFTY PUT open lanes (Yahoo 5m proxy).

Mirrors production defaults in open_index_lane (first lift, off-open/off-extreme,
09:20 entry). Combined portfolio = up to one signal per index per session day.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.config import Settings

# Reuse Yahoo fetch from sibling script
from scripts.morning_yahoo_strategy_search import (  # noqa: E402
    SYMBOLS,
    _fetch_5m,
    _option_proxy_pnl,
    _session_days,
)

OUT = Path("/opt/cursor/artifacts/morning_open_lane_60d_eval.json")


@dataclass(frozen=True)
class LaneRule:
    index: str
    side: str
    min_off_open: float
    max_off_open: float
    min_off_extreme: float
    max_off_extreme: float
    min_range: float
    require_first_lift: bool


def _morning_bars(day_df: pd.DataFrame) -> pd.DataFrame:
    return day_df.loc[[time(9, 15) <= ts.time() <= time(9, 45) for ts in day_df.index]]


def _day_feat(day_df: pd.DataFrame, d: date, index: str) -> dict[str, Any] | None:
    morning = _morning_bars(day_df)
    if len(morning) < 3:
        return None
    cash_open = float(day_df.iloc[0]["Open"])
    low_m = float(morning["Low"].min())
    high_m = float(morning["High"].max())
    close_945 = float(morning.iloc[-1]["Close"])
    b920 = morning[morning.index.time >= time(9, 20)]
    if b920.empty:
        return None
    px920 = float(b920.iloc[0]["Open"])
    off_open = (close_945 - cash_open) / cash_open * 100.0
    off_low = (close_945 - low_m) / low_m * 100.0 if low_m else 0.0
    off_high = (high_m - close_945) / cash_open * 100.0 if cash_open else 0.0
    range_pct = (high_m - low_m) / cash_open * 100.0 if cash_open else 0.0
    first_lift_call = close_945 > low_m * 1.0015 and close_945 > cash_open * 0.999
    first_lift_put = close_945 < high_m * 0.9985 and close_945 < cash_open * 1.001

    forward = day_df.loc[
        (day_df.index.time > time(9, 45)) & (day_df.index.time <= time(10, 0))
    ]
    fwd_high = float(forward["High"].max()) if not forward.empty else close_945
    fwd_low = float(forward["Low"].min()) if not forward.empty else close_945
    close_10 = float(forward.iloc[-1]["Close"]) if not forward.empty else close_945

    return {
        "date": d.isoformat(),
        "index": index,
        "cashOpen": cash_open,
        "px920": px920,
        "close945": close_945,
        "offOpenPct": off_open,
        "offLowPct": off_low,
        "offHighPct": off_high,
        "rangePct": range_pct,
        "firstLiftCall": first_lift_call,
        "firstLiftPut": first_lift_put,
        "close10": close_10,
        "fwdHigh": fwd_high,
        "fwdLow": fwd_low,
    }


def _passes(feat: dict[str, Any], rule: LaneRule) -> bool:
    if feat["rangePct"] < rule.min_range:
        return False
    if rule.side == "CALL":
        if rule.require_first_lift and not feat["firstLiftCall"]:
            return False
        if not (rule.min_off_open <= feat["offOpenPct"] <= rule.max_off_open):
            return False
        if not (rule.min_off_extreme <= feat["offLowPct"] <= rule.max_off_extreme):
            return False
        return True
    if rule.require_first_lift and not feat["firstLiftPut"]:
        return False
    if not (rule.min_off_open <= -feat["offOpenPct"] <= rule.max_off_open):
        return False
    if not (rule.min_off_extreme <= feat["offHighPct"] <= rule.max_off_extreme):
        return False
    return True


def _rules_from_settings(s: Settings) -> tuple[LaneRule, LaneRule]:
    max_local = float(s.open_index_lane_max_local_base_pct or 15.0)
    sensex = LaneRule(
        index="SENSEX",
        side="CALL",
        min_off_open=0.03,
        max_off_open=1.2,
        min_off_extreme=0.0,
        max_off_extreme=max_local,
        min_range=0.0,
        require_first_lift=bool(s.open_index_lane_require_first_lift),
    )
    nifty = LaneRule(
        index="NIFTY",
        side="PUT",
        min_off_open=0.03,
        max_off_open=1.2,
        min_off_extreme=0.0,
        max_off_extreme=max_local,
        min_range=0.0,
        require_first_lift=bool(s.open_index_lane_require_first_lift),
    )
    return sensex, nifty


def _build_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, ysym in SYMBOLS.items():
        df = _fetch_5m(ysym)
        for d in _session_days(df):
            day_df = df.loc[df.index.date == d]
            feat = _day_feat(day_df, d, idx)
            if feat:
                rows.append(feat)
    return rows


def _eval_rows(rows: list[dict[str, Any]], s: Settings) -> dict[str, Any]:
    sensex_rule, nifty_rule = _rules_from_settings(s)
    trades: list[dict[str, Any]] = []
    for feat in rows:
        rule = sensex_rule if feat["index"] == "SENSEX" else nifty_rule
        if not _passes(feat, rule):
            continue
        entry = feat["px920"]
        pnl, win = _option_proxy_pnl(rule.side, entry, feat)
        trades.append(
            {
                **feat,
                "side": rule.side,
                "pnlInr": pnl,
                "win": win,
            }
        )

    def split_metrics(subset: list[dict[str, Any]]) -> dict[str, Any]:
        if not subset:
            return {"trades": 0, "winRate": 0.0, "netPnlInr": 0}
        wins = sum(1 for t in subset if t["win"])
        return {
            "trades": len(subset),
            "wins": wins,
            "losses": len(subset) - wins,
            "winRate": wins / len(subset),
            "netPnlInr": sum(t["pnlInr"] for t in subset),
        }

    by_index = {
        idx: split_metrics([t for t in trades if t["index"] == idx])
        for idx in ("NIFTY", "SENSEX")
    }
    full = split_metrics(trades)
    rows_sorted = sorted(rows, key=lambda r: r["date"])
    mid = len(rows_sorted) // 2
    train_dates = {r["date"] for r in rows_sorted[:mid]}
    test_dates = {r["date"] for r in rows_sorted[mid:]}
    oos = {
        "train": split_metrics([t for t in trades if t["date"] in train_dates]),
        "test": split_metrics([t for t in trades if t["date"] in test_dates]),
    }
    return {
        "combined": full,
        "byIndex": by_index,
        "oos5050": oos,
        "trades": trades,
    }


def _radar_lane_eval(s: Settings) -> dict[str, Any]:
    """Premium-tape morning window with open lanes (available archive days only)."""
    from app.config import set_settings_override
    from app.engines.eod_local_base_replay import replay_local_base_day

    s = s.model_copy(
        update={
            "radar_archive_dir": "/tmp/eod_audit_archives",
            "trade_store_dir": "/tmp/eod_audit_archives/trades",
            "eod_replay_live_session_gates_enabled": True,
            "open_index_lane_enabled": True,
            "open_sensex_call_lane_enabled": True,
            "open_nifty_put_lane_enabled": True,
        }
    )
    set_settings_override(s)

    dates = [
        "2026-10-21",
        "2026-10-22",
        "2026-10-23",
        "2026-10-26",
        "2026-10-27",
    ]
    per_day: list[dict[str, Any]] = []
    all_trades: list[dict] = []
    for d in dates:
        zip_path = Path(s.radar_archive_dir) / f"radar-{d}.zip"
        if not zip_path.exists():
            continue
        rep = replay_local_base_day(
            d,
            settings=s,
            window_start="09:15:00",
            window_end="09:45:59",
        )
        trades = list(rep.get("trades") or [])
        per_day.append(
            {
                "date": d,
                "status": rep.get("status"),
                "trades": len(trades),
                "netPnlInr": rep.get("netPnlInr", 0),
            }
        )
        all_trades.extend(trades)

    wins = sum(1 for t in all_trades if float(t.get("pnlInr") or 0) > 0)
    n = len(all_trades)
    return {
        "dates": dates,
        "perDay": per_day,
        "combined": {
            "trades": n,
            "winRate": wins / n if n else 0.0,
            "netPnlInr": sum(float(t.get("pnlInr") or 0) for t in all_trades),
        },
        "note": "Option tape replay with open_index_lane merge + replay clock (09:20–09:45).",
    }


def main() -> int:
    s = Settings(
        open_index_lane_enabled=True,
        open_sensex_call_lane_enabled=True,
        open_nifty_put_lane_enabled=True,
    )
    rows = _build_rows()
    days_per = len({(r["date"], r["index"]) for r in rows}) // 2
    yahoo = _eval_rows(rows, s)
    radar = _radar_lane_eval(s)

    out = {
        "settings": {
            "openIndexLane": True,
            "sensexCallLane": True,
            "niftyPutLane": True,
            "requireFirstLift": s.open_index_lane_require_first_lift,
            "maxLocalBasePct": s.open_index_lane_max_local_base_pct,
        },
        "yahoo60d": {
            "indexDaysEach": days_per,
            "dateRange": {
                "first": min(r["date"] for r in rows),
                "last": max(r["date"] for r in rows),
            },
            **{k: v for k, v in yahoo.items() if k != "trades"},
            "sampleTrades": yahoo["trades"][:12],
        },
        "radarPremiumReplayMorning": radar,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
