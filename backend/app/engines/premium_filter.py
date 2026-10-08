"""Option premium (LTP) band filter for tradeable analysis range."""

from __future__ import annotations

from typing import Any

from app.config import get_settings


def premium_in_band(
    premium: float | None,
    *,
    mode: str = "default",
    peak_move_pct: float = 0.0,
    snap: Any = None,
) -> bool:
    """True when option LTP is within configured tradeable band."""
    if premium is None or premium <= 0:
        return False
    settings = get_settings()
    max_prem = settings.max_option_premium_inr
    if mode == "explosion" and settings.explosion_max_premium_inr > 0:
        max_prem = max(max_prem, settings.explosion_max_premium_inr)
    min_prem = settings.min_option_premium_inr
    # Same-day expiry: soften floor so ~₹15–20 near-base rips clear (Aug4 24550 PE).
    if snap is not None and mode == "explosion":
        try:
            from app.engines.expiry_day_guards import is_symbol_expiry_day

            if is_symbol_expiry_day(snap):
                expiry_floor = float(
                    getattr(settings, "expiry_day_min_option_premium_inr", 15.0) or 15.0
                )
                min_prem = min(min_prem, expiry_floor)
        except Exception:
            pass
    if mode == "explosion":
        cheap_min = float(getattr(settings, "explosion_cheap_rip_min_premium_inr", 12.0) or 12.0)
        cheap_peak = float(getattr(settings, "explosion_cheap_rip_min_peak_pct", 28.0) or 28.0)
        try:
            from app.engines.session_timing import in_open_premium_window

            if in_open_premium_window():
                cheap_min = min(
                    cheap_min,
                    float(
                        getattr(settings, "expiry_open_cheap_premium_min_inr", 10.0) or 10.0
                    ),
                    float(
                        getattr(settings, "explosion_open_cheap_rip_min_premium_inr", 10.0)
                        or 10.0
                    ),
                )
                cheap_peak = min(
                    cheap_peak,
                    float(
                        getattr(settings, "expiry_open_cheap_rip_min_peak_pct", 15.0) or 15.0
                    ),
                )
        except Exception:
            pass
        if peak_move_pct >= cheap_peak and premium >= cheap_min:
            min_prem = min(min_prem, cheap_min)
        # Mid-rip ATM/ITM (180→450+) stays tradeable for max-TP capture.
        ict_ceil = float(getattr(settings, "explosion_ict_max_premium_inr", 0) or 0)
        if ict_ceil > max_prem and peak_move_pct >= 28.0:
            max_prem = max(max_prem, ict_ceil)
    return min_prem <= premium <= max_prem


def premium_band_label() -> str:
    settings = get_settings()
    return f"₹{settings.min_option_premium_inr:.0f}–₹{settings.max_option_premium_inr:.0f}"


def _explosion_min_premium(
    premium: float,
    *,
    peak_move_pct: float = 0.0,
    snap: Any = None,
    settings: Any = None,
) -> float:
    """Lower bound used by premium_in_band for explosion mode."""
    settings = settings or get_settings()
    min_prem = float(getattr(settings, "min_option_premium_inr", 18.0) or 18.0)
    if snap is not None:
        try:
            from app.engines.expiry_day_guards import is_symbol_expiry_day

            if is_symbol_expiry_day(snap):
                expiry_floor = float(
                    getattr(settings, "expiry_day_min_option_premium_inr", 15.0) or 15.0
                )
                min_prem = min(min_prem, expiry_floor)
        except Exception:
            pass
    cheap_min = float(getattr(settings, "explosion_cheap_rip_min_premium_inr", 12.0) or 12.0)
    cheap_peak = float(getattr(settings, "explosion_cheap_rip_min_peak_pct", 28.0) or 28.0)
    try:
        from app.engines.session_timing import in_open_premium_window

        if in_open_premium_window():
            cheap_min = min(
                cheap_min,
                float(getattr(settings, "expiry_open_cheap_premium_min_inr", 10.0) or 10.0),
                float(
                    getattr(settings, "explosion_open_cheap_rip_min_premium_inr", 10.0) or 10.0
                ),
            )
            cheap_peak = min(
                cheap_peak,
                float(getattr(settings, "expiry_open_cheap_rip_min_peak_pct", 15.0) or 15.0),
            )
    except Exception:
        pass
    if peak_move_pct >= cheap_peak and premium >= cheap_min:
        min_prem = min(min_prem, cheap_min)
    return min_prem


