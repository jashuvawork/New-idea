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

from typing import Any, Mapping, Optional

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


def _index_side_aligned(
    side_v: str,
    snap: Optional[SymbolSnapshot],
    alert: Mapping[str, Any],
) -> bool:
    if bool(alert.get("indexMomAlign") or alert.get("indexHelpersConfirm")):
        return True
    if snap is None:
        return False
    breadth = str(getattr(getattr(snap, "breadth", None), "bias", "NEUTRAL") or "NEUTRAL").upper()
    if side_v == "CALL" and breadth == "BULLISH":
        return True
    if side_v == "PUT" and breadth == "BEARISH":
        return True
    chart = getattr(snap, "spotChart", None)
    if chart is not None:
        from app.engines.spot_direction import side_aligned_with_chart
        from app.models.schemas import Side

        if side_v in ("CALL", "PUT"):
            return side_aligned_with_chart(Side(side_v), chart)
    return False


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
    soft_prem_min = _number(
        getattr(settings, "local_base_pad_capture_min_premium_inr", 18.0), 18.0
    )
    soft_prem_cap = _number(
        getattr(settings, "fast_bullish_local_base_max_premium_inr", 220.0), 220.0
    )
    in_pad_band = premium > 0 and soft_prem_min <= premium <= soft_prem_cap
    if in_pad_band:
        min_score = min(
            min_score,
            _number(
                getattr(settings, "fast_bullish_local_base_soft_min_score", 45.0),
                45.0,
            ),
            _number(
                getattr(settings, "bullish_local_base_pad_min_explosion_score", 12.0),
                12.0,
            ),
        )
    if explosion_score < min_score:
        return _inactive(["weak_explosion_score"], side=side_v)

    base_rel = _number(
        getattr(ict, "base_relative_move_pct", 0)
        or alert.get("ictBaseRelativeMovePct")
        or alert.get("localBaseMovePct")
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
    if in_pad_band:
        max_move = max(
            max_move,
            _number(
                getattr(settings, "bullish_local_base_pad_max_move_pct", 45.0), 45.0
            ),
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
    min_volume = _number(
        getattr(settings, "bullish_local_base_prediction_min_vol_surge", 2.0), 2.0
    )
    min_v3 = _number(
        getattr(settings, "bullish_local_base_prediction_min_velocity_3s", 1.5), 1.5
    )
    if in_pad_band and volume_surge >= min_volume:
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
    volume_awake = bool(
        alert.get("volumeAwaken")
        or alert.get("ictVolumeAwakening")
        or getattr(ict, "volume_awakening", False)
    )
    premium_accelerating = velocity_3s >= min_v3 and velocity_9s >= min_v9
    volume_confirmed = volume_surge >= min_volume
    # Volume awakening at the session trough IS the lift trigger — allow v3≈0 only.
    # Do not treat stale low v3 (e.g. 0.2) as pad-ready (Jul24 structured near-ATM trap).
    trough_eps = _number(
        getattr(settings, "bullish_local_base_trough_velocity_eps", 0.05), 0.05
    )
    trough_awakening = bool(
        in_pad_band
        and volume_confirmed
        and velocity_3s <= trough_eps
        and velocity_3s >= 0
    )
    premium_ok = premium_accelerating or trough_awakening

    from app.engines.local_base_chart_bypass import local_base_momentum_turn

    side_enum = Side.CALL if side_v == "CALL" else Side.PUT
    momentum_turn = local_base_momentum_turn(
        side_enum, snap, event=event, alert=alert,
    )
    index_aligned = _index_side_aligned(side_v, snap, alert)
    turn_ok = momentum_turn or index_aligned

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
    elif trough_awakening:
        confidence += 12.0
    if volume_confirmed:
        confidence += 10.0
    confidence += min(15.0, confluence_count * 3.0)
    confidence += ict_bonus
    confidence = max(0.0, min(100.0, confidence))

    min_confidence = _number(
        getattr(settings, "bullish_local_base_prediction_min_confidence", 70.0), 70.0
    )
    if in_pad_band:
        min_confidence = min(
            min_confidence,
            _number(
                getattr(settings, "bullish_local_base_pad_min_confidence", 55.0),
                55.0,
            ),
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
        turn_ok
        and premium_ok
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
    elif index_aligned:
        reasons.append("index_side_aligned")
    if premium_accelerating:
        reasons.append("premium_accelerating")
    elif trough_awakening:
        reasons.append("trough_volume_awakening")
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


def alert_bullish_local_base_prediction(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
) -> dict[str, Any]:
    """Alert-only wrapper for selector chart/score bypass paths."""
    from types import SimpleNamespace

    from app.models.schemas import Side

    row = dict(alert)
    side_raw = str(row.get("side") or "").upper()
    side = Side(side_raw) if side_raw in ("CALL", "PUT") else None
    event = SimpleNamespace(
        side=side,
        tier=str(row.get("tier") or ""),
        explosion_score=float(row.get("explosionScore") or row.get("score") or 0),
        premium=float(row.get("premium") or 0),
        velocity_3s=float(row.get("velocity3s") or 0),
        velocity_9s=float(row.get("velocity9s") or 0),
        volume_surge=float(row.get("volumeSurge") or 0),
        daily_move_pct=float(row.get("dailyMovePct") or 0),
        peak_move_pct=float(row.get("peakMovePct") or 0),
    )
    ict = SimpleNamespace(
        base_relative_move_pct=float(
            row.get("ictBaseRelativeMovePct") or row.get("localBaseMovePct") or 0
        ),
        flat_then_vertical=bool(row.get("ictFlatThenVertical")),
        local_swing_base=bool(row.get("ictLocalSwingBase")),
        volume_awakening=bool(
            row.get("ictVolumeAwakening") or row.get("volumeAwaken")
        ),
        premium_fvg=bool(row.get("ictPremiumFvg") or row.get("premiumFvgPadReady")),
        displacement=bool(row.get("ictDisplacement")),
        active=bool(row.get("ictBreakout")),
    )
    return local_base_reversal_prediction(snap, event, ict, alert=row)


def alert_bullish_local_base_active(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
) -> bool:
    return bool(alert_bullish_local_base_prediction(alert, snap).get("active"))


def _pad_move_band(
    alert: Mapping[str, Any],
    *,
    settings: Any | None = None,
) -> tuple[float, float, float]:
    s = settings or get_settings()
    base_rel = _number(
        alert.get("localBaseMovePct")
        or alert.get("ictBaseRelativeMovePct")
        or alert.get("offLowMovePct")
    )
    lo = _number(getattr(s, "ict_v_rip_pad_min_move_pct", 2.0), 2.0)
    hi = _number(getattr(s, "bullish_local_base_pad_max_move_pct", 45.0), 45.0)
    return base_rel, lo, hi


def alert_is_bullish_local_base_pad_entry(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """True when bullish local-base prediction is live at a measured session pad.

    Lifts session halts (expiry afternoon wait, declining halt, worst-day pause)
    for Aug27-style afternoon armed_base_launch pads that radar already graded A+.
    """
    settings = get_settings()
    if not bool(
        getattr(settings, "bullish_local_base_pad_session_bypass_enabled", True)
    ):
        return False
    if not bool(alert.get("tradeable", True)):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False
    base_rel, lo, hi = _pad_move_band(alert, settings=settings)
    if not (lo <= base_rel <= hi + 1e-6):
        return False
    structure = bool(
        alert.get("ictFirstLift")
        or alert.get("ictArmedBaseLaunch")
        or alert.get("ictFlatThenVertical")
        or alert.get("ictBreakout")
        or alert.get("ictBaseArmed")
    )
    if not structure:
        return False
    if bool(alert.get("bullishLocalBaseActive")):
        return True
    if snap is None:
        return False
    return alert_bullish_local_base_active(alert, snap)


def snapshots_have_bullish_local_base_pad(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    for snap in snapshots.values():
        if not getattr(snap, "dataAvailable", False):
            continue
        for alert in snap.explosionAlerts or []:
            merged = dict(alert)
            merged.setdefault("symbol", snap.symbol)
            if alert_is_bullish_local_base_pad_entry(merged, snap):
                return True
    return False
