"""Option premium (LTP) band filter for tradeable analysis range."""

from typing import Any

from app.config import Settings, get_settings


def _positive_premium_cap(settings: Any, key: str) -> float | None:
    raw = getattr(settings, key, None)
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            return None
    else:
        return None
    return value if value > 0 else None


def explosion_tradeable_max_premium_inr(settings: Settings | None = None) -> float:
    """Hard ceiling for explosion entry/scan — min of configured caps (default ₹450)."""
    s = settings or get_settings()
    caps: list[float] = []
    for key in (
        "max_option_premium_inr",
        "explosion_max_premium_inr",
        "explosion_ict_max_premium_inr",
    ):
        cap = _positive_premium_cap(s, key)
        if cap is not None:
            caps.append(cap)
    if not caps:
        return 450.0
    return min(caps)


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
        max_prem = min(max_prem, settings.explosion_max_premium_inr)
    max_prem = min(max_prem, explosion_tradeable_max_premium_inr(settings))
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
        # ICT mid-rip uses the same hard ceiling — never above tradeable max.
        ict_ceil = _positive_premium_cap(settings, "explosion_ict_max_premium_inr")
        if ict_ceil is not None and peak_move_pct >= 28.0:
            max_prem = min(max_prem, ict_ceil, explosion_tradeable_max_premium_inr(settings))
    return min_prem <= premium <= max_prem


def premium_band_label() -> str:
    settings = get_settings()
    hi = explosion_tradeable_max_premium_inr(settings)
    return f"₹{settings.min_option_premium_inr:.0f}–₹{hi:.0f}"


def premium_reject_reason(premium: float | None, *, mode: str = "default") -> str:
    if premium is None or premium <= 0:
        return "missing_premium"
    settings = get_settings()
    max_prem = explosion_tradeable_max_premium_inr(settings)
    if mode != "explosion":
        max_prem = min(max_prem, float(settings.max_option_premium_inr or max_prem))
    if premium < settings.min_option_premium_inr:
        return f"premium_below_{settings.min_option_premium_inr:.0f}"
    if premium > max_prem:
        return f"premium_above_{max_prem:.0f}"
    return "passed"
