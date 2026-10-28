"""Intraday index dominant trend — rally vs slide leg, recomputed every read."""

from __future__ import annotations

from typing import Any, Literal, Mapping

from app.config import get_settings
from app.models.schemas import SymbolSnapshot

DominantTrend = Literal["RALLY", "SLIDE", "NEUTRAL"]

_last_dominant: dict[str, str] = {}


def reset_index_session_dominant_trend_for_tests() -> None:
    _last_dominant.clear()


def index_trend_features_active(settings: Any = None) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_session_dominant_trend_enabled", True)):
        return False
    if not bool(getattr(settings, "index_trend_opposite_side_legacy_profile_only", True)):
        return True
    from app.engines.sep917_legacy_profile import sep917_legacy_profile_active

    return sep917_legacy_profile_active(settings) and bool(
        getattr(settings, "symmetric_best_trade_capture_enabled", True)
    )


def _resolve_trend_arms(
    sym: str,
    snap: SymbolSnapshot,
    state: Any,
    *,
    settings: Any = None,
) -> tuple[bool, bool, dict[str, Any]]:
    from app.engines.index_rally_side_flip import index_rally_metrics
    from app.engines.pe_win_ce_mirror import call_rally_unlock_armed
    from app.engines.put_slide_ce_mirror import put_slide_unlock_armed

    settings = settings or get_settings()
    meta: dict[str, Any] = {}

    call_armed, call_reason, call_meta = call_rally_unlock_armed(
        state, snap, sym, settings=settings,
    )
    put_armed, put_reason, put_meta = put_slide_unlock_armed(
        state, snap, sym, settings=settings,
    )
    meta["callRallyUnlock"] = {"armed": call_armed, "reason": call_reason, **call_meta}
    meta["putSlideUnlock"] = {"armed": put_armed, "reason": put_reason, **put_meta}

    metrics = index_rally_metrics(sym, snap, settings=settings)
    meta["indexTrendMetrics"] = metrics

    if not (call_armed and put_armed):
        return call_armed, put_armed, meta

    rally_pts = float(metrics.get("rallyPoints") or 0)
    slide_pts = float(metrics.get("slidePoints") or 0)
    margin = float(
        getattr(settings, "index_trend_opposite_side_flip_margin_pts", 20.0) or 20.0
    )
    chart = snap.spotChart
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0) if chart else 0.0

    if rally_pts > slide_pts + margin:
        meta["indexTrendFlip"] = "rally_dominant"
        return True, False, meta
    if slide_pts > rally_pts + margin:
        meta["indexTrendFlip"] = "slide_dominant"
        return False, True, meta
    if mom5 > 0.02:
        meta["indexTrendFlip"] = "mom5_rally"
        return True, False, meta
    if mom5 < -0.02:
        meta["indexTrendFlip"] = "mom5_slide"
        return False, True, meta
    meta["indexTrendFlip"] = "both_neutral"
    return False, False, meta


def index_session_dominant_trend(
    symbol: str,
    snap: SymbolSnapshot,
    state: Any = None,
    *,
    settings: Any = None,
    track_flip: bool = True,
) -> tuple[DominantTrend, dict[str, Any]]:
    """
    Which index leg is active now: RALLY (off low), SLIDE (off high), or NEUTRAL.
    Recomputed on every call — no day-long lock.
    """
    settings = settings or get_settings()
    sym = str(symbol or getattr(snap, "symbol", "") or "").upper()
    meta: dict[str, Any] = {"symbol": sym}

    call_armed, put_armed, arm_meta = _resolve_trend_arms(
        sym, snap, state, settings=settings,
    )
    meta.update(arm_meta)

    dominant: DominantTrend = "NEUTRAL"
    if call_armed and not put_armed:
        dominant = "RALLY"
    elif put_armed and not call_armed:
        dominant = "SLIDE"
    elif call_armed and put_armed:
        flip = str(meta.get("indexTrendFlip") or "")
        if flip in ("rally_dominant", "mom5_rally"):
            dominant = "RALLY"
        elif flip in ("slide_dominant", "mom5_slide"):
            dominant = "SLIDE"

    meta["dominantTrend"] = dominant

    if track_flip:
        prev = _last_dominant.get(sym)
        if prev and prev != dominant and dominant != "NEUTRAL":
            meta["dominantTrendFlipped"] = True
            meta["dominantTrendPrevious"] = prev
        else:
            meta["dominantTrendFlipped"] = False
        if dominant != "NEUTRAL":
            _last_dominant[sym] = dominant

    return dominant, meta


