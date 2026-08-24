"""Local-base reversal prediction — CE and PE flat→vertical first lifts (ICT-aligned).

Promotes a confirmed early launch off a measured premium base when:
- CALL or PUT top-quality radar event,
- local/flat/V premium base in the early window,
- live index momentum turning toward that side,
- option premium accelerating with volume,
- optional ICT confirms (premium FVG, index OTE, Judas+displacement, CHoCH/MSS).

Never bypasses chase / fake-trap / risk / execution-chart safety.
"""

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


def _inactive(reasons: list[str], *, confidence: float = 0.0, side: str = "") -> dict[str, Any]:
    return {
        "active": False,
        "side": side or "",
        "direction": "WATCH",
        "confidence": round(max(0.0, min(100.0, confidence)), 1),
        "rankBonus": 0.0,
        "baseRelativeMovePct": 0.0,
        "confluenceCount": 0,
        "ictConfirms": [],
        "reasons": reasons,
    }


def _index_smc(snap: Optional[SymbolSnapshot]) -> dict[str, Any]:
    ca = getattr(snap, "chartAnalysis", None) if snap is not None else None
    if ca is None:
        return {}
    inst = getattr(ca, "institutional", None)
    if isinstance(inst, dict):
        return inst
    if inst is not None and hasattr(inst, "model_dump"):
        try:
            return inst.model_dump()
        except Exception:
            pass
    if isinstance(ca, dict):
        raw = ca.get("institutional") or ca.get("smc") or {}
        return raw if isinstance(raw, dict) else {}
    return {}


def _ict_confirms_for_side(
    side_v: str,
    snap: Optional[SymbolSnapshot],
    ict: Any,
    *,
    settings: Any,
) -> tuple[list[str], float]:
    """Best-fit ICT evidence for CE/PE local-base reversals.

    Returns (confirm_tags, bonus_points). Additive only — never a hard fail.
    """
    confirms: list[str] = []
    bonus = 0.0
    smc = _index_smc(snap)

    # 1) Premium FVG / imbalance — option premium gaps up on the rip (both CE and PE).
    if bool(getattr(ict, "premium_fvg", False)):
        confirms.append("premium_fvg")
        bonus += 6.0

    # 2) Index OTE / discount-premium: CALL from discount, PUT from premium.
    pd = str(smc.get("premiumDiscount") or "").upper()
    if side_v == "CALL" and pd == "DISCOUNT":
        confirms.append("index_discount_ote")
        bonus += 5.0
    elif side_v == "PUT" and pd == "PREMIUM":
        confirms.append("index_premium_ote")
        bonus += 5.0

    # 3) Judas / stop-hunt then reclaim toward the option side.
    stop_hunt = str(smc.get("stopHunt") or "").lower()
    judas = bool(smc.get("judasSwing"))
    displacement_idx = bool(smc.get("displacement"))
    if side_v == "CALL" and (
        stop_hunt == "buy_side_liquidity_sweep" or (judas and displacement_idx)
    ):
        confirms.append("judas_buy_side_reclaim")
        bonus += 5.0
    elif side_v == "PUT" and (
        stop_hunt == "sell_side_liquidity_sweep" or (judas and displacement_idx)
    ):
        confirms.append("judas_sell_side_reclaim")
        bonus += 5.0
    if displacement_idx and getattr(ict, "displacement", False):
        confirms.append("index_option_displacement")
        bonus += 3.0

    # 4) CISD / MSS — CHoCH toward the option side.
    choch = str(smc.get("choch") or "").lower()
    bos = str(smc.get("bos") or "").lower()
    if side_v == "CALL" and ("bullish_choch" in choch or bos == "bullish_bos"):
        confirms.append("bullish_mss")
        bonus += 5.0
    elif side_v == "PUT" and ("bearish_choch" in choch or bos == "bearish_bos"):
        confirms.append("bearish_mss")
        bonus += 5.0

    # 5) Kill-zone timing (NSE open / PM) — mild boost only.
    if bool(smc.get("inKillZone")) and bool(
        getattr(settings, "local_base_reversal_kill_zone_bonus_enabled", True)
    ):
        confirms.append(str(smc.get("killZone") or "kill_zone"))
        bonus += 2.0

    # Cap ICT bonus so confluence/turn still dominate quality.
    max_bonus = _number(
        getattr(settings, "local_base_reversal_ict_bonus_max", 18.0), 18.0
    )
    return confirms, min(max_bonus, bonus)


