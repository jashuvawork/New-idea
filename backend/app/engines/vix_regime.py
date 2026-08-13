"""India VIX regime — day-type context for explosion capture vs chop/theta days.

VIX is the single most useful macro input for F&O:
- Rising / elevated VIX  -> volatility EXPANSION: explosions & big directional moves
  are likely -> trade normally / be willing to hold runners.
- Falling / low VIX       -> CONTRACTION: theta-grind chop days where premium buying
  bleeds -> stand down or scalp only (this is where the chop losses come from).
- VIX spike (fast jump)   -> event risk -> size down.

This module is pure classification logic. It is INERT until a VIX value is supplied
(via the snapshot or a fetch hook), so it can never break the live path. Wire a real
India VIX feed (Upstox `NSE_INDEX|India VIX`) into `vix_value` to activate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.config import get_settings


@dataclass(frozen=True)
class VixRegime:
    value: float = 0.0
    available: bool = False
    level: str = "UNKNOWN"     # CALM | NORMAL | ELEVATED | HIGH
    trend: str = "FLAT"        # RISING | FALLING | FLAT
    regime: str = "NORMAL"     # EXPANSION | CONTRACTION | NORMAL
    posture: str = "NORMAL"    # AGGRESSIVE | NORMAL | SIZE_DOWN | STAND_DOWN


def classify_vix_regime(
    vix_value: Optional[float],
    *,
    vix_reference: Optional[float] = None,
) -> VixRegime:
    """Classify the India VIX level + trend into a trading posture.

    ``vix_reference`` is a smoothing baseline (e.g. an EMA or prior session close) used
    to judge RISING/FALLING; when absent, trend is FLAT.
    """
    settings = get_settings()
    if not bool(getattr(settings, "india_vix_enabled", True)):
        return VixRegime()
    try:
        vix = float(vix_value) if vix_value is not None else 0.0
    except (TypeError, ValueError):
        vix = 0.0
    if vix <= 0:
        return VixRegime()

    calm = float(getattr(settings, "india_vix_calm_max", 11.0) or 11.0)
    normal = float(getattr(settings, "india_vix_normal_max", 14.0) or 14.0)
    elevated = float(getattr(settings, "india_vix_elevated_max", 20.0) or 20.0)
    if vix < calm:
        level = "CALM"
    elif vix < normal:
        level = "NORMAL"
    elif vix < elevated:
        level = "ELEVATED"
    else:
        level = "HIGH"

    rise = float(getattr(settings, "india_vix_rising_pct", 0.03) or 0.03)
    trend = "FLAT"
    if vix_reference and vix_reference > 0:
        if vix >= vix_reference * (1.0 + rise):
            trend = "RISING"
        elif vix <= vix_reference * (1.0 - rise):
            trend = "FALLING"

    spike = float(getattr(settings, "india_vix_spike_pct", 0.10) or 0.10)
    spiking = bool(vix_reference and vix_reference > 0 and vix >= vix_reference * (1.0 + spike))

    # Regime: expansion when vol is building; contraction when bleeding on a low base.
    if level in ("ELEVATED", "HIGH") and trend in ("RISING", "FLAT"):
        regime = "EXPANSION"
    elif level in ("CALM", "NORMAL") and trend in ("FALLING", "FLAT"):
        regime = "CONTRACTION"
    else:
        regime = "NORMAL"

    if spiking and level == "HIGH":
        posture = "SIZE_DOWN"          # event risk — protect capital
    elif regime == "EXPANSION":
        posture = "AGGRESSIVE"         # explosion-friendly
    elif level == "CALM" and trend != "RISING":
        posture = "STAND_DOWN"         # dead theta-grind chop
    else:
        posture = "NORMAL"

    return VixRegime(
        value=round(vix, 2), available=True, level=level, trend=trend,
        regime=regime, posture=posture,
    )


def vix_size_multiplier(snap: Any) -> tuple[float, dict[str, Any]]:
    """Day-type lot multiplier from the India VIX regime + an observation context dict.

    Default is a no-op (multiplier 1.0) — the caller only APPLIES it when
    vix_regime_sizing_enabled is true. The context is always returned so the regime and
    the *would-be* multiplier can be recorded on every trade for validation before it
    influences sizing. Expansion = normal size; calm/contraction and VIX spikes shrink.
    """
    settings = get_settings()
    r = vix_regime_from_snapshot(snap)
    ctx: dict[str, Any] = {
        "available": r.available,
        "value": r.value,
        "level": r.level,
        "trend": r.trend,
        "regime": r.regime,
        "posture": r.posture,
        "multiplier": 1.0,
        "applied": False,
    }
    if not r.available:
        return 1.0, ctx
    posture_mult = {
        "AGGRESSIVE": float(getattr(settings, "vix_size_mult_expansion", 1.0) or 1.0),
        "NORMAL": 1.0,
        "SIZE_DOWN": float(getattr(settings, "vix_size_mult_size_down", 0.5) or 0.5),
        "STAND_DOWN": float(getattr(settings, "vix_size_mult_stand_down", 0.6) or 0.6),
    }
    mult = posture_mult.get(r.posture, 1.0)
    ctx["multiplier"] = round(mult, 3)
    return mult, ctx


def vix_regime_from_snapshot(snap: Any) -> VixRegime:
    """Best-effort VIX regime from a snapshot that may carry an ``indiaVix`` value.

    Returns an inert (available=False) regime when no VIX is present — safe no-op until a
    real feed is wired, so callers can treat 'not available' as 'no VIX opinion'.
    """
    if snap is None:
        return VixRegime()
    vix = getattr(snap, "indiaVix", None)
    ref = getattr(snap, "indiaVixRef", None)
    return classify_vix_regime(vix, vix_reference=ref)