def index_session_dominant_trend_summary(
    snapshots: dict[str, SymbolSnapshot],
    state: Any = None,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """Per-symbol dominant trend for deployment HUD."""
    settings = settings or get_settings()
    if not index_trend_features_active(settings):
        return {"enabled": False, "symbols": {}}

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
            sym, snap, state, settings=settings, track_flip=False,
        )
        metrics = meta.get("indexTrendMetrics") or {}
        out["symbols"][sym] = {
            "dominantTrend": trend,
            "rallyPoints": metrics.get("rallyPoints"),
            "slidePoints": metrics.get("slidePoints"),
            "callRallyUnlock": (meta.get("callRallyUnlock") or {}).get("armed"),
            "putSlideUnlock": (meta.get("putSlideUnlock") or {}).get("armed"),
            "indexTrendFlip": meta.get("indexTrendFlip"),
        }
    return out


def side_aligns_with_dominant_trend(side: str, dominant: DominantTrend) -> bool:
    side_u = str(side or "").upper()
    if dominant == "RALLY":
        return side_u == "CALL"
    if dominant == "SLIDE":
        return side_u == "PUT"
    return True


def index_trend_rank_adjustment(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
    state: Any = None,
    *,
    settings: Any = None,
) -> float:
    """Boost aligned leg; penalize opposite when dominant trend is clear."""
    settings = settings or get_settings()
    if not index_trend_features_active(settings):
        return 0.0
    sym = str(getattr(candidate, "symbol", "") or "").upper()
    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None:
        return 0.0
    side = getattr(getattr(candidate, "side", None), "value", getattr(candidate, "side", ""))
    dominant, meta = index_session_dominant_trend(
        sym, snap, state, settings=settings, track_flip=True,
    )
    if dominant == "NEUTRAL":
        return 0.0
    bonus = float(getattr(settings, "index_trend_rank_bonus_aligned", 8.0) or 8.0)
    penalty = float(getattr(settings, "index_trend_rank_penalty_opposite", 6.0) or 6.0)
    flip_bonus = float(getattr(settings, "index_trend_rank_flip_bonus", 5.0) or 5.0)
    if side_aligns_with_dominant_trend(str(side), dominant):
        adj = bonus
        if meta.get("dominantTrendFlipped"):
            adj += flip_bonus
        if bool(getattr(settings, "best_trade_sep917_base_shape_align_enabled", True)):
            from app.engines.best_trade_policy import sep917_near_base_capture_ok

            alert = getattr(candidate, "alert", None)
            alert = alert if isinstance(alert, dict) else {}
            pretrade = getattr(candidate, "pretrade_meta", None) or {}
            ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}
            if not isinstance(ranking, dict):
                ranking = {}
            nested = ranking.get("evidence") if isinstance(ranking.get("evidence"), dict) else {}
            evidence = {**alert, **nested, **ranking}
            ok, _ = sep917_near_base_capture_ok(
                evidence, ranking, alert, settings=settings,
            )
            if ok:
                adj += float(
                    getattr(settings, "index_trend_rank_sep917_base_bonus_aligned", 12.0)
                    or 12.0
                )
        return adj
    return -penalty


def index_trend_premium_fade_aligned(
    side: str,
    snap: SymbolSnapshot,
    state: Any,
    *,
    evidence: Mapping[str, Any] | None = None,
    settings: Any = None,
) -> bool:
    """Shallow fade fill when dominant trend matches side and structure is at base."""
    settings = settings or get_settings()
    if not index_trend_features_active(settings):
        return False
    sym = str(getattr(snap, "symbol", "") or "").upper()
    dominant, _ = index_session_dominant_trend(sym, snap, state, settings=settings, track_flip=False)
    side_u = str(side or "").upper()
    if not side_aligns_with_dominant_trend(side_u, dominant):
        return False
    from app.engines.best_trade_policy import sep917_near_base_capture_ok

    ev = dict(evidence if isinstance(evidence, Mapping) else {})
    ev.setdefault("side", side_u)
    ok, _ = sep917_near_base_capture_ok(ev, {}, ev, settings=settings)
    return ok
