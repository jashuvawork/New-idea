"""Midday PUT slide timing — enter on breakdown, not on post-top bounce (CE/PE book infra).

Replaces PAD676 flip *blocks* with a positive readiness bar: index off session high with
bearish micro-momentum (no bullish 5m bounce bar). Does not change pad ranking.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

_DEFAULT_DAY_MODES = frozenset({
    "CHOP + RALLY",
    "CHOP DAY",
    "CHOP (PRE-10)",
    "MOMENTUM RALLY",
})


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _day_modes(settings: Any) -> frozenset[str]:
    raw = str(getattr(settings, "pe_slide_breakdown_day_modes_csv", "") or "").strip()
    if raw:
        return frozenset(s.strip().upper() for s in raw.split(",") if s.strip())
    return _DEFAULT_DAY_MODES


def pe_slide_breakdown_active(*, day_mode: str = "", settings: Any = None) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "pe_slide_breakdown_timing_enabled", True)):
        return False
    dm = str(day_mode or "").strip().upper()
    return bool(dm and dm in _day_modes(settings))


def pe_slide_breakdown_ready(
    symbol: str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    True when index has rolled off session high with bearish 5m momentum (slide leg),
    not a green bounce candle inside the pullback.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"peSlideBreakdown": True}
    from app.engines.index_rally_side_flip import index_rally_metrics

    metrics = index_rally_metrics(symbol, snap, settings=settings)
    meta["indexMetrics"] = metrics
    slide_pts = float(metrics.get("slidePoints") or 0)
    min_pts = float(metrics.get("minMovePoints") or 45)
    fraction = float(getattr(settings, "pe_slide_breakdown_min_slide_fraction", 0.45) or 0.45)
    soft_min = min_pts * max(0.15, min(1.0, fraction))
    meta["softMinSlidePts"] = round(soft_min, 1)
    if slide_pts < soft_min - 1e-6:
        return False, f"pe_slide_insufficient_slide_{slide_pts:.0f}lt{soft_min:.0f}", meta

    hi = float(metrics.get("sessionHigh") or 0)
    spot = float(metrics.get("spot") or 0)
    if hi > 0 and spot > 0:
        pullback_pct = (hi - spot) / hi * 100.0
        meta["pullbackPctFromHigh"] = round(pullback_pct, 3)
        min_pb = float(
            getattr(settings, "pe_slide_breakdown_min_pullback_pct_from_high", 0.22) or 0.22
        )
        if pullback_pct < min_pb:
            return False, "pe_slide_pullback_from_high_too_shallow", meta

    chart = getattr(snap, "spotChart", None)
    if chart is None:
        return False, "pe_slide_no_chart", meta

    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
    macd_hist = float(getattr(chart, "macdHistogram", 0) or 0)
    direction = str(getattr(chart, "direction", "") or "NEUTRAL").upper()
    candle_bias = str(getattr(chart, "candleBias", "") or "NEUTRAL").upper()
    meta["indexMom5Pct"] = round(mom5, 3)
    meta["indexMacdHist"] = round(macd_hist, 4)
    meta["index5mDirection"] = direction
    meta["indexCandleBias"] = candle_bias

    bounce_max = float(getattr(settings, "pe_slide_breakdown_bounce_max_mom5_pct", 0.05) or 0.05)
    if candle_bias == "BULLISH" and mom5 > bounce_max:
        return False, "pe_slide_bounce_trap", meta

    min_bear_mom = float(
        getattr(settings, "pe_slide_breakdown_min_bearish_mom5_pct", 0.03) or 0.03
    )
    bearish_ok = (
        direction == "BEARISH"
        or mom5 <= -min_bear_mom
        or macd_hist < 0
    )
    if not bearish_ok:
        return False, "pe_slide_momentum_not_bearish", meta

    return True, "pe_slide_breakdown_ready", meta


def pe_slide_breakdown_put_entry_blocked(
    candidate: Any,
    *,
    day_mode: str = "",
    settings: Any = None,
    when: Optional[datetime] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Pretrade: block PUT until slide breakdown timing is ready (midday chop/rally days)."""
    settings = settings or get_settings()
    if _side_val(getattr(candidate, "side", "")) != "PUT":
        return False, "", {}
    if not pe_slide_breakdown_active(day_mode=day_mode, settings=settings):
        return False, "", {}

    when = when or datetime.now(IST)
    from app.engines.open_index_lane import in_open_caution_window_at

    if in_open_caution_window_at(when.astimezone(IST)):
        return False, "", {}

    sym = str(getattr(candidate, "symbol", "") or "")
    snap = getattr(candidate, "snap", None)
    if snap is None:
        return False, "", {}

    ready, reason, meta = pe_slide_breakdown_ready(sym, snap, settings=settings)
    if ready:
        return False, "", meta
    return True, reason, meta
