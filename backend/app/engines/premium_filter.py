"""Option premium (LTP) band filter for tradeable analysis range."""

from app.config import get_settings


def premium_in_band(
    premium: float | None,
    *,
    mode: str = "default",
    peak_move_pct: float = 0.0,
) -> bool:
    """True when option LTP is within configured tradeable band."""
    if premium is None or premium <= 0:
        return False
    settings = get_settings()
    max_prem = settings.max_option_premium_inr
    if mode == "explosion" and settings.explosion_max_premium_inr > 0:
        max_prem = max(max_prem, settings.explosion_max_premium_inr)
    min_prem = settings.min_option_premium_inr
    if mode == "explosion":
        cheap_min = float(getattr(settings, "explosion_cheap_rip_min_premium_inr", 12.0) or 12.0)
        cheap_peak = float(getattr(settings, "explosion_cheap_rip_min_peak_pct", 28.0) or 28.0)
        if peak_move_pct >= cheap_peak and premium >= cheap_min:
            min_prem = min(min_prem, cheap_min)
    return min_prem <= premium <= max_prem


def premium_band_label() -> str:
    settings = get_settings()
    return f"₹{settings.min_option_premium_inr:.0f}–₹{settings.max_option_premium_inr:.0f}"


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
