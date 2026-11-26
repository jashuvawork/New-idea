"""Live-only entry integrity: broker fill + index leg alignment (no paper waiver stack)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot


def _side_u(side: Any) -> str:
    return str(getattr(side, "value", side) or "").upper()


def _symbols_allowed(sym: str, settings: Any) -> bool:
    raw = str(
        getattr(
            settings,
            "live_index_leg_hard_align_symbols_csv",
            "NIFTY,SENSEX",
        )
        or "NIFTY,SENSEX"
    )
    allowed = {s.strip().upper() for s in raw.split(",") if s.strip()}
    return sym.upper() in allowed


def live_index_leg_hard_blocks_entry(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Live orders require alignment with index_session_dominant_trend — no chart/mirror
  fingerprint bypasses. Paper may waive; live waits for leg flip or trend breakout.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not bool(getattr(settings, "enable_live_trading", False)):
        return False, "ok", meta
    if not bool(getattr(settings, "auto_trading_enabled", False)):
        return False, "ok", meta
    if not bool(getattr(settings, "live_index_leg_hard_align_enabled", True)):
        return False, "ok", meta

    side = _side_u(getattr(candidate, "side", None))
    if side not in ("CALL", "PUT"):
        return False, "ok", meta

    sym = str(getattr(candidate, "symbol", "") or "").upper()
    if not _symbols_allowed(sym, settings):
        return False, "ok", meta

    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None:
        return False, "ok", meta

    from app.engines.index_session_dominant_trend import (
        index_session_dominant_trend,
        side_aligns_with_dominant_trend,
    )
    from app.engines.index_tick_helpers import index_trend_breakout

    dominant, trend_meta = index_session_dominant_trend(sym, snap, state, settings=settings)
    meta["indexDominantTrend"] = dominant
    meta.update(trend_meta)

    if dominant == "NEUTRAL" or side_aligns_with_dominant_trend(side, dominant):
        return False, "ok", meta

    bo = index_trend_breakout(sym, side, snap)
    if bo.get("breakout"):
        meta["indexTrendBreakout"] = bo
        return False, "ok", meta

    return True, "live_index_leg_misaligned", meta