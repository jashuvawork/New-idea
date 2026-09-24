"""Sanitize option LTP for open-trade marks — reject WS/REST spike glitches."""

from __future__ import annotations

import statistics
from typing import Any, Optional

from app.config import Settings, get_settings
from app.models.schemas import PaperTrade, Side, SymbolSnapshot
from app.services.tick_store import recent_option_ltps


def rest_heatmap_premium(
    snap: SymbolSnapshot,
    strike: float,
    side: Side,
) -> Optional[float]:
    """REST heatmap LTP only (no WebSocket overlay)."""
    for row in snap.heatmap:
        if abs(row.strike - strike) < 1:
            if side == Side.CALL:
                return float(row.callLtp) if row.callLtp else None
            return float(row.putLtp) if row.putLtp else None
    return None


def _side_val(side: Side | str) -> Side:
    if isinstance(side, Side):
        return side
    return Side.CALL if str(side).upper() == "CALL" else Side.PUT


def _last_accepted_mark(trade: PaperTrade) -> float:
    ctx = trade.entryContext or {}
    for key in ("lastSanitizedLtp", "lastAcceptedMarkLtp"):
        try:
            val = float(ctx.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    try:
        cur = float(trade.currentPremium or 0)
    except (TypeError, ValueError):
        cur = 0.0
    return cur if cur > 0 else float(trade.entryPremium or 0)


def _hard_ceiling(
    *,
    entry: float,
    rest: Optional[float],
    last_mark: float,
    median: Optional[float],
    settings: Settings,
) -> float:
    mult_entry = float(
        getattr(settings, "open_trade_ltp_max_dev_from_entry_mult", 2.75) or 2.75
    )
    ws_rest = float(getattr(settings, "open_trade_ltp_ws_over_rest_ratio", 1.18) or 1.18)
    step = float(getattr(settings, "open_trade_ltp_max_step_ratio", 1.32) or 1.32)

    ceilings: list[float] = []
    if entry > 0:
        ceilings.append(entry * mult_entry)
    if rest and rest > 0:
        ceilings.append(rest * ws_rest)
    if last_mark > 0:
        ceilings.append(last_mark * step)
    if median and median > 0:
        ceilings.append(median * 1.15)

    if not ceilings:
        return entry * mult_entry if entry > 0 else 0.0
    return min(ceilings)


def _spike_confirmed_by_tape(median: Optional[float], candidate: float, settings: Settings) -> bool:
    """True only when the tape already trades near candidate (not a lone spike)."""
    if not median or median <= 0:
        return False
    lo = float(getattr(settings, "open_trade_ltp_median_confirm_ratio", 0.92) or 0.92)
    hi = float(getattr(settings, "open_trade_ltp_median_confirm_max_ratio", 1.12) or 1.12)
    return median * lo <= candidate <= median * hi


def sanitize_open_trade_ltp(
    trade: PaperTrade,
    candidate: float,
    *,
    snap: SymbolSnapshot | None = None,
    instrument_key: Optional[str] = None,
    settings: Settings | None = None,
) -> Optional[float]:
    """
    Return an accepted LTP for MTM / maxLtp, or None to keep the prior mark.

    Rejects single-tick spikes vs entry, REST heatmap, last mark, and recent median.
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "open_trade_ltp_sanity_enabled", True)):
        return candidate

    try:
        raw = float(candidate)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None

    ctx = dict(trade.entryContext or {})
    ikey = instrument_key or ctx.get("instrumentKey")
    entry = float(trade.entryPremium or 0)
    side = _side_val(trade.side)
    last_mark = _last_accepted_mark(trade)

    window = float(getattr(settings, "open_trade_ltp_recent_window_seconds", 12.0) or 12.0)
    recent = recent_option_ltps(ikey, window_seconds=window) if ikey else []
    median = statistics.median(recent) if len(recent) >= 2 else None

    rest = None
    if snap is not None:
        rest = rest_heatmap_premium(snap, float(trade.strike), side)

    ceiling = _hard_ceiling(
        entry=entry,
        rest=rest,
        last_mark=last_mark,
        median=median,
        settings=settings,
    )
    if ceiling > 0 and raw > ceiling:
        if _spike_confirmed_by_tape(median, raw, settings):
            pass
        else:
            return None

    if last_mark > 0:
        step = float(getattr(settings, "open_trade_ltp_max_step_ratio", 1.32) or 1.32)
        if raw > last_mark * step and not _spike_confirmed_by_tape(median, raw, settings):
            return None

    return round(raw, 2)


def persist_accepted_mark(trade: PaperTrade, accepted: float) -> None:
    ctx = dict(trade.entryContext or {})
    ctx["lastSanitizedLtp"] = round(float(accepted), 2)
    ctx["lastAcceptedMarkLtp"] = ctx["lastSanitizedLtp"]
    trade.entryContext = ctx


def reconcile_max_ltp(trade: PaperTrade, *, settings: Settings | None = None) -> None:
    """Clamp stored maxLtp / bestPnlPoints after spike glitches."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "open_trade_ltp_sanity_enabled", True)):
        return

    entry = float(trade.entryPremium or 0)
    if entry <= 0:
        return

    mult = float(getattr(settings, "open_trade_ltp_max_dev_from_entry_mult", 2.75) or 2.75)
    ceiling = entry * mult
    try:
        stored = float(trade.maxLtp or 0)
    except (TypeError, ValueError):
        stored = 0.0
    if stored <= 0 or stored <= ceiling:
        return

    last = _last_accepted_mark(trade)
    try:
        cur = float(trade.currentPremium or 0)
    except (TypeError, ValueError):
        cur = 0.0
    trusted_high = max(entry, last, cur)
    capped = min(stored, ceiling, trusted_high if trusted_high > entry else ceiling)

    trade.maxLtp = round(capped, 2)
    ctx = dict(trade.entryContext or {})
    ctx["maxLtp"] = trade.maxLtp
    ctx["maxLtpRepaired"] = True
    best = round(max(0.0, trade.maxLtp - entry), 2)
    trade.bestPnlPoints = min(float(trade.bestPnlPoints or 0), best) if trade.bestPnlPoints else best
    trade.entryContext = ctx


def apply_open_trade_mark(
    trade: PaperTrade,
    raw_ltp: float,
    *,
    snap: SymbolSnapshot | None = None,
    instrument_key: Optional[str] = None,
) -> Optional[float]:
    """Sanitize and persist an LTP for MTM; caller updates maxLtp then reconcile_max_ltp."""
    accepted = sanitize_open_trade_ltp(
        trade, raw_ltp, snap=snap, instrument_key=instrument_key,
    )
    if accepted is None:
        reconcile_max_ltp(trade)
        last = _last_accepted_mark(trade)
        return last if last > 0 else None

    persist_accepted_mark(trade, accepted)
    return accepted
