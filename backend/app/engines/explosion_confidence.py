"""High-confidence explosion filter — align missed-trade radar with tradeable base rips."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.moneyness import atm_strike, classify_moneyness
from app.engines.premium_filter import premium_in_band
from app.engines.spot_direction import side_aligned_with_chart
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Any) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def explosion_session_move(alert_or_event: Any) -> float:
    if alert_or_event is None:
        return 0.0
    if isinstance(alert_or_event, dict):
        return max(
            float(alert_or_event.get("dailyMovePct") or alert_or_event.get("openPremiumMove") or 0),
            float(alert_or_event.get("peakMovePct") or 0),
        )
    return max(
        float(getattr(alert_or_event, "daily_move_pct", 0) or 0),
        float(getattr(alert_or_event, "peak_move_pct", 0) or 0),
    )


def high_confidence_explosion(
    *,
    side: Any,
    strike: float,
    premium: float,
    snap: SymbolSnapshot,
    alert: Optional[dict[str, Any]] = None,
    explosion_event: Any = None,
    tier: str = "",
    score: float = 0.0,
    ict_flat: bool = False,
    ict_displacement: bool = False,
    volume_awakening: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """
    True when this looks like a Jul15-style base rip — not a Jul20 cheap OTM chase.

    Checklist: ELITE/EXPLODING, score floor, early/base move window, premium in band,
    chart-aligned side, ATM/near (not deep cheap OTM).
    """
    settings = get_settings()
    meta: dict[str, Any] = {"highConfidenceExplosion": False}
    tier_u = str(tier or (alert or {}).get("tier") or getattr(explosion_event, "tier", "") or "").upper()
    score_v = float(
        score
        or (alert or {}).get("explosionScore")
        or getattr(explosion_event, "explosion_score", 0)
        or 0
    )
    move = explosion_session_move(alert if alert is not None else explosion_event)
    min_score = float(getattr(settings, "missed_explosion_promote_min_score", 70.0) or 70.0)
    min_move = float(getattr(settings, "missed_explosion_promote_min_move_pct", 28.0) or 28.0)
    max_move = float(getattr(settings, "missed_explosion_promote_max_move_pct", 55.0) or 55.0)

    if tier_u not in ("ELITE", "EXPLODING"):
        return False, "tier_not_elite", meta
    if score_v < min_score:
        return False, f"score_{score_v:.0f}<{min_score:.0f}", meta
    if move < min_move:
        return False, f"immature_move_{move:.1f}%", meta
    if move > max_move:
        return False, f"extended_chase_{move:.1f}%", meta

    prem = float(premium or 0)
    peak = move
    if not premium_in_band(prem, mode="explosion", peak_move_pct=peak):
        return False, "premium_out_of_band", meta

    side_v = _side_val(side)
    if snap.spotChart and not side_aligned_with_chart(side_v, snap.spotChart):
        # Breadth-aligned CALL on bullish breadth can still qualify
        breadth = str(snap.breadth.bias if snap.breadth else "NEUTRAL").upper()
        if not (
            (side_v == "CALL" and breadth == "BULLISH")
            or (side_v == "PUT" and breadth == "BEARISH")
        ):
            return False, "not_chart_aligned", meta

    spot = float(snap.spot or 0)
    money = "ATM"
    if spot > 0:
        atm = float(snap.atmStrike or atm_strike(spot, snap.symbol))
        money = classify_moneyness(side_v, float(strike), spot, symbol=snap.symbol, atm=atm)
    meta["moneyness"] = money
    # Deep cheap OTM was the afternoon false radar — require ATM/ITM or 1-step OTM
    if money == "OTM":
        from app.engines.moneyness import _depth_steps

        depth = _depth_steps(side_v, float(strike), spot, snap.symbol, float(snap.atmStrike or spot))
        meta["otmSteps"] = depth
        if depth > 2:
            return False, f"otm_too_deep_{depth}", meta

    alert = alert or {}
    flat = ict_flat or bool(alert.get("ictFlatThenVertical"))
    disp = ict_displacement or bool(alert.get("ictDisplacement"))
    vol = volume_awakening or bool(alert.get("volumeAwaken") or alert.get("ictVolumeAwakening"))
    if explosion_event is not None and not flat:
        try:
            from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

            ict = analyze_explosion_event_ict(explosion_event, snap)
            flat = flat or bool(ict.flat_then_vertical and ict.active)
            disp = disp or bool(ict.displacement)
            vol = vol or bool(ict.volume_awakening)
        except Exception:
            pass

    # Prefer ICT confirmation; allow clean ELITE in window without ICT if chart aligned
    ict_ok = flat or (disp and vol) or tier_u == "ELITE"
    if not ict_ok:
        return False, "no_ict_confirmation", meta

    meta.update({
        "highConfidenceExplosion": True,
        "tier": tier_u,
        "score": round(score_v, 1),
        "sessionMovePct": round(move, 1),
        "ictFlat": flat,
        "ictDisplacement": disp,
        "volumeAwakening": vol,
    })
    return True, "high_confidence_base_rip", meta


def missed_explosion_rank_bonus(candidate: Any, snap: SymbolSnapshot) -> float:
    """Rank boost for radar explosions that match the missed-trade keep list."""
    settings = get_settings()
    if not getattr(settings, "missed_explosion_promote_enabled", True):
        return 0.0
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return 0.0

    alert = getattr(candidate, "alert", None) or {}
    event = getattr(candidate, "explosion_event", None)
    # Prefer explosionScore (confidence); candidate.score is often the rank composite.
    exp_score = float(
        getattr(candidate, "confidence", 0)
        or (alert.get("explosionScore") if isinstance(alert, dict) else 0)
        or getattr(event, "explosion_score", 0)
        or 0
    )
    ok, reason, meta = high_confidence_explosion(
        side=candidate.side,
        strike=float(candidate.strike),
        premium=float(candidate.premium or 0),
        snap=snap,
        alert=alert if isinstance(alert, dict) else {},
        explosion_event=event,
        tier=str(getattr(candidate, "tier", "") or ""),
        score=exp_score,
    )
    if not ok:
        return 0.0
    bonus = float(getattr(settings, "missed_explosion_promote_rank_bonus", 22.0) or 22.0)
    if meta.get("ictFlat"):
        bonus += 6.0
    if meta.get("moneyness") in ("ATM", "ITM"):
        bonus += 4.0
    # Stash for entry context
    try:
        candidate.pretrade_meta = {
            **(getattr(candidate, "pretrade_meta", None) or {}),
            "highConfidenceExplosion": meta,
            "missedExplosionPromote": True,
            "promoteReason": reason,
        }
    except Exception:
        pass
    return bonus


def is_high_conviction_entry(
    *,
    side: Any,
    snap: SymbolSnapshot,
    tier: str,
    score: float,
    move_pct: float,
    chart_confidence: float,
) -> bool:
    """
    Very high-confidence base rip → take max lots + hold longer.

    Strict: ELITE, score≥90, chartConf≥85, matched side (chart or breadth), and move in
    the 28-55% base window. This is the Jul22 SENSEX 77200 PE profile (ELITE 100, conf 95)
    that only got 4 lots and trailed out in 1 min while it ran +122%.
    """
    settings = get_settings()
    if not getattr(settings, "high_conviction_sizing_enabled", True):
        return False
    if str(tier or "").upper() != "ELITE":
        return False
    if float(score or 0) < float(getattr(settings, "high_conviction_min_score", 90.0) or 90.0):
        return False
    if float(chart_confidence or 0) < float(
        getattr(settings, "high_conviction_min_chart_confidence", 85.0) or 85.0
    ):
        return False
    lo = float(getattr(settings, "missed_explosion_promote_min_move_pct", 28.0) or 28.0)
    hi = float(getattr(settings, "missed_explosion_promote_max_move_pct", 55.0) or 55.0)
    if not (lo <= float(move_pct or 0) <= hi):
        return False
    side_v = _side_val(side)
    if snap is not None and snap.spotChart and not side_aligned_with_chart(side_v, snap.spotChart):
        breadth = str(snap.breadth.bias if snap.breadth else "NEUTRAL").upper()
        if not (
            (side_v == "CALL" and breadth == "BULLISH")
            or (side_v == "PUT" and breadth == "BEARISH")
        ):
            return False
    return True


def trade_is_high_conviction(trade: Any) -> bool:
    """True when this open trade was flagged high-conviction at entry."""
    ctx = getattr(trade, "entryContext", None) or {}
    return bool(ctx.get("highConviction"))
