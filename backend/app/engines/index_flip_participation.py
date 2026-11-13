"""Leading participation read — breadth, PCR, index orderflow, CE vs PE book (symmetric)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.models.schemas import SymbolSnapshot


def _side_u(raw: Any) -> str:
    val = str(getattr(raw, "value", raw) or "").upper()
    if val in {"CALL", "CE", "C"}:
        return "CALL"
    if val in {"PUT", "PE", "P"}:
        return "PUT"
    return val


def _option_side_to_leg(side: str) -> str:
    if side == "CALL":
        return "RALLY"
    if side == "PUT":
        return "SLIDE"
    return "NEUTRAL"


def index_flip_participation_assessment(
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """
    Who is entering before the index leg label flips — rank/HUD only, not a hard block.
    """
    settings = settings or get_settings()
    enabled = bool(getattr(settings, "index_flip_participation_enabled", True))
    out: dict[str, Any] = {
        "enabled": enabled,
        "leadingOptionSide": None,
        "leadingLeg": "NEUTRAL",
        "confidence": 0.0,
        "callVotes": 0,
        "putVotes": 0,
        "breadthBias": None,
        "pcr": None,
        "callBookScore": 0.0,
        "putBookScore": 0.0,
        "callBookVelocity3s": 0.0,
        "putBookVelocity3s": 0.0,
        "orderflowDeltaVelocity": 0.0,
        "reasons": [],
    }
    if not enabled:
        return out

    min_votes = int(getattr(settings, "index_flip_participation_min_votes", 2) or 2)
    call_votes = 0
    put_votes = 0
    reasons: list[str] = []

    breadth = getattr(snap, "breadth", None)
    breadth_bias = (
        str(getattr(breadth, "bias", None) or "NEUTRAL").upper() if breadth else "NEUTRAL"
    )
    out["breadthBias"] = breadth_bias
    if breadth_bias == "BULLISH":
        call_votes += 1
        reasons.append("breadth_bullish")
    elif breadth_bias == "BEARISH":
        put_votes += 1
        reasons.append("breadth_bearish")

    try:
        pcr = float(getattr(snap, "pcr", 1.0) or 1.0)
    except (TypeError, ValueError):
        pcr = 1.0
    out["pcr"] = round(pcr, 3)
    pcr_hi = float(getattr(settings, "index_flip_participation_pcr_high", 1.12) or 1.12)
    pcr_lo = float(getattr(settings, "index_flip_participation_pcr_low", 0.88) or 0.88)
    if pcr >= pcr_hi:
        put_votes += 1
        reasons.append("pcr_put_skew")
    elif pcr <= pcr_lo:
        call_votes += 1
        reasons.append("pcr_call_skew")

    of = getattr(snap, "orderflow", None)
    delta_v = float(getattr(of, "deltaVelocity", 0) or 0) if of else 0.0
    out["orderflowDeltaVelocity"] = round(delta_v, 2)
    delta_min = float(
        getattr(settings, "index_flip_participation_orderflow_delta_min", 25.0) or 25.0
    )
    if delta_v >= delta_min:
        call_votes += 1
        reasons.append("index_orderflow_buy")
    elif delta_v <= -delta_min:
        put_votes += 1
        reasons.append("index_orderflow_sell")

    from app.engines.best_side_selection import side_velocity_metrics

    book = side_velocity_metrics(snap)
    call_score = float(book.get("callScore") or 0)
    put_score = float(book.get("putScore") or 0)
    call_v3 = float(book.get("callVelocity3s") or 0)
    put_v3 = float(book.get("putVelocity3s") or 0)
    out["callBookScore"] = call_score
    out["putBookScore"] = put_score
    out["callBookVelocity3s"] = call_v3
    out["putBookVelocity3s"] = put_v3

    score_gap = float(
        getattr(settings, "index_flip_participation_book_score_gap", 15.0) or 15.0
    )
    vel_gap = float(
        getattr(settings, "index_flip_participation_book_vel_gap", 0.04) or 0.04
    )
    if put_score >= call_score + score_gap and put_v3 >= call_v3 + vel_gap:
        put_votes += 1
        reasons.append("put_book_leading")
    elif call_score >= put_score + score_gap and call_v3 >= put_v3 + vel_gap:
        call_votes += 1
        reasons.append("call_book_leading")
    dom_book = _side_u(book.get("dominantSide"))
    if dom_book == "PUT" and put_score > 0:
        put_votes += 1
        reasons.append("put_velocity_dominant")
    elif dom_book == "CALL" and call_score > 0:
        call_votes += 1
        reasons.append("call_velocity_dominant")

    # Participation at pad: orderflow-confirmed explosion rows per side.
    call_flow = put_flow = 0
    for alert in getattr(snap, "explosionAlerts", None) or []:
        if not isinstance(alert, dict):
            continue
        side = _side_u(alert.get("side"))
        if not (
            alert.get("orderflowConfirmed")
            or alert.get("optionCvdBuying")
            or alert.get("orderflowPositive")
        ):
            continue
        if side == "CALL":
            call_flow += 1
        elif side == "PUT":
            put_flow += 1
    if call_flow > put_flow and call_flow >= 1:
        call_votes += 1
        reasons.append("call_orderflow_entries")
    elif put_flow > call_flow and put_flow >= 1:
        put_votes += 1
        reasons.append("put_orderflow_entries")

    out["callVotes"] = call_votes
    out["putVotes"] = put_votes
    leading: str | None = None
    if call_votes > put_votes:
        leading = "CALL"
    elif put_votes > call_votes:
        leading = "PUT"
    out["leadingOptionSide"] = leading
    out["leadingLeg"] = _option_side_to_leg(leading or "")

    winner = max(call_votes, put_votes)
    total = call_votes + put_votes
    if leading and winner >= min_votes and total > 0:
        out["confidence"] = round(min(1.0, (winner / total) * (winner / 4.0)), 3)
    else:
        out["confidence"] = 0.0
    out["reasons"] = reasons
    return out


def participation_should_lead_flip(
    dominant: str,
    predicted: str,
    participation: dict[str, Any],
    *,
    settings: Any = None,
    margin_pts: float = 0.0,
    thin_margin: float = 25.0,
) -> tuple[str, list[str]]:
    """Blend participation into leg prediction — lead before spot leg flips."""
    settings = settings or get_settings()
    if not participation.get("enabled"):
        return predicted, []
    p_leg = str(participation.get("leadingLeg") or "NEUTRAL")
    conf = float(participation.get("confidence") or 0)
    min_c = float(getattr(settings, "index_flip_participation_min_confidence", 0.5) or 0.5)
    imm_c = float(
        getattr(settings, "index_flip_participation_imminent_confidence", 0.65) or 0.65
    )
    if p_leg not in ("RALLY", "SLIDE") or conf < min_c:
        return predicted, []
    extra: list[str] = []
    if dominant in ("RALLY", "SLIDE") and p_leg != dominant:
        extra.append("participation_vs_dominant_leg")
        thin = margin_pts <= thin_margin * 1.5
        if conf >= imm_c or (predicted == dominant and thin):
            return p_leg, extra
        if predicted == dominant:
            extra.append("participation_watch_flip")
            return p_leg, extra
    if dominant == "NEUTRAL" and predicted == "NEUTRAL" and conf >= min_c:
        extra.append("participation_neutral_lead")
        return p_leg, extra
    return predicted, extra
