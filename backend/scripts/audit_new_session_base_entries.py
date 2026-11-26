#!/usr/bin/env python3
"""Replay new_session_base_identify at live entry times using stored premium tape."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IST = ZoneInfo("Asia/Kolkata")


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


def _hydrate_tape_through(
    batches: list[dict[str, Any]],
    cutoff: datetime,
    *,
    target_keys: set[str] | None = None,
) -> None:
    import app.engines.explosion_detector as ed
    from app.engines.explosion_detector import _open_key, _record_local_base, _roll_session
    from app.models.schemas import Side

    _roll_session(cutoff)
    ed._session_low.clear()
    ed._session_peak.clear()
    ed._local_base_hist.clear()

    for batch in batches:
        ts = _parse_ts(batch.get("ts"))
        if ts is None or ts > cutoff:
            break
        for contract in batch.get("contracts") or []:
            symbol = str(contract.get("symbol") or "").upper()
            side_s = str(contract.get("side") or "").upper()
            try:
                side = Side(side_s)
            except Exception:
                continue
            strike = float(contract.get("strike") or 0)
            premium = float(contract.get("premium") or 0)
            if not symbol or strike <= 0 or premium <= 0:
                continue
            key = _open_key(symbol, strike, side)
            if target_keys and key not in target_keys:
                continue
            sess_low = float(contract.get("sessionLow") or 0)
            sess_peak = float(contract.get("sessionPeak") or 0)
            if sess_low > 0:
                cur = ed._session_low.get(key)
                if cur is None or sess_low < cur:
                    ed._session_low[key] = sess_low
            if sess_peak > 0:
                cur_p = ed._session_peak.get(key)
                if cur_p is None or sess_peak > cur_p:
                    ed._session_peak[key] = sess_peak
            if premium > 0:
                ed._record_local_base(key, ts, premium)
            if premium > 0:
                ed._session_low[key] = min(ed._session_low.get(key, premium), premium)
                ed._session_peak[key] = max(ed._session_peak.get(key, premium), premium)


def _load_tape(path: Path, max_bytes: int = 0) -> list[dict[str, Any]]:
    if max_bytes > 0:
        from app.services.radar_learning import _read_jsonl_tail

        return _read_jsonl_tail(path, max_bytes=max_bytes)
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


def _evaluate_at(
    *,
    symbol: str,
    strike: float,
    side: str,
    premium: float,
    velocity_3s: float,
    stale_ict: float,
    settings: Any,
) -> dict[str, Any]:
    from app.engines.explosion_detector import get_session_low_premium, get_session_peak_premium
    from app.engines.ict_breakout_monitor import _detect_recent_window_base
    from app.engines.new_session_base import new_session_base_identify
    from app.models.schemas import Side as SideEnum

    side_e = SideEnum.CALL if side.upper() == "CALL" else SideEnum.PUT
    ok, kind, meta = new_session_base_identify(
        symbol,
        strike,
        side_e,
        premium,
        velocity_3s=velocity_3s,
        stale_ict_base=stale_ict,
        settings=settings,
    )
    found, recent_base, base_rel = _detect_recent_window_base(
        symbol=symbol,
        strike=strike,
        side=side_e,
        premium=premium,
        settings=settings,
    )
    sl = get_session_low_premium(symbol, strike, side_e)
    sp = get_session_peak_premium(symbol, strike, side_e)
    fall_peak = (sp - premium) / sp * 100 if sp > premium > 0 else 0.0
    off_low = (premium - sl) / sl * 100 if sl > 0 else 0.0
    return {
        "newSessionBase": ok,
        "newBaseKind": kind,
        "identifyMeta": meta,
        "recentWindowBaseFound": found,
        "recentWindowBase": recent_base,
        "recentWindowBaseRelPct": round(base_rel, 2),
        "sessionLowPremium": round(sl, 2) if sl else None,
        "sessionPeakPremium": round(sp, 2) if sp else None,
        "fallFromPeakPct": round(fall_peak, 2),
        "offSessionLowPct": round(off_low, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument("--trades", type=Path, help="auto-trader history JSON (trades array)")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=0,
        help="Tail-cap tape parse (0 = full file)",
    )
    parser.add_argument(
        "--trough-enabled",
        action="store_true",
        help="simulate trough stamp ON (prod default after #1013 is OFF)",
    )
    args = parser.parse_args()

    from tests.mock_defaults import settings_mock

    settings = settings_mock()
    if args.trough_enabled:
        settings.new_session_base_session_trough_stamp_enabled = True

    if args.trades:
        raw = json.loads(args.trades.read_text())
        if isinstance(raw, list):
            trades = raw
        elif isinstance(raw, dict):
            trades = raw.get("trades") or raw.get("closedTrades") or []
        else:
            trades = []
    else:
        trades = []

    targets: list[dict[str, Any]] = []
    from app.engines.explosion_detector import _open_key
    from app.models.schemas import Side

    keys: set[str] = set()
    for t in trades:
        if str(t.get("status", "CLOSED")).upper() != "CLOSED":
            continue
        sym = str(t.get("symbol") or "").upper()
        side = str(t.get("side") or "CALL").upper()
        strike = float(t.get("strike") or 0)
        opened = _parse_ts(t.get("openedAt"))
        if not sym or strike <= 0 or not opened:
            continue
        side_e = Side.CALL if side == "CALL" else Side.PUT
        keys.add(_open_key(sym, strike, side_e))
        ctx = t.get("entryContext") or {}
        targets.append(
            {
                "openedAt": opened,
                "symbol": sym,
                "strike": strike,
                "side": side,
                "entryPremium": float(t.get("entryPremium") or 0),
                "pnlInr": float(t.get("pnlInr") or 0),
                "liveStamp": bool(ctx.get("newSessionBase")),
                "liveKind": ctx.get("newBaseKind"),
                "velocity3s": float(ctx.get("velocity3s") or 0),
                "staleIct": float(
                    ctx.get("ictBasePremium")
                    or ctx.get("localBaseBasePremium")
                    or 0
                ),
            }
        )

    print(f"Loading tape {args.tape} ({args.tape.stat().st_size // 1_000_000} MB)...", file=sys.stderr)
    batches = _load_tape(args.tape, max_bytes=args.max_bytes or 0)
    print(f"Tape batches: {len(batches)}", file=sys.stderr)

    rows: list[dict[str, Any]] = []
    for tgt in sorted(targets, key=lambda r: r["openedAt"]):
        sub = [b for b in batches if (_parse_ts(b.get("ts")) or datetime.min.replace(tzinfo=IST)) <= tgt["openedAt"]]
        _hydrate_tape_through(sub, tgt["openedAt"], target_keys=keys)
        ev = _evaluate_at(
            symbol=tgt["symbol"],
            strike=tgt["strike"],
            side=tgt["side"],
            premium=tgt["entryPremium"],
            velocity_3s=tgt["velocity3s"],
            stale_ict=tgt["staleIct"],
            settings=settings,
        )
        rows.append({**tgt, **ev, "troughStampEnabled": bool(args.trough_enabled)})

    print(json.dumps({"date": "from-tape", "entries": rows}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())