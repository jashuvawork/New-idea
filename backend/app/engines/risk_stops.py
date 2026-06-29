"""Position-aware stop loss helpers."""

from app.config import get_settings


def effective_emergency_stop_inr(
    lots: int,
    lot_multiplier: int,
    stop_points: float,
) -> float:
    """
    INR emergency cap — never wider than the point-stop budget.
    Prevents 60-lot trades from bleeding ₹20K+ when SL is ~2.5pt.
    """
    settings = get_settings()
    if lots <= 0 or lot_multiplier <= 0 or stop_points <= 0:
        return settings.emergency_stop_inr
    point_budget = lots * lot_multiplier * stop_points
    if settings.emergency_stop_scale_with_position:
        return min(settings.emergency_stop_inr, point_budget)
    return settings.emergency_stop_inr
