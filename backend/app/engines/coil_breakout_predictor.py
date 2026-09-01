"""Flat-base coil breakout predictor — flag the setup WHILE it's still flat.

By the time a contract is graded ELITE/FTV/S-A it has usually already moved — the
tier/grade is a lagging label. This predictor composes signals that exist DURING
the flat coil, before any real lift, to answer: "is this a tight coil that is
loading, and which way is it likely to break?" It does not (by itself) enter at
the pure flat — predicting a break before any expansion is inherently lower hit
rate — it makes the coil + predicted side + readiness VISIBLE on the radar and
nudges ranking, so the early-ignition lane can take it at the first real move.

Composition (honest about data reliability):
- Coil shape        : option armed-base tightness (range_pct, span) — reliable per contract
- Compression       : INDEX Bollinger/Keltner squeeze on + bars_on — reliable (index)
- Direction lean    : index squeeze direction, index VWAP reclaim, side-regime, and option
                      CVD buying/acceleration (best on ATM+ with dense ticks)
- Pre-awakening     : volume not yet surged (still coiling, not fired)

Output: {coiling, armed, readinessScore 0-100, predictedSide CALL/PUT|None,
predictedConfidence, reasons}. Selection-only; never gates the live trigger/exit.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings


def _side_str(side: Any) -> str:
    from app.models.schemas import Side

    return side.value if isinstance(side, Side) else str(side or "").upper()


def _chart_squeeze(snap: Any) -> dict[str, Any]:
    ca = getattr(snap, "chartAnalysis", None)
    if ca is None:
        return {}
    sq = getattr(ca, "squeeze", None)
    if sq is None and isinstance(ca, dict):
        sq = ca.get("squeeze")
    if isinstance(sq, dict):
        return sq
    if sq is not None and hasattr(sq, "__dict__"):
        return dict(sq.__dict__)
    return {}


def coil_breakout_prediction(
    snap: Any,
    event: Any,
    ict: Any = None,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """Score a flat coil's breakout readiness + predicted side, before it fires."""
    settings = settings or get_settings()
    out: dict[str, Any] = {
        "coiling": False,
        "armed": False,
        "readinessScore": 0.0,
        "predictedSide": None,
        "predictedConfidence": 0.0,
        "reasons": [],
    }
    if not bool(getattr(settings, "coil_breakout_prediction_enabled", True)):
        return out
    if snap is None or event is None:
        return out
    side = _side_str(getattr(event, "side", ""))
    if side not in ("CALL", "PUT"):
        return out

    base_armed = bool(getattr(ict, "base_armed", False)) if ict is not None else False
    range_pct = float(getattr(ict, "armed_base_range_pct", 0) or 0) if ict is not None else 0.0
    span = float(getattr(ict, "armed_base_span_seconds", 0) or 0) if ict is not None else 0.0
    base_move = float(getattr(ict, "base_relative_move_pct", 0) or 0) if ict is not None else 0.0

    squeeze = _chart_squeeze(snap)
    sq_on = bool(squeeze.get("on"))
    sq_bars = int(squeeze.get("bars_on") or 0)
    sq_dir = str(squeeze.get("direction") or "").upper()

    max_range = float(getattr(settings, "coil_prediction_max_range_pct", 5.0) or 5.0)
    # Coiling = a tight, armed local base that is either index-compressed or still in the
    # near-base pad band (not yet a run).
    coiling = bool(
        base_armed
        and (range_pct <= 0 or range_pct <= max_range)
        and (sq_on or 0 < base_move <= 25.0)
    )
    out["armed"] = base_armed
    out["coiling"] = coiling
    if not coiling:
        return out

    bull = side == "CALL"
    votes = 0
    reasons: list[str] = []

    if sq_on and (
        (sq_dir == "BULLISH" and bull) or (sq_dir == "BEARISH" and not bull)
    ):
        votes += 1
        reasons.append("squeeze_dir")

    try:
        from app.engines.advanced_indicators import index_vwap_confirms_side
        from app.models.schemas import Side as _S

        if index_vwap_confirms_side(_S(side), snap):
            votes += 1
            reasons.append("vwap")
    except Exception:
        pass

    try:
        from app.engines.advanced_indicators import (
            option_cvd_acceleration_confirms_buying,
            option_cvd_confirms_buying,
        )

        strike = float(getattr(event, "strike", 0) or 0)
        if strike > 0 and option_cvd_confirms_buying(snap, strike, side):
            votes += 1
            reasons.append("cvd_buying")
            if option_cvd_acceleration_confirms_buying(snap, strike, side):
                votes += 1
                reasons.append("cvd_accel")
    except Exception:
        pass

    try:
        from app.engines.side_regime import session_trade_side

        if session_trade_side(getattr(snap, "symbol", "")) == side:
            votes += 1
            reasons.append("side_regime")
    except Exception:
        pass

    try:
        from app.engines.advanced_indicators import index_decisive_breakout_confirms_side
        from app.models.schemas import Side as _S

        if index_decisive_breakout_confirms_side(_S(side), snap):
            votes += 1
            reasons.append("decisive_candle")
    except Exception:
        pass

    try:
        from app.engines.advanced_indicators import option_decisive_breakout_confirms

        strike = float(getattr(event, "strike", 0) or 0)
        if strike > 0 and option_decisive_breakout_confirms(
            getattr(snap, "symbol", ""), strike, side, settings=settings
        ):
            votes += 1
            reasons.append("option_decisive_break")
    except Exception:
        pass

    # Readiness score (0-100): coil tightness + maturity + compression + pre-awakening + votes.
    score = 0.0
    if range_pct > 0:
        score += max(0.0, 25.0 * (1.0 - min(1.0, range_pct / max_range)))
    else:
        score += 15.0
    score += min(15.0, span / 4.0)
    if sq_on:
        score += min(20.0, 8.0 + sq_bars * 2.0)
    vol_surge = float(getattr(event, "volume_surge", 0) or 0)
    if vol_surge < 1.8:
        score += 10.0
    score += min(30.0, votes * 10.0)
    score = max(0.0, min(100.0, score))

    min_votes = int(getattr(settings, "coil_prediction_min_direction_votes", 2) or 2)
    predicted = side if votes >= min_votes else None

    out.update(
        {
            "readinessScore": round(score, 1),
            "predictedSide": predicted,
            "predictedConfidence": round(min(100.0, votes * 25.0), 1),
            "reasons": reasons,
            "squeezeOn": sq_on,
            "rangePct": round(range_pct, 2),
            "spanSeconds": round(span, 1),
            "directionVotes": votes,
        }
    )
    return out


def coil_prediction_rank_delta(alert: Optional[dict[str, Any]], side: Any) -> float:
    """Soft rank nudge for a ripe coil whose predicted side matches the candidate side."""
    settings = get_settings()
    if not bool(getattr(settings, "coil_breakout_prediction_enabled", True)):
        return 0.0
    if not bool(getattr(settings, "coil_prediction_influences_ranking", True)):
        return 0.0
    if not isinstance(alert, dict):
        return 0.0
    readiness = float(alert.get("coilReadinessScore") or 0)
    predicted = alert.get("coilPredictedSide")
    floor = float(getattr(settings, "coil_prediction_min_readiness_for_rank", 60.0) or 60.0)
    if predicted and _side_str(side) == _side_str(predicted) and readiness >= floor:
        return float(getattr(settings, "coil_prediction_rank_bonus", 10.0) or 10.0)
    return 0.0
