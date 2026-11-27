#!/usr/bin/env python3
"""Replay all archived premium tapes: index regime + option base vs live ENTERED legs."""

from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IST = ZoneInfo("Asia/Kolkata")

ZIP_DIRS = [
    Path("/tmp/nexusquant/trades/radar_archives"),
    Path("/cursor/stores/self/artifacts/radar-zips"),
    Path("/cursor/stores/self/artifacts/radar-aug25"),
]

TRADE_DIRS = [
    Path("/tmp/nexusquant/trades"),
    Path("/tmp/nexusquant/paper-parity-trades"),
]

EXTRA_TAPES: dict[str, Path] = {
    "2026-11-26": Path("/tmp/premium_tape_1126.jsonl"),
}

MIN_PTS = {"NIFTY": 45.0, "BANKNIFTY": 80.0, "SENSEX": 130.0}
CHOP_BUFFER = 15.0


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        if isinstance(raw, datetime):
            return raw.astimezone(IST) if raw.tzinfo else raw.replace(tzinfo=IST)
        s = str(raw)
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)
    except Exception:
        return None


def _find_zip(date: str) -> Path | None:
    name = f"radar-{date}.zip"
    for d in ZIP_DIRS:
        p = d / name
        if p.is_file() and p.stat().st_size > 500:
            return p
    return None


def _index_series_from_tape(batches: list[dict[str, Any]]) -> dict[str, list[tuple[datetime, float]]]:
    """Per index symbol, spot samples from tape contracts."""
    out: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for batch in batches:
        ts = _parse_ts(batch.get("ts"))
        if ts is None:
            continue
        seen_sym: set[str] = set()
        for c in batch.get("contracts") or []:
            sym = str(c.get("symbol") or "").upper()
            spot = float(c.get("spot") or 0)
            if sym not in {"NIFTY", "SENSEX", "BANKNIFTY"} or spot <= 0 or sym in seen_sym:
                continue
            seen_sym.add(sym)
            out[sym].append((ts, spot))
    return out


def _index_metrics_at(
    series: list[tuple[datetime, float]],
    at: datetime,
    symbol: str,
) -> dict[str, Any]:
    pts = [(t, s) for t, s in series if t <= at and s > 0]
    if not pts:
        return {"regime": "UNKNOWN", "rallyPoints": 0.0, "slidePoints": 0.0, "spot": 0.0}
    lo = min(s for _, s in pts)
    hi = max(s for _, s in pts)
    spot = pts[-1][1]
    rally = round(spot - lo, 1)
    slide = round(hi - spot, 1)
    min_pts = MIN_PTS.get(symbol.upper(), 130.0)
    if rally >= min_pts and rally > slide + CHOP_BUFFER:
        regime = "RALLY"
    elif slide >= min_pts and slide > rally + CHOP_BUFFER:
        regime = "SLIDE"
    else:
        regime = "CHOP"
    return {
        "regime": regime,
        "sessionLow": round(lo, 2),
        "sessionHigh": round(hi, 2),
        "spot": round(spot, 2),
        "rallyPoints": rally,
        "slidePoints": slide,
        "minMovePoints": min_pts,
    }


