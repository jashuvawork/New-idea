"""Afternoon index SLIDE leg — lower elite floor + rank for aligned PUT (CE/PE symmetric for CALL on RALLY)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _side_u(side: Any) -> str:
    raw = str(getattr(side, "value", side) or "").upper()
    if raw in {"CALL", "CE", "C"}:
        return "CALL"
    if raw in {"PUT", "PE", "P"}:
        return "PUT"
    return raw


def _symbols_allowed(settings: Any) -> frozenset[str]:
    raw = str(
        getattr(settings, "index_slide_capture_lane_symbols_csv", "SENSEX") or "SENSEX"
    )
    return frozenset(s.strip().upper() for s in raw.split(",") if s.strip())


def in_index_slide_capture_window_at(when: datetime, *, settings: Any = None) -> bool:
    settings = settings or get_settings()
    if not isinstance(when, datetime):
        return False
    local = when.astimezone(IST)
    current = local.hour * 60 + local.minute
    start = int(getattr(settings, "index_slide_capture_lane_start_hour", 10)) * 60 + int(
        getattr(settings, "index_slide_capture_lane_start_minute", 30)
    )
    end = 15 * 60 + 45
    return start <= current < end


def _index_leg_frac(settings: Any, side: str) -> float:
    if _side_u(side) == "PUT":
        return float(
            getattr(settings, "index_slide_capture_lane_min_slide_frac", 0.35) or 0.35
        )
    return float(
        getattr(settings, "index_slide_capture_lane_min_slide_frac", 0.35) or 0.35
    )


def index_slide_capture_lane_status(
    symbol: str,
    side: str,
    snap: SymbolSnapshot,
    *,
    when: Optional[datetime] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    True when index slide (PUT) or rally (CALL mirror) is armed for capture lane waivers.
  Not limited to CHOP day_modes — uses session extremes only.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"indexSlideCaptureLane": True}
    if not bool(getattr(settings, "index_slide_capture_lane_enabled", True)):
        return False, "lane_disabled", meta
    sym = str(symbol or "").upper()
    if sym not in _symbols_allowed(settings):
        return False, "symbol_not_in_lane", meta
    when = when or datetime.now(IST)
    if when.tzinfo is None:
        when = when.replace(tzinfo=IST)
    if not in_index_slide_capture_window_at(when, settings=settings):
        return False, "outside_lane_window", meta

    from app.engines.index_rally_side_flip import _min_move_pts, index_rally_metrics
    from app.engines.index_session_dominant_trend import (
        index_session_dominant_trend,
        side_aligns_with_dominant_trend,
    )

    side_u = _side_u(side)
    metrics = index_rally_metrics(sym, snap, settings=settings)
    min_pts = _min_move_pts(sym, settings)
    frac = _index_leg_frac(settings, side_u)
    need = min_pts * frac
    rally_pts = float(metrics.get("rallyPoints") or 0)
    slide_pts = float(metrics.get("slidePoints") or 0)
    mom5 = float(metrics.get("momentum5Pct") or 0)
    meta["indexTrendMetrics"] = metrics
    meta["laneMinMovePoints"] = round(need, 1)

    dominant, trend_meta = index_session_dominant_trend(
        sym, snap, None, settings=settings, track_flip=False,
    )
    meta["dominantTrend"] = dominant
    meta["indexTrendMeta"] = trend_meta

    if not side_aligns_with_dominant_trend(side_u, dominant) and dominant != "NEUTRAL":
        return False, "side_opposes_dominant_trend", meta

    if side_u == "PUT":
        slide_ok = slide_pts >= need - 1e-6 and mom5 <= 0.0
        meta["slidePoints"] = slide_pts
        if not slide_ok:
            return False, "slide_leg_not_confirmed", meta
        meta["laneArmed"] = True
        return True, "index_slide_capture_lane_put", meta

    if side_u == "CALL":
        rally_ok = rally_pts >= need - 1e-6 and mom5 >= 0.0
        meta["rallyPoints"] = rally_pts
        if not rally_ok:
            return False, "rally_leg_not_confirmed", meta
        meta["laneArmed"] = True
        return True, "index_slide_capture_lane_call", meta

    return False, "unknown_side", meta


def index_slide_capture_elite_floor(
    evidence: Mapping[str, Any],
    *,
    snap: Optional[SymbolSnapshot] = None,
    when: Optional[datetime] = None,
    settings: Any = None,
) -> Optional[float]:
    """Lower elite_trade_min_score when afternoon slide/rally lane is armed (default 78)."""
    settings = settings or get_settings()
    sym = str(evidence.get("symbol") or "").upper()
    side = _side_u(evidence.get("side") or "")
    if not sym or not side:
        return None
    if snap is None:
        return None
    armed, _, _ = index_slide_capture_lane_status(
        sym, side, snap, when=when, settings=settings,
    )
    if not armed:
        return None
    return float(
        getattr(settings, "index_slide_capture_lane_min_elite_score", 78.0) or 78.0
    )


def index_slide_capture_rank_adjustment(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
    *,
    when: Optional[datetime] = None,
    settings: Any = None,
) -> float:
    settings = settings or get_settings()
    sym = str(getattr(candidate, "symbol", "") or "").upper()
    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None:
        return 0.0
    side = _side_u(getattr(candidate, "side", ""))
    armed, _, meta = index_slide_capture_lane_status(
        sym, side, snap, when=when, settings=settings,
    )
    bonus = float(
        getattr(settings, "index_slide_capture_lane_rank_bonus", 22.0) or 22.0
    )
    penalty = float(
        getattr(settings, "index_slide_capture_lane_ce_rank_penalty", 12.0) or 12.0
    )
    dominant = str(meta.get("dominantTrend") or "NEUTRAL")
    if armed and side == "PUT":
        return bonus
    if dominant == "SLIDE" and side == "CALL":
        return -penalty
    return 0.0


def index_slide_capture_lane_summary(settings: Any = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "enabled": bool(getattr(settings, "index_slide_capture_lane_enabled", True)),
        "windowIst": (
            f"{int(getattr(settings, 'index_slide_capture_lane_start_hour', 10)):02d}:"
            f"{int(getattr(settings, 'index_slide_capture_lane_start_minute', 30)):02d}"
            "–15:45"
        ),
        "minEliteScore": float(
            getattr(settings, "index_slide_capture_lane_min_elite_score", 78.0) or 78.0
        ),
        "symbols": str(
            getattr(settings, "index_slide_capture_lane_symbols_csv", "SENSEX") or "SENSEX"
        ),
        "minSlideFrac": float(
            getattr(settings, "index_slide_capture_lane_min_slide_frac", 0.35) or 0.35
        ),
    }
