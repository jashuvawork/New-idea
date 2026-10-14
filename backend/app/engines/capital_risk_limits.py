"""INR risk limits that follow the day's capital (CAPITAL_SCALED_RISK_LIMITS_ENABLED).

With the flag on, the operator sets one number per day — the book, via POST /api/capital or
FALLBACK_CAPITAL_INR — and every INR risk limit is that book × its ``*_capital_pct``.
With the flag off, the fixed ``*_inr`` settings apply unchanged.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings

RISK_LIMIT_PCT_FIELDS: dict[str, str] = {
    "daily_loss_stop_inr": "daily_loss_stop_capital_pct",
    "emergency_stop_inr": "emergency_stop_capital_pct",
    "max_risk_per_trade_inr": "max_risk_per_trade_capital_pct",
    "session_large_loss_pause_inr": "session_large_loss_pause_capital_pct",
}


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def capital_scaled_risk_limits_active(settings: Any = None) -> bool:
    s = settings or get_settings()
    return getattr(s, "capital_scaled_risk_limits_enabled", False) is True


def book_capital_inr(settings: Any = None, *, runtime: bool = True) -> float:
    """The day's book: operator capital when set (runtime), else the env sizing cap."""
    s = settings or get_settings()
    if runtime:
        from app.engines.capital_allocator import manual_capital_limit_inr

        manual = manual_capital_limit_inr()
        if manual is not None and manual > 0:
            return float(manual)
    return _num(getattr(s, "max_sizing_capital_inr", 0)) or _num(
        getattr(s, "fallback_capital_inr", 0)
    )


def risk_limit_inr(field: str, settings: Any = None, *, runtime: bool = True) -> float:
    s = settings or get_settings()
    fixed = _num(getattr(s, field, 0))
    pct_field = RISK_LIMIT_PCT_FIELDS.get(field)
    if pct_field is None or not capital_scaled_risk_limits_active(s):
        return fixed
    book = book_capital_inr(s, runtime=runtime)
    pct = _num(getattr(s, pct_field, 0))
    if book <= 0 or pct <= 0:
        return fixed
    return round(book * pct / 100.0, 2)


def daily_loss_budget_lot_cap(
    *,
    lots: int,
    lot_mult: int,
    stop_points: float,
    session_pnl_inr: float,
    settings: Any = None,
) -> tuple[int, dict[str, Any]]:
    """Largest lot count whose stop loss still fits what is left of the daily loss stop.

    Session profit does not widen the budget past one full daily stop, so a single
    all-in stop-out can never on its own carry the session through the daily loss stop.
    """
    s = settings or get_settings()
    if getattr(s, "entry_stop_daily_budget_cap_enabled", False) is not True:
        return int(lots), {}
    loss_stop = abs(risk_limit_inr("daily_loss_stop_inr", s))
    stop_pts = _num(stop_points)
    if loss_stop <= 0 or stop_pts <= 0 or lot_mult <= 0 or lots <= 0:
        return int(lots), {}
    remaining = min(loss_stop, loss_stop + _num(session_pnl_inr))
    frac = _num(getattr(s, "entry_stop_daily_budget_frac", 1.0)) or 1.0
    budget = max(0.0, remaining * max(0.0, min(1.0, frac)))
    risk_one = stop_pts * lot_mult
    fit = int(budget // risk_one)
    capped = max(0, min(int(lots), fit))
    return capped, {
        "dailyLossStopInr": round(loss_stop, 2),
        "remainingBudgetInr": round(remaining, 2),
        "budgetInr": round(budget, 2),
        "stopRiskPerLotInr": round(risk_one, 2),
        "requestedLots": int(lots),
        "cappedLots": capped,
        "requestedStopRiskInr": round(risk_one * int(lots), 2),
    }


def capital_risk_limits_summary(settings: Any = None) -> dict[str, Any]:
    s = settings or get_settings()
    return {
        "enabled": capital_scaled_risk_limits_active(s),
        "bookCapitalInr": book_capital_inr(s),
        "limitsInr": {f: risk_limit_inr(f, s) for f in RISK_LIMIT_PCT_FIELDS},
        "pcts": {f: _num(getattr(s, p, 0)) for f, p in RISK_LIMIT_PCT_FIELDS.items()},
    }