def oct_paper_slide_explosion_context_armed(
    alert: dict[str, Any],
    snap: Any,
    state: Any,
    *,
    settings: Any = None,
) -> bool:
    """Index slide (PUT) or rally (CALL) capture armed — Frozen Oct symmetric book."""
    settings = settings or get_settings()
    if not isinstance(alert, dict) or snap is None:
        return False
    side_u = str(alert.get("side") or "").upper()
    sym = str(alert.get("symbol") or getattr(snap, "symbol", "") or "").upper()
    if not sym:
        return False
    if side_u == "PUT":
        from app.engines.put_slide_ce_mirror import put_pe_base_context_armed

        ok, _, _ = put_pe_base_context_armed(
            state,
            snap,
            sym,
            alert,
            settings=settings,
        )
        return ok
    if side_u == "CALL":
        from app.models.schemas import Side

        from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

        ok, _, _ = index_rally_side_flip_bypass(sym, Side.CALL, snap, settings=settings)
        return ok
    return False


def explosion_alert_premium_tradeable(
    premium: float | None,
    *,
    peak_move_pct: float = 0.0,
    snap: Any = None,
    alert: dict[str, Any] | None = None,
    state: Any = None,
    settings: Any = None,
) -> bool:
    """
    Explosion candidate premium check — standard band, or Oct paper slide/rally waiver
    for ELITE/EXPLODING ATM/ITM when index move context is armed.
    """
    if premium is None or float(premium) <= 0:
        return False
    prem = float(premium)
    if premium_in_band(prem, mode="explosion", peak_move_pct=peak_move_pct, snap=snap):
        return True
    settings = settings or get_settings()
    if not bool(getattr(settings, "oct_paper_slide_premium_waiver_enabled", True)):
        return False
    if not isinstance(alert, dict) or snap is None:
        return False
    from app.engines.live_paper_parity import trading_rules_match_paper

    if not trading_rules_match_paper(settings):
        return False
    tier_u = str(alert.get("tier") or "").upper()
    score = float(alert.get("explosionScore") or alert.get("score") or 0)
    min_score = float(getattr(settings, "aggressive_min_explosion_score", 45.0) or 45.0)
    if tier_u not in ("ELITE", "EXPLODING") or score < min_score:
        return False
    side_u = str(alert.get("side") or "").upper()
    try:
        strike_v = float(alert.get("strike") or 0)
    except (TypeError, ValueError):
        strike_v = 0.0
    spot_v = float(getattr(snap, "spot", 0) or 0)
    if side_u not in ("CALL", "PUT") or strike_v <= 0 or spot_v <= 0:
        return False
    from app.models.schemas import Side

    from app.engines.moneyness import _depth_steps, classify_moneyness

    symbol = str(getattr(snap, "symbol", "") or alert.get("symbol") or "").upper()
    atm_v = float(getattr(snap, "atmStrike", 0) or 0)
    money = classify_moneyness(
        Side(side_u),
        strike_v,
        spot_v,
        symbol=symbol,
        atm=atm_v if atm_v > 0 else None,
    )
    if money == "OTM":
        depth = _depth_steps(
            Side(side_u),
            strike_v,
            spot_v,
            symbol,
            atm_v if atm_v > 0 else spot_v,
        )
        max_otm = int(getattr(settings, "explosion_shallow_otm_entry_steps", 1) or 1)
        if depth > max_otm:
            return False
    if not oct_paper_slide_explosion_context_armed(alert, snap, state, settings=settings):
        return False
    min_prem = _explosion_min_premium(
        prem, peak_move_pct=peak_move_pct, snap=snap, settings=settings,
    )
    if prem < min_prem:
        return False
    slide_max = float(
        getattr(settings, "oct_paper_slide_explosion_max_premium_inr", 650.0) or 650.0
    )
    return prem <= slide_max


def premium_reject_reason(premium: float | None, *, mode: str = "default") -> str:
    if premium is None or premium <= 0:
        return "missing_premium"
    settings = get_settings()
    max_prem = settings.max_option_premium_inr
    if mode == "explosion" and settings.explosion_max_premium_inr > 0:
        max_prem = max(max_prem, settings.explosion_max_premium_inr)
    if premium < settings.min_option_premium_inr:
        return f"premium_below_{settings.min_option_premium_inr:.0f}"
    if premium > max_prem:
        return f"premium_above_{max_prem:.0f}"
    return "passed"
