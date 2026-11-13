"""Single HUD-friendly index leg story: RALLY / SLIDE / NEUTRAL + flip per symbol."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _side_u(raw: Any) -> str:
    val = str(getattr(raw, "value", raw) or "").upper()
    if val in {"CALL", "CE", "C"}:
        return "CALL"
    if val in {"PUT", "PE", "P"}:
        return "PUT"
    return val


def _aligned_explosion_picks(
    symbol: str,
    snap: SymbolSnapshot,
    aligned_side: str | None,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    if not aligned_side:
        return []
    want = _side_u(aligned_side)
    alerts = list(getattr(snap, "explosionAlerts", None) or [])
    rows: list[dict[str, Any]] = []
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        side = _side_u(alert.get("side"))
        if side != want:
            continue
        try:
            strike = float(alert.get("strike") or 0)
        except (TypeError, ValueError):
            strike = 0.0
        try:
            score = float(
                alert.get("explosionScore")
                or alert.get("score")
                or alert.get("rankScore")
                or 0
            )
        except (TypeError, ValueError):
            score = 0.0
        try:
            local_base = float(
                alert.get("localBaseMovePct")
                or alert.get("ictBaseRelativeMovePct")
                or alert.get("offLowMovePct")
                or 0
            )
        except (TypeError, ValueError):
            local_base = 0.0
        tier = str(alert.get("tier") or "").upper()
        moment = str(alert.get("momentType") or alert.get("setup") or "")
        rows.append(
            {
                "symbol": symbol,
                "side": side,
                "strike": strike,
                "tier": tier,
                "momentType": moment,
                "explosionScore": round(score, 1),
                "localBasePct": round(local_base, 1),
                "premium": alert.get("premium") or alert.get("ltp"),
                "nearBase676": local_base > 0 and local_base <= 28.0,
            }
        )
    rows.sort(
        key=lambda r: (
            1 if r.get("nearBase676") else 0,
            float(r.get("explosionScore") or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


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


def index_session_monitoring_summary(
    snapshots: dict[str, SymbolSnapshot],
    state: Any = None,
    *,
    settings: Any = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    """
    Index leg + flip + slide-capture lane + top #676-aligned explosion picks per index.
    Shipped on auto-trader chopGuards for Analysis HUD.
    """
    settings = settings or get_settings()
    when = when or datetime.now(IST)
    if when.tzinfo is None:
        when = when.replace(tzinfo=IST)
    narrative = index_session_narrative_summary(snapshots, state, settings=settings)
    from app.engines.index_slide_capture_lane import index_slide_capture_lane_status
    from app.engines.open_setup_guards import open_setup_guard_summary
    from app.engines.index_slide_capture_lane import index_slide_capture_lane_summary
    from app.engines.session_timing import in_open_caution_window

    symbols_out: dict[str, Any] = {}
    for sym, leg in dict(narrative.get("symbols") or {}).items():
        snap = snapshots.get(sym)
        if snap is None:
            continue
        aligned = leg.get("bullishOptionSide")
        slide_lane: dict[str, Any] = {}
        if aligned:
            armed, lane_reason, lane_meta = index_slide_capture_lane_status(
                sym, aligned, snap, when=when, settings=settings,
            )
            slide_lane = {
                "armed": armed,
                "reason": lane_reason,
                "dominantTrend": lane_meta.get("dominantTrend"),
            }
        symbols_out[sym] = {
            **leg,
            "slideCaptureLane": slide_lane,
            "alignedBookPicks": _aligned_explosion_picks(sym, snap, aligned),
            "timingHint": _timing_hint(leg, slide_lane),
        }

    return {
        "enabled": narrative.get("enabled", True),
        "updatedAtIst": when.astimezone(IST).strftime("%H:%M:%S"),
        "openCautionWindow": in_open_caution_window(),
        "openSetupGuards": open_setup_guard_summary(settings),
        "slideCaptureLanePolicy": index_slide_capture_lane_summary(settings),
        "symbols": symbols_out,
    }


def _timing_hint(leg: dict[str, Any], slide_lane: dict[str, Any]) -> str:
    trend = str(leg.get("dominantLeg") or "NEUTRAL").upper()
    side = leg.get("bullishOptionSide")
    if leg.get("dominantTrendFlipped"):
        prev = leg.get("dominantTrendPrevious") or "?"
        return f"Flip {prev} → {trend} — trade {side or 'flat'} at base after confirm."
    if trend == "RALLY" and side == "CALL":
        return "Index rally leg — rank CE near base (#676 pad); avoid open counter-PE."
    if trend == "SLIDE" and side == "PUT":
        if slide_lane.get("armed"):
            return "Slide lane armed — PE elite floor relaxed; prefer SENSEX pad at base."
        return "Index slide leg — rank PE off session high; defer CE chase."
    if trend == "NEUTRAL":
        return "No clear leg — smaller size; #676 + fade decide at base only."
    return "Monitor leg — take aligned side at base when pad + explosion agree."