def local_base_reversal_prediction(
    snap: Optional[SymbolSnapshot],
    event: Any,
    ict: Any,
    *,
    alert: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Grade an early CE/PE reversal at a confirmed local premium base."""
    settings = get_settings()
    enabled = bool(
        getattr(settings, "bullish_local_base_prediction_enabled", True)
        or getattr(settings, "local_base_reversal_prediction_enabled", True)
    )
    if not enabled:
        return _inactive(["disabled"])
    if snap is None or event is None or ict is None:
        return _inactive(["missing_context"])

    side_v = _side_value(getattr(event, "side", ""))
    if side_v not in ("CALL", "PUT"):
        return _inactive(["invalid_side"], side=side_v)

    alert = alert if isinstance(alert, dict) else {}
    tier = str(getattr(event, "tier", "") or alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return _inactive(["weak_tier"], side=side_v)

    explosion_score = _number(
        getattr(event, "explosion_score", 0)
        or alert.get("explosionScore")
        or alert.get("score")
    )
    min_score = _number(
        getattr(settings, "bullish_local_base_prediction_min_score", 62.0), 62.0
    )
    premium = _number(getattr(event, "premium", 0) or alert.get("premium"))
    soft_prem_cap = _number(
        getattr(settings, "fast_bullish_local_base_max_premium_inr", 30.0), 30.0
    )
    if premium > 0 and premium <= soft_prem_cap:
        min_score = min(
            min_score,
            _number(
                getattr(settings, "fast_bullish_local_base_soft_min_score", 45.0),
                45.0,
            ),
        )
    if explosion_score < min_score:
        return _inactive(["weak_explosion_score"], side=side_v)

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
        return _inactive(["no_local_base"], side=side_v)

    min_move = _number(
        getattr(settings, "bullish_local_base_prediction_min_move_pct", 8.0), 8.0
    )
    max_move = _number(
        getattr(settings, "bullish_local_base_prediction_max_move_pct", 40.0), 40.0
    )
    if not (min_move <= base_rel <= max_move):
        return _inactive(["outside_local_base_window"], side=side_v)

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
    if premium > 0 and premium <= soft_prem_cap and volume_surge >= min_volume:
        min_v3 = min(
            min_v3,
            _number(
                getattr(settings, "fast_bullish_local_base_min_velocity_3s", 0.8),
                0.8,
            ),
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

    side_enum = Side.CALL if side_v == "CALL" else Side.PUT
    momentum_turn = local_base_momentum_turn(
        side_enum, snap, event=event, alert=alert,
    )

    from app.engines.advanced_indicators import build_entry_confluence

    confluence = build_entry_confluence(snap, event)
    confluence_count = int(_number(confluence.get("score"), 0.0))

    ict_confirms, ict_bonus = _ict_confirms_for_side(
        side_v, snap, ict, settings=settings,
    )

    confidence = 20.0  # measured local premium base
    confidence += 15.0  # early launch window
    if momentum_turn:
        confidence += 25.0
    if premium_accelerating:
        confidence += 15.0
    if volume_confirmed:
        confidence += 10.0
    confidence += min(15.0, confluence_count * 3.0)
    confidence += ict_bonus
    confidence = max(0.0, min(100.0, confidence))

    min_confidence = _number(
        getattr(settings, "bullish_local_base_prediction_min_confidence", 70.0), 70.0
    )
    if premium > 0 and premium <= soft_prem_cap:
        min_confidence = min(
            min_confidence,
            _number(
                getattr(
                    settings,
                    "fast_bullish_local_base_soft_min_confidence",
                    60.0,
                ),
                60.0,
            ),
        )
    # Optional: require at least one ICT confirm on choppiest days — off by default.
    require_ict = bool(
        getattr(settings, "local_base_reversal_require_ict_confirm", False)
    )
    ict_ok = (not require_ict) or bool(ict_confirms)
    active = bool(
        momentum_turn
        and premium_accelerating
        and volume_confirmed
        and confidence >= min_confidence
        and ict_ok
    )
    rank_max = _number(
        getattr(settings, "bullish_local_base_prediction_rank_max", 18.0), 18.0
    )
    turn_reason = (
        "bullish_momentum_turn" if side_v == "CALL" else "bearish_momentum_turn"
    )
    reasons = ["local_base", "early_launch_window"]
    if momentum_turn:
        reasons.append(turn_reason)
    if premium_accelerating:
        reasons.append("premium_accelerating")
    if volume_confirmed:
        reasons.append("volume_expanding")
    if confluence_count:
        reasons.append(f"confluence_{confluence_count}")
    reasons.extend(ict_confirms)

    direction = "BULLISH" if side_v == "CALL" else "BEARISH"
    return {
        "active": active,
        "side": side_v,
        "direction": direction if active else "WATCH",
        "confidence": round(confidence, 1),
        "rankBonus": round(rank_max * confidence / 100.0, 2) if active else 0.0,
        "baseRelativeMovePct": round(base_rel, 1),
        "confluenceCount": confluence_count,
        "ictConfirms": ict_confirms,
        "reasons": reasons,
    }


def bullish_local_base_prediction(
    snap: Optional[SymbolSnapshot],
    event: Any,
    ict: Any,
    *,
    alert: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Backward-compatible name — now CE+PE via ``local_base_reversal_prediction``."""
    return local_base_reversal_prediction(snap, event, ict, alert=alert)
