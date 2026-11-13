"""Early index leg flip risk — contested rally/slide + momentum turning (CE/PE symmetric)."""

from __future__ import annotations

from typing import Any, Literal

from app.config import get_settings
from app.engines.index_session_dominant_trend import (
    DominantTrend,
    index_session_dominant_trend,
    side_aligns_with_dominant_trend,
)
from app.models.schemas import SymbolSnapshot
from app.services.upstox import INDEX_KEYS

FlipRiskLevel = Literal["NONE", "WATCH", "IMMINENT", "CONTESTED"]


def _side_u(raw: Any) -> str:
    val = str(getattr(raw, "value", raw) or "").upper()
    if val in {"CALL", "CE", "C"}:
        return "CALL"
    if val in {"PUT", "PE", "P"}:
        return "PUT"
    return val


def _leg_to_option_side(leg: DominantTrend) -> str | None:
    if leg == "RALLY":
        return "CALL"
    if leg == "SLIDE":
        return "PUT"
    return None


def _index_velocity_3s(symbol: str) -> float:
    key = INDEX_KEYS.get(str(symbol or "").upper())
    if not key:
        return 0.0
    try:
        from app.services.tick_store import get_velocity_pct

        v3 = get_velocity_pct(
            key,
            window_seconds=3.0,
            max_age_seconds=5.0,
            min_span_seconds=0.5,
        )
        return float(v3) if v3 is not None else 0.0
    except Exception:
        return 0.0


def index_imminent_flip_assessment(
    symbol: str,
    snap: SymbolSnapshot,
    state: Any = None,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """
    Predict near-term index leg flip when both rally/slide arms are live or margin is thin.
    ``predictedBullishOptionSide`` is the side that wins if momentum continues — wrong-side
    entries at CONTESTED/IMMINENT risk get selector penalties.
    """
    settings = settings or get_settings()
    sym = str(symbol or getattr(snap, "symbol", "") or "").upper()
    out: dict[str, Any] = {
        "enabled": bool(getattr(settings, "index_imminent_flip_enabled", True)),
        "symbol": sym,
        "riskLevel": "NONE",
        "dominantLeg": "NEUTRAL",
        "predictedLeg": "NEUTRAL",
        "predictedBullishOptionSide": None,
        "contestedLeg": False,
        "rallyPoints": 0.0,
        "slidePoints": 0.0,
        "legMarginPts": 0.0,
        "momentum5Pct": 0.0,
        "indexVelocity3s": 0.0,
        "reasons": [],
    }
    if not out["enabled"]:
        return out

    dominant, meta = index_session_dominant_trend(
        sym, snap, state, settings=settings, track_flip=False,
    )
    metrics = meta.get("indexTrendMetrics") or {}
    rally = float(metrics.get("rallyPoints") or 0)
    slide = float(metrics.get("slidePoints") or 0)
    chart = getattr(snap, "spotChart", None)
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0) if chart else 0.0
    v3 = _index_velocity_3s(sym)
    call_armed = bool((meta.get("callRallyUnlock") or {}).get("armed"))
    put_armed = bool((meta.get("putSlideUnlock") or {}).get("armed"))
    contested = call_armed and put_armed
    margin_pts = abs(rally - slide)
    thin_margin = float(
        getattr(settings, "index_imminent_flip_thin_margin_pts", 25.0) or 25.0
    )
    mom_thr = float(getattr(settings, "index_imminent_flip_mom5_threshold", 0.02) or 0.02)
    vel_thr = float(getattr(settings, "index_imminent_flip_velocity_3s", 0.015) or 0.015)

    out.update(
        {
            "dominantLeg": dominant,
            "contestedLeg": contested,
            "rallyPoints": round(rally, 1),
            "slidePoints": round(slide, 1),
            "legMarginPts": round(margin_pts, 1),
            "momentum5Pct": round(mom5, 4),
            "indexVelocity3s": round(v3, 4),
            "dominantTrendFlipped": bool(meta.get("dominantTrendFlipped")),
        }
    )

    predicted: DominantTrend = dominant
    reasons: list[str] = []
    if contested:
        reasons.append("both_rally_slide_arms")
        if slide > rally + 1e-6:
            predicted = "SLIDE"
            reasons.append("slide_pts_lead")
        elif rally > slide + 1e-6:
            predicted = "RALLY"
            reasons.append("rally_pts_lead")
        elif mom5 >= mom_thr:
            predicted = "RALLY"
            reasons.append("mom5_rally")
        elif mom5 <= -mom_thr:
            predicted = "SLIDE"
            reasons.append("mom5_slide")
        elif v3 >= vel_thr:
            predicted = "RALLY"
            reasons.append("spot_velocity_up")
        elif v3 <= -vel_thr:
            predicted = "SLIDE"
            reasons.append("spot_velocity_down")
    elif dominant in ("RALLY", "SLIDE"):
        predicted = dominant
        against = (
            (dominant == "RALLY" and mom5 < -mom_thr)
            or (dominant == "SLIDE" and mom5 > mom_thr)
        )
        vel_against = (
            (dominant == "RALLY" and v3 <= -vel_thr)
            or (dominant == "SLIDE" and v3 >= vel_thr)
        )
        if against:
            reasons.append("mom5_against_dominant")
            predicted = "SLIDE" if dominant == "RALLY" else "RALLY"
        if vel_against:
            reasons.append("spot_velocity_against_dominant")
            predicted = "SLIDE" if dominant == "RALLY" else "RALLY"
    elif margin_pts <= thin_margin and (call_armed or put_armed):
        reasons.append("thin_leg_margin")
        predicted = "SLIDE" if slide >= rally else "RALLY"

    out["predictedLeg"] = predicted
    out["predictedBullishOptionSide"] = _leg_to_option_side(predicted)
    out["reasons"] = reasons

    risk: FlipRiskLevel = "NONE"
    if contested:
        risk = "CONTESTED"
    elif reasons and predicted != dominant:
        risk = "IMMINENT"
    elif reasons or margin_pts <= thin_margin:
        risk = "WATCH"
    out["riskLevel"] = risk

    if risk in ("CONTESTED", "IMMINENT") and predicted != dominant and dominant != "NEUTRAL":
        out["flipAwayFrom"] = dominant
    return out


