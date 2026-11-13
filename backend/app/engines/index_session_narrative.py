"""Single HUD-friendly index leg story: RALLY / SLIDE / NEUTRAL + flip per symbol."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.models.schemas import SymbolSnapshot


def index_session_narrative_summary(
    snapshots: dict[str, SymbolSnapshot],
    state: Any = None,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_session_narrative_enabled", True)):
        return {"enabled": False, "symbols": {}}

    from app.engines.index_session_dominant_trend import index_session_dominant_trend

    raw = str(
        getattr(
            settings,
            "index_trend_opposite_side_symbols_csv",
            "SENSEX,NIFTY",
        )
        or "SENSEX,NIFTY"
    )
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    out: dict[str, Any] = {"enabled": True, "symbols": {}}
    for sym in symbols:
        snap = snapshots.get(sym)
        if snap is None:
            continue
        trend, meta = index_session_dominant_trend(
            sym, snap, state, settings=settings, track_flip=True,
        )
        metrics = meta.get("indexTrendMetrics") or {}
        bullish_option_side = (
            "CALL" if trend == "RALLY" else "PUT" if trend == "SLIDE" else None
        )
        out["symbols"][sym] = {
            "dominantLeg": trend,
            "bullishOptionSide": bullish_option_side,
            "rallyPoints": metrics.get("rallyPoints"),
            "slidePoints": metrics.get("slidePoints"),
            "dominantTrendFlipped": meta.get("dominantTrendFlipped"),
            "dominantTrendPrevious": meta.get("dominantTrendPrevious"),
            "callRallyUnlockArmed": (meta.get("callRallyUnlock") or {}).get("armed"),
            "putSlideUnlockArmed": (meta.get("putSlideUnlock") or {}).get("armed"),
            "indexTrendFlip": meta.get("indexTrendFlip"),
        }
    return out
