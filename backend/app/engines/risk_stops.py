"""Position-aware stop loss helpers."""

from app.config import get_settings


def _strict_bool(value, default: bool = False) -> bool:
    """Only real bools count — MagicMock attrs must not flip live-hold mode."""
    if isinstance(value, bool):
        return value
    return default


def live_hold_to_structural_sl(settings=None) -> bool:
    """Live mode: skip INR force-stops / scratch exits — ride to structural SL only."""
    s = settings or get_settings()
    if not _strict_bool(getattr(s, "enable_live_trading", False)):
        return False
    return _strict_bool(getattr(s, "live_hold_to_structural_sl", True), True)


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
    if not settings.emergency_stop_enabled:
        return float("inf")
    if lots <= 0 or lot_multiplier <= 0 or stop_points <= 0:
        return settings.emergency_stop_inr
    point_budget = lots * lot_multiplier * stop_points
    if settings.emergency_stop_scale_with_position:
        return min(settings.emergency_stop_inr, point_budget)
    return settings.emergency_stop_inr
