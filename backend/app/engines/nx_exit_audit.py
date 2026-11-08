"""Post-session audit: entry LTP N× captures vs premium tape after exit.

Flags trades that exited before reaching N× while open but whose contract later
crossed higher multiples on the session premium tape.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.radar_learning import _number, _parse_ts, read_premium_tape
from app.services.trade_store import get_day_detail

IST = ZoneInfo("Asia/Kolkata")


def _trade_ctx(trade: dict[str, Any]) -> dict[str, Any]:
    ctx = trade.get("entryContext")
    if isinstance(ctx, dict):
        return ctx
    ctx = trade.get("context")
    return dict(ctx) if isinstance(ctx, dict) else {}


def _highest_n_multiple(entry: float, ltp: float, *, max_n: int) -> int:
    """Largest integer N≥1 such that ltp reached N× entry (N=1 is baseline at entry)."""
    if entry <= 0 or ltp <= 0 or not math.isfinite(entry) or not math.isfinite(ltp):
        return 0
    best = 1 if ltp + 1e-6 >= entry else 0
    cap = max(2, min(int(max_n), 50))
    for n in range(2, cap + 1):
        if ltp + 1e-6 >= n * entry:
            best = n
        else:
            break
    return best


def _captures_max_n(ctx: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    raw = ctx.get("entryLtpMultipleCaptures")
    rows: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                rows.append(dict(item))
    max_n = 0
    for row in rows:
        try:
            max_n = max(max_n, int(row.get("n", 0)))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: int(r.get("n", 0)))
    return max_n, rows


def _trade_contract_key(trade: dict[str, Any]) -> str:
    symbol = str(trade.get("symbol") or "").upper()
    side = str(trade.get("side") or "").upper()
    strike = _number(trade.get("strike"))
    if not symbol or side not in {"CALL", "PUT"} or strike <= 0:
        return ""
    return f"{symbol}:{side}:{strike:g}"


def _match_contract(contract: dict[str, Any], trade: dict[str, Any]) -> bool:
    symbol = str(trade.get("symbol") or "").upper()
    side = str(trade.get("side") or "").upper()
    strike = _number(trade.get("strike"))
    if str(contract.get("symbol") or "").upper() != symbol:
        return False
    if str(contract.get("side") or "").upper() != side:
        return False
    return abs(_number(contract.get("strike")) - strike) <= 0.5


def _post_exit_tape_peak(
    date: str,
    trade: dict[str, Any],
    closed_at: datetime,
    *,
    max_n: int,
) -> tuple[float, int]:
    """Max sanitized LTP on premium tape strictly after ``closed_at`` for this contract."""
    peak = 0.0
    for batch in read_premium_tape(date):
        ts = _parse_ts(batch.get("ts"))
        if ts is None or ts <= closed_at:
            continue
        for contract in batch.get("contracts") or []:
            if not isinstance(contract, dict):
                continue
            if not _match_contract(contract, trade):
                continue
            prem = _number(contract.get("premium"))
            if prem > peak:
                peak = prem
    entry = _number(trade.get("entryPremium"))
    post_n = _highest_n_multiple(entry, peak, max_n=max_n) if peak > 0 else 0
    return peak, post_n


def _parse_closed_at(trade: dict[str, Any]) -> datetime | None:
    return _parse_ts(trade.get("closedAt"))


def audit_trade_nx_exit(trade: dict[str, Any], date: str, *, max_n: int) -> dict[str, Any]:
    entry = _number(trade.get("entryPremium"))
    ctx = _trade_ctx(trade)
    captured_max_n, captures = _captures_max_n(ctx)
    while_open_ltp = max(
        _number(trade.get("maxLtp")),
        _number(ctx.get("maxLtp")),
    )
    while_open_n = _highest_n_multiple(entry, while_open_ltp, max_n=max_n)
    closed_at = _parse_closed_at(trade)
    post_peak = 0.0
    post_n = 0
    if closed_at is not None:
        post_peak, post_n = _post_exit_tape_peak(date, trade, closed_at, max_n=max_n)

    effective_while_open_n = max(captured_max_n, while_open_n)
    missed_n = max(0, post_n - effective_while_open_n)
    early_exit_after_nx = bool(missed_n >= 1 and post_n >= 2)

    return {
        "tradeId": trade.get("id"),
        "symbol": trade.get("symbol"),
        "side": trade.get("side"),
        "strike": trade.get("strike"),
        "executionMode": trade.get("executionMode") or ctx.get("executionMode"),
        "entryPremium": round(entry, 2) if entry else None,
        "exitReason": trade.get("exitReason"),
        "pnlInr": trade.get("pnlInr"),
        "openedAt": trade.get("openedAt"),
        "closedAt": trade.get("closedAt"),
        "nxCaptureEnabled": bool(captures) or effective_while_open_n >= 2,
        "entryLtpMultipleCaptures": captures,
        "whileOpenMaxN": effective_while_open_n,
        "whileOpenMaxLtp": round(while_open_ltp, 2) if while_open_ltp else None,
        "postExitTapeMaxLtp": round(post_peak, 2) if post_peak else None,
        "postExitTapeMaxN": post_n,
        "missedNAfterExit": missed_n,
        "earlyExitBeforeLaterNx": early_exit_after_nx,
    }


def generate_nx_exit_audit(date: str) -> dict[str, Any]:
    """Audit all closed trades on ``date`` for N× capture vs post-exit tape."""
    settings = get_settings()
    max_n = int(getattr(settings, "trade_entry_multiple_capture_max_n", 20) or 20)
    capture_on = bool(getattr(settings, "trade_entry_multiple_capture_enabled", True))

    day = get_day_detail(date)
    closed = [t for t in day.get("trades", []) if t.get("status") == "CLOSED"]
    rows = [audit_trade_nx_exit(t, date, max_n=max_n) for t in closed]
    early = [r for r in rows if r.get("earlyExitBeforeLaterNx")]

    return {
        "date": date,
        "status": "ok",
        "tradeEntryMultipleCaptureEnabled": capture_on,
        "maxN": max_n,
        "closedTradeCount": len(closed),
        "earlyExitMissCount": len(early),
        "capturesPresentCount": sum(1 for r in rows if r.get("entryLtpMultipleCaptures")),
        "trades": rows,
        "earlyExits": early,
        "note": (
            "earlyExitBeforeLaterNx when post-exit tape reaches a higher N× than "
            "recorded while the trade was open (captures or maxLtp)."
        ),
    }