def _load_tape_zip(zpath: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with zipfile.ZipFile(zpath) as zf:
        with zf.open("premium_tape.jsonl") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _load_tape_path(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _entered_legs(zpath: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(zpath) as zf:
        fn = json.loads(zf.read("funnel.json"))
    legs: list[dict[str, Any]] = []
    for row in fn.get("rows") or []:
        if not row.get("entered"):
            continue
        parts = str(row.get("key") or "::").split(":")
        sym, side, strike_s = (parts + ["", "", "0"])[:3]
        entry_ts = None
        trade_id = None
        for ev in row.get("timeline") or []:
            if ev.get("event") == "ENTERED":
                entry_ts = _parse_ts(ev.get("ts"))
                trade_id = ev.get("tradeId")
                break
        legs.append(
            {
                "key": row.get("key"),
                "symbol": sym.upper(),
                "side": side.upper(),
                "strike": float(strike_s or 0),
                "openedAt": entry_ts,
                "tradeId": trade_id,
                "pnlInr": float(row.get("pnlInr") or 0),
                "outcome": row.get("tradeOutcome"),
            }
        )
    return legs


def _trade_context_index(date: str) -> dict[str, dict[str, Any]]:
    """tradeId -> entryContext snippet."""
    out: dict[str, dict[str, Any]] = {}
    for base in TRADE_DIRS:
        path = base / f"{date}.json"
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text())
        except Exception:
            continue
        for t in raw.get("trades") or []:
            tid = str(t.get("id") or "")
            if not tid:
                continue
            ctx = t.get("entryContext") or {}
            out[tid] = {
                "newSessionBase": bool(ctx.get("newSessionBase")),
                "newBaseKind": ctx.get("newBaseKind"),
                "entryPremium": float(t.get("entryPremium") or 0),
                "velocity3s": float(ctx.get("velocity3s") or 0),
                "staleIct": float(
                    ctx.get("ictBasePremium") or ctx.get("localBaseBasePremium") or 0
                ),
                "fakeExplosionTrap": bool(ctx.get("fakeExplosionTrap")),
            }
    ext = Path(f"/tmp/hist-{date.replace('-', '')[-4:]}.json")
    if date == "2026-11-26" and Path("/tmp/hist-1126.json").is_file():
        ext = Path("/tmp/hist-1126.json")
    if ext.is_file():
        try:
            raw = json.loads(ext.read_text())
            for t in raw.get("trades") or []:
                tid = str(t.get("id") or "")
                ctx = t.get("entryContext") or {}
                out[tid] = {
                    "newSessionBase": bool(ctx.get("newSessionBase")),
                    "newBaseKind": ctx.get("newBaseKind"),
                    "entryPremium": float(t.get("entryPremium") or 0),
                    "velocity3s": float(ctx.get("velocity3s") or 0),
                    "staleIct": float(
                        ctx.get("ictBasePremium") or ctx.get("localBaseBasePremium") or 0
                    ),
                    "fakeExplosionTrap": bool(ctx.get("fakeExplosionTrap")),
                }
        except Exception:
            pass
    return out


def _hydrate_and_eval(
    batches: list[dict[str, Any]],
    leg: dict[str, Any],
    settings: Any,
) -> dict[str, Any]:
    from app.engines.explosion_detector import _open_key
    from app.models.schemas import Side

    at = leg.get("openedAt")
    if not at:
        return {"baseEval": "SKIP_NO_ENTRY_TS"}

    sym = leg["symbol"]
    side = leg["side"]
    strike = leg["strike"]
    side_e = Side.CALL if side == "CALL" else Side.PUT
    key = _open_key(sym, strike, side_e)

    ctx = leg.get("ctx") or {}
    premium = float(ctx.get("entryPremium") or 0)
    if premium <= 0:
        for batch in batches:
            ts = _parse_ts(batch.get("ts"))
            if ts is None or ts > at:
                break
            for c in batch.get("contracts") or []:
                if (
                    str(c.get("symbol") or "").upper() == sym
                    and str(c.get("side") or "").upper() == side
                    and float(c.get("strike") or 0) == strike
                ):
                    premium = float(c.get("premium") or 0)

    import app.engines.explosion_detector as ed
    from app.engines.explosion_detector import _record_local_base, _roll_session
    from app.engines.ict_breakout_monitor import _detect_recent_window_base
    from app.engines.new_session_base import new_session_base_identify

    _roll_session(at)
    ed._session_low.clear()
    ed._session_peak.clear()
    ed._local_base_hist.clear()

    for batch in batches:
        ts = _parse_ts(batch.get("ts"))
        if ts is None or ts > at:
            break
        for contract in batch.get("contracts") or []:
            c_sym = str(contract.get("symbol") or "").upper()
            c_side = str(contract.get("side") or "").upper()
            try:
                c_side_e = Side(c_side)
            except Exception:
                continue
            c_strike = float(contract.get("strike") or 0)
            c_prem = float(contract.get("premium") or 0)
            if not c_sym or c_strike <= 0 or c_prem <= 0:
                continue
            c_key = _open_key(c_sym, c_strike, c_side_e)
            if c_key != key:
                continue
            sess_low = float(contract.get("sessionLow") or 0)
            sess_peak = float(contract.get("sessionPeak") or 0)
            if sess_low > 0:
                cur = ed._session_low.get(c_key)
                if cur is None or sess_low < cur:
                    ed._session_low[c_key] = sess_low
            if sess_peak > 0:
                cur_p = ed._session_peak.get(c_key)
                if cur_p is None or sess_peak > cur_p:
                    ed._session_peak[c_key] = sess_peak
            ed._record_local_base(c_key, ts, c_prem)
            ed._session_low[c_key] = min(ed._session_low.get(c_key, c_prem), c_prem)
            ed._session_peak[c_key] = max(ed._session_peak.get(c_key, c_prem), c_prem)

    if premium <= 0:
        return {"baseEval": "SKIP_NO_PREMIUM"}

    _roll_session(at)
    sl = float(ed._session_low.get(key) or 0)
    sp = float(ed._session_peak.get(key) or 0)

    ok, kind, _meta = new_session_base_identify(
        sym,
        strike,
        side_e,
        premium,
        velocity_3s=float(ctx.get("velocity3s") or 0),
        stale_ict_base=float(ctx.get("staleIct") or 0),
        settings=settings,
    )
    found, _rb, base_rel = _detect_recent_window_base(
        symbol=sym,
        strike=strike,
        side=side_e,
        premium=premium,
        settings=settings,
    )
    fall_peak = (sp - premium) / sp * 100 if sp > premium > 0 else 0.0
    off_low = (premium - sl) / sl * 100 if sl > 0 else 0.0

    real_base = (
        found
        and 2.0 <= off_low <= 22.0
        and (fall_peak >= 8.0 or kind in {"post_rip_pullback", "local_base_retest"})
    )
    ghost = bool(ok and kind == "session_trough" and (fall_peak < 5.0 or not found))

    return {
        "newSessionBaseReplay": ok,
        "newBaseKindReplay": kind,
        "recentWindowBase": found,
        "offSessionLowPct": round(off_low, 2),
        "fallFromPeakPct": round(fall_peak, 2),
        "realBase": real_base,
        "ghostBase": ghost,
    }


def _policy_verdict(index: dict[str, Any], leg: dict[str, Any], base: dict[str, Any]) -> str:
    regime = index.get("regime") or "UNKNOWN"
    side = leg.get("side")
    real = base.get("realBase")
    ghost = base.get("ghostBase")

    if regime == "UNKNOWN" or base.get("baseEval", "").startswith("SKIP"):
        return "UNKNOWN"

    side_ok = (side == "CALL" and regime == "RALLY") or (side == "PUT" and regime == "SLIDE")
    side_bad = (side == "CALL" and regime == "SLIDE") or (side == "PUT" and regime == "RALLY")

    if ghost or (base.get("newSessionBaseReplay") and not real):
        return "BLOCK_GHOST"
    if side_bad:
        return "BLOCK_SIDE_VS_INDEX"
    if side_ok and real:
        return "ALLOW_ALIGNED"
    if side_ok and not real:
        return "WAIT_BASE"
    if not side_ok and real:
        return "BLOCK_COUNTER_REGIME"
    return "CHOP_DISCIPLINE"


def main() -> int:
    from tests.mock_defaults import settings_mock

    settings = settings_mock()
    settings.new_session_base_session_trough_stamp_enabled = True

    dates: set[str] = set()
    for d in ZIP_DIRS:
        for z in d.glob("radar-20*.zip"):
            dates.add(z.stem.replace("radar-", ""))
    dates.update(EXTRA_TAPES.keys())
    dates_sorted = sorted(dates)

    all_rows: list[dict[str, Any]] = []
    per_day: list[dict[str, Any]] = []
    verdict_counter: Counter = Counter()
    pnl_by_verdict: defaultdict[str, float] = defaultdict(float)

    for i, date in enumerate(dates_sorted):
        print(f"[{i+1}/{len(dates_sorted)}] {date}", flush=True)
        zpath = _find_zip(date)
        if zpath:
            batches = _load_tape_zip(zpath)
            legs = _entered_legs(zpath)
        elif date in EXTRA_TAPES and EXTRA_TAPES[date].is_file():
            batches = _load_tape_path(EXTRA_TAPES[date])
            legs = []
            raw = json.loads(Path("/tmp/hist-1126.json").read_text())
            for t in raw.get("trades") or []:
                if str(t.get("status", "")).upper() != "CLOSED":
                    continue
                legs.append(
                    {
                        "key": f"{t.get('symbol')}:{t.get('side')}:{int(float(t.get('strike') or 0))}",
                        "symbol": str(t.get("symbol")).upper(),
                        "side": str(t.get("side")).upper(),
                        "strike": float(t.get("strike") or 0),
                        "openedAt": _parse_ts(t.get("openedAt")),
                        "tradeId": t.get("id"),
                        "pnlInr": float(t.get("pnlInr") or 0),
                        "outcome": "WIN" if float(t.get("pnlInr") or 0) > 0 else "LOSS",
                    }
                )
        else:
            continue

        index_series = _index_series_from_tape(batches)
        ctx_by_id = _trade_context_index(date)

        day_rows = []
        for leg in legs:
            tid = str(leg.get("tradeId") or "")
            leg["ctx"] = ctx_by_id.get(tid, {})
            sym = leg["symbol"]
            at = leg.get("openedAt")
            idx = _index_metrics_at(index_series.get(sym, []), at, sym) if at else {}
            base = _hydrate_and_eval(batches, leg, settings)
            verdict = _policy_verdict(idx, leg, base)
            row = {
                "date": date,
                **leg,
                "index": idx,
                "base": base,
                "policyVerdict": verdict,
                "liveNsb": leg["ctx"].get("newSessionBase"),
                "liveNsbKind": leg["ctx"].get("newBaseKind"),
            }
            day_rows.append(row)
            all_rows.append(row)
            verdict_counter[verdict] += 1
            pnl_by_verdict[verdict] += float(leg.get("pnlInr") or 0)

        day_summary = {
            "date": date,
            "legs": len(day_rows),
            "netInr": round(sum(r.get("pnlInr") or 0 for r in day_rows), 2),
            "verdictMix": dict(Counter(r["policyVerdict"] for r in day_rows)),
            "ghostWithLiveNsb": sum(
                1
                for r in day_rows
                if r.get("liveNsb") and r["policyVerdict"] in ("BLOCK_GHOST", "BLOCK_SIDE_VS_INDEX")
            ),
            "alignedWins": sum(
                1 for r in day_rows if r["policyVerdict"] == "ALLOW_ALIGNED" and (r.get("pnlInr") or 0) > 0
            ),
        }
        per_day.append(day_summary)

    nsb_live = [r for r in all_rows if r.get("liveNsb")]
    nsb_ghost = [r for r in nsb_live if r["policyVerdict"] == "BLOCK_GHOST"]

    report = {
        "sessions": len(per_day),
        "totalEnteredLegs": len(all_rows),
        "verdictTotals": dict(verdict_counter),
        "pnlInrByVerdict": {k: round(v, 2) for k, v in pnl_by_verdict.items()},
        "liveNewSessionBaseLegs": len(nsb_live),
        "liveNsbWouldBlockAsGhost": len(nsb_ghost),
        "liveNsbGhostPnlInr": round(sum(r.get("pnlInr") or 0 for r in nsb_ghost), 2),
        "perDay": per_day,
        "entries": all_rows,
    }

    out = Path("/opt/cursor/artifacts/index-aligned-historical-replay.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: report[k] for k in report if k != "entries"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())