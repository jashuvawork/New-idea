"""Midday CALL rally lift timing — enter on lift off low/base, not cold chase (CE/PE book infra).

Symmetric to pe_slide_breakdown_timing: positive readiness on the bullish leg; at-base
capture allowed inside a tight local-base band; blocks late chase when timing is COLD.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional
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
    raw = str(getattr(settings, "ce_rally_lift_day_modes_csv", "") or "").strip()
    if raw:
        return frozenset(s.strip().upper() for s in raw.split(",") if s.strip())
    return _DEFAULT_DAY_MODES


def ce_rally_lift_active(*, day_mode: str = "", settings: Any = None) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "ce_rally_lift_timing_enabled", True)):
        return False
    dm = str(day_mode or "").strip().upper()
    return bool(dm and dm in _day_modes(settings))


def _local_base_pct(candidate: Any, timing_meta: Optional[Mapping[str, Any]] = None) -> float:
    if timing_meta:
        try:
            val = float(timing_meta.get("localBasePct") or 0)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        for key in ("localBaseMovePct", "localBasePct", "ictBaseRelativeMovePct"):
            try:
                val = float(alert.get(key) or 0)
            except (TypeError, ValueError):
                val = 0.0
            if val > 0:
                return val
    return 0.0


def ce_at_armed_base_capture_ok(
    candidate: Any,
    *,
    settings: Any = None,
    timing_meta: Optional[Mapping[str, Any]] = None,
) -> tuple[bool, dict[str, Any]]:
    """True when strike is still on the armed local base (book: capture at base, not chase)."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {"ceAtBaseCapture": True}
    local_pct = _local_base_pct(candidate, timing_meta)
    meta["localBasePct"] = round(local_pct, 2)
    max_pct = float(getattr(settings, "ce_rally_at_base_max_local_base_pct", 8.0) or 8.0)
    meta["atBaseMaxPct"] = max_pct
    if local_pct <= 0 or local_pct > max_pct:
        return False, meta
    alert = getattr(candidate, "alert", None)
    alert = alert if isinstance(alert, dict) else {}
    armed = bool(
        alert.get("ictBaseArmed")
        or alert.get("armedBaseLaunch")
        or alert.get("firstLift")
        or alert.get("ictArmedBaseLaunch")
    )
    meta["ictBaseArmed"] = bool(alert.get("ictBaseArmed"))
    if not armed:
        return False, meta
    return True, meta


def ce_rally_lift_ready(
    symbol: str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Index rally off session low with bullish 5m — not a bearish dump bar (CE mirror of PE slide)."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {"ceRallyLift": True}
    from app.engines.index_rally_side_flip import index_rally_metrics

    metrics = index_rally_metrics(symbol, snap, settings=settings)
    meta["indexMetrics"] = metrics
    rally_pts = float(metrics.get("rallyPoints") or 0)
    min_pts = float(metrics.get("minMovePoints") or 45)
    fraction = float(getattr(settings, "ce_rally_lift_min_rally_fraction", 0.45) or 0.45)
    soft_min = min_pts * max(0.15, min(1.0, fraction))
    meta["softMinRallyPts"] = round(soft_min, 1)
    if rally_pts < soft_min - 1e-6:
        return False, f"ce_rally_insufficient_rally_{rally_pts:.0f}lt{soft_min:.0f}", meta

    lo = float(metrics.get("sessionLow") or 0)
    spot = float(metrics.get("spot") or 0)
    if lo > 0 and spot > 0:
        lift_pct = (spot - lo) / lo * 100.0
        meta["liftPctFromLow"] = round(lift_pct, 3)
        min_lift = float(
            getattr(settings, "ce_rally_lift_min_lift_pct_from_low", 0.22) or 0.22
        )
        if lift_pct < min_lift:
            return False, "ce_rally_lift_from_low_too_shallow", meta

    chart = getattr(snap, "spotChart", None)
    if chart is None:
        return False, "ce_rally_no_chart", meta

    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
    macd_hist = float(getattr(chart, "macdHistogram", 0) or 0)
    direction = str(getattr(chart, "direction", "") or "NEUTRAL").upper()
    candle_bias = str(getattr(chart, "candleBias", "") or "NEUTRAL").upper()
    meta["indexMom5Pct"] = round(mom5, 3)
    meta["indexMacdHist"] = round(macd_hist, 4)
    meta["index5mDirection"] = direction
    meta["indexCandleBias"] = candle_bias

    dump_max = float(getattr(settings, "ce_rally_lift_dump_trap_max_mom5_pct", -0.05) or -0.05)
    if candle_bias == "BEARISH" and mom5 < dump_max:
        return False, "ce_rally_dump_trap", meta

    min_bull_mom = float(
        getattr(settings, "ce_rally_lift_min_bullish_mom5_pct", 0.03) or 0.03
    )
    bullish_ok = (
        direction == "BULLISH"
        or mom5 >= min_bull_mom
        or macd_hist > 0
    )
    if not bullish_ok:
        return False, "ce_rally_momentum_not_bullish", meta

    return True, "ce_rally_lift_ready", meta


def ce_rally_lift_call_entry_blocked(
    candidate: Any,
    *,
    day_mode: str = "",
    settings: Any = None,
    when: Optional[datetime] = None,
    timing_meta: Optional[Mapping[str, Any]] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Pretrade: allow CALL at armed base OR rally-ready; else block midday chase."""
    settings = settings or get_settings()
    if _side_val(getattr(candidate, "side", "")) != "CALL":
        return False, "", {}
    if not ce_rally_lift_active(day_mode=day_mode, settings=settings):
        return False, "", {}

    when = when or datetime.now(IST)
    from app.engines.open_index_lane import in_open_caution_window_at

    if in_open_caution_window_at(when.astimezone(IST)):
        return False, "", {}

    sym = str(getattr(candidate, "symbol", "") or "")
    snap = getattr(candidate, "snap", None)
    if snap is None:
        return False, "", {}

    at_base, base_meta = ce_at_armed_base_capture_ok(
        candidate, settings=settings, timing_meta=timing_meta,
    )
    if at_base:
        return False, "", base_meta

    chase_max = float(
        getattr(settings, "ce_rally_chase_max_local_base_pct", 10.0) or 10.0
    )
    local_pct = _local_base_pct(candidate, timing_meta)
    if local_pct > chase_max:
        meta = {**base_meta, "localBasePct": local_pct, "chaseMaxPct": chase_max}
        return True, "ce_chase_past_local_base", meta

    ready, reason, meta = ce_rally_lift_ready(sym, snap, settings=settings)
    if ready:
        return False, "", meta
    return True, reason, meta


def ce_cold_timing_chase_blocked(
    candidate: Any,
    timing_meta: Optional[Mapping[str, Any]] = None,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Block armed-base / first-lift bypass when timing is COLD and premium is already
    extended off local base (Nov 2 CALL 23050 @ 14% off base).
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "ce_cold_timing_chase_block_enabled", True)):
        return False, "", {}
    if _side_val(getattr(candidate, "side", "")) != "CALL":
        return False, "", {}
    timing_meta = timing_meta if isinstance(timing_meta, Mapping) else {}
    action = str(timing_meta.get("action") or "").lower()
    assessment = str(timing_meta.get("assessment") or "").upper()
    if action not in ("block", "reject") and assessment != "COLD":
        return False, "", {}

    local_pct = _local_base_pct(candidate, timing_meta)
    max_cold = float(
        getattr(settings, "ce_cold_timing_max_local_base_pct", 10.0) or 10.0
    )
    meta = {"localBasePct": local_pct, "coldTimingMaxBasePct": max_cold}
    if local_pct <= max_cold:
        return False, "", meta
    return True, "ce_cold_timing_chase_past_base", meta
