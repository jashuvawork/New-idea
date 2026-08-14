"""Bullish CALL prediction at a confirmed local premium base."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _side_value(value: Any) -> str:
    return value.value if isinstance(value, Side) else str(value or "").upper()


def _inactive(reasons: list[str], *, confidence: float = 0.0) -> dict[str, Any]:
    return {
        "active": False,
        "direction": "WATCH",
        "confidence": round(max(0.0, min(100.0, confidence)), 1),
        "rankBonus": 0.0,
        "baseRelativeMovePct": 0.0,
        "confluenceCount": 0,
        "reasons": reasons,
    }


def bullish_local_base_prediction(
    snap: Optional[SymbolSnapshot],
    event: Any,
    ict: Any,
    *,
    alert: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Grade an early bullish reversal without pretending it is a probability.

    A signal requires all of:
    - CALL side and a top-quality radar event,
    - a measured flat/V/local premium base in the early launch window,
    - live index momentum improving toward CALL,
    - positive option premium acceleration and real volume expansion.

    The returned confidence is a deterministic setup-quality score. Callers may use the
    rank bonus and early-window flag, but every normal entry/risk/execution guard remains.
    """
    settings = get_settings()
    if not bool(getattr(settings, "bullish_local_base_prediction_enabled", True)):
        return _inactive(["disabled"])
    if snap is None or event is None or ict is None:
        return _inactive(["missing_context"])
    if _side_value(getattr(event, "side", "")) != "CALL":
        return _inactive(["not_call"])

    alert = alert if isinstance(alert, dict) else {}
    tier = str(getattr(event, "tier", "") or alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return _inactive(["weak_tier"])

    explosion_score = _number(
        getattr(event, "explosion_score", 0)
        or alert.get("explosionScore")
        or alert.get("score")
    )
    min_score = _number(
        getattr(settings, "bullish_local_base_prediction_min_score", 62.0), 62.0
    )
    if explosion_score < min_score:
        return _inactive(["weak_explosion_score"])

    base_rel = _number(
        getattr(ict, "base_relative_move_pct", 0)
        or alert.get("ictBaseRelativeMovePct")
    )
    base_level = _number(
        getattr(ict, "base_premium", 0) or alert.get("ictBasePremium")
    )
    base_structure = bool(
        getattr(ict, "flat_then_vertical", False)
        or getattr(ict, "local_swing_base", False)
        or base_level > 0
        or alert.get("ictFlatThenVertical")
        or str(alert.get("ictPattern") or "") in (
            "flat_then_vertical",
            "early_flat_break",
            "local_swing_base",
        )
    )
    if not base_structure:
        return _inactive(["no_local_base"])

    min_move = _number(
        getattr(settings, "bullish_local_base_prediction_min_move_pct", 8.0), 8.0
    )
    max_move = _number(
        getattr(settings, "bullish_local_base_prediction_max_move_pct", 40.0), 40.0
    )
    in_window = min_move <= base_rel <= max_move
    if not in_window:
        return _inactive(["outside_local_base_window"])

    velocity_3s = _number(
        getattr(event, "velocity_3s", 0) or alert.get("velocity3s")
    )
    velocity_9s = _number(
        getattr(event, "velocity_9s", 0) or alert.get("velocity9s")
    )
    volume_surge = _number(
        getattr(event, "volume_surge", 0) or alert.get("volumeSurge")
    )
    min_v3 = _number(
        getattr(settings, "bullish_local_base_prediction_min_velocity_3s", 1.5), 1.5
    )
    min_v9 = _number(
        getattr(settings, "bullish_local_base_prediction_min_velocity_9s", 0.2), 0.2
    )
    min_volume = _number(
        getattr(settings, "bullish_local_base_prediction_min_vol_surge", 2.0), 2.0
    )
    premium_accelerating = velocity_3s >= min_v3 and velocity_9s >= min_v9
    volume_confirmed = volume_surge >= min_volume

    from app.engines.local_base_chart_bypass import local_base_momentum_turn

    momentum_turn = local_base_momentum_turn(
        Side.CALL, snap, event=event, alert=alert,
    )

    # Existing confluence is evidence, not a hard dependency: a turn can lead lagging
    # ADX/Supertrend/VWAP at the actual bottom. CVD/squeeze still improve ranking.
    from app.engines.advanced_indicators import build_entry_confluence

    confluence = build_entry_confluence(snap, event)
    confluence_count = int(_number(confluence.get("score"), 0.0))

    confidence = 20.0  # measured local premium base
    confidence += 15.0  # early 8-40% launch window
    if momentum_turn:
        confidence += 25.0
    if premium_accelerating:
        confidence += 15.0
    if volume_confirmed:
        confidence += 10.0
    confidence += min(15.0, confluence_count * 3.0)
    confidence = max(0.0, min(100.0, confidence))

    min_confidence = _number(
        getattr(settings, "bullish_local_base_prediction_min_confidence", 70.0), 70.0
    )
    active = bool(
        momentum_turn
        and premium_accelerating
        and volume_confirmed
        and confidence >= min_confidence
    )
    rank_max = _number(
        getattr(settings, "bullish_local_base_prediction_rank_max", 18.0), 18.0
    )
    reasons = ["local_base", "early_launch_window"]
    if momentum_turn:
        reasons.append("bullish_momentum_turn")
    if premium_accelerating:
        reasons.append("premium_accelerating")
    if volume_confirmed:
        reasons.append("volume_expanding")
    if confluence_count:
        reasons.append(f"confluence_{confluence_count}")

    return {
        "active": active,
        "direction": "BULLISH" if active else "WATCH",
        "confidence": round(confidence, 1),
        "rankBonus": round(rank_max * confidence / 100.0, 2) if active else 0.0,
        "baseRelativeMovePct": round(base_rel, 1),
        "confluenceCount": confluence_count,
        "reasons": reasons,
    }