def index_imminent_flip_rank_adjustment(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
    state: Any = None,
    *,
    settings: Any = None,
) -> float:
    """Penalize entries on the side that loses if the index leg flips now."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_imminent_flip_enabled", True)):
        return 0.0
    sym = str(getattr(candidate, "symbol", "") or "").upper()
    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None:
        return 0.0
    side = _side_u(getattr(candidate, "side", ""))
    if side not in ("CALL", "PUT"):
        return 0.0

    assess = index_imminent_flip_assessment(sym, snap, state, settings=settings)
    risk = str(assess.get("riskLevel") or "NONE")
    if risk == "NONE":
        return 0.0

    predicted_side = assess.get("predictedBullishOptionSide")
    if not predicted_side:
        return 0.0

    dominant = str(assess.get("dominantLeg") or "NEUTRAL")
    predicted_u = _side_u(predicted_side)
    if side == predicted_u:
        bonus = float(getattr(settings, "index_imminent_flip_aligned_bonus", 6.0) or 6.0)
        if risk == "IMMINENT":
            bonus += float(
                getattr(settings, "index_imminent_flip_imminent_aligned_bonus", 4.0) or 4.0
            )
        return bonus

    if risk == "WATCH" and side_aligns_with_dominant_trend(side, dominant):
        return 0.0

    wrong_pen = float(getattr(settings, "index_imminent_flip_wrong_side_watch_penalty", 40.0) or 40.0)
    if risk == "IMMINENT":
        wrong_pen = float(
            getattr(settings, "index_imminent_flip_wrong_side_imminent_penalty", 75.0) or 75.0
        )
    elif risk == "CONTESTED":
        wrong_pen = float(
            getattr(settings, "index_imminent_flip_wrong_side_contested_penalty", 55.0) or 55.0
        )
    return -wrong_pen
