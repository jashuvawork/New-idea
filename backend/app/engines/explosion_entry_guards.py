"""Explosion entry guards — OTM depth cap, peak-chase block, MACD alignment."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.moneyness import _depth_steps, atm_strike, classify_moneyness
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _strike_depth(
    side: Side | str,
    strike: float,
    snap: SymbolSnapshot,
) -> tuple[int, str, float]:
    spot = float(snap.spot or 0)
    symbol = snap.symbol.upper()
    atm = float(snap.atmStrike or atm_strike(spot, symbol))
    money = classify_moneyness(side, strike, spot, symbol=symbol, atm=atm)
    depth = _depth_steps(side, strike, spot, symbol, atm)
    return depth, money, atm


def check_all_in_moneyness_cap(
    side: Side | str,
    strike: float,
    snap: SymbolSnapshot,
) -> tuple[bool, str, dict[str, Any]]:
    """Hard cap OTM depth — all-in bypass cannot skip this."""
    settings = get_settings()
    depth, money, atm = _strike_depth(side, strike, snap)
    meta = {
        "moneyness": money,
        "strikeStepsFromAtm": depth,
        "atmStrike": atm,
        "allInOtmCap": settings.extreme_all_in_max_otm_steps,
    }
    if money != "OTM":
        return True, "ok", meta
    if depth > settings.extreme_all_in_max_otm_steps:
        return False, f"all_in_otm_too_deep_{depth}", meta
    return True, "ok", meta


def check_peak_chase_entry(
    candidate: Any,
    explosion_event: Any,
    snap: SymbolSnapshot,
) -> tuple[bool, str]:
    """Block chasing deep OTM premium rips near local top."""
    settings = get_settings()
    if not settings.explosion_peak_chase_guard_enabled:
        return True, "ok"
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return True, "ok"

    depth, money, _ = _strike_depth(candidate.side, float(candidate.strike), snap)
    if money != "OTM" or depth <= settings.explosion_peak_chase_max_otm_steps:
        return True, "ok"

    v3 = v9 = daily = peak = 0.0
    if explosion_event is not None:
        v3 = float(getattr(explosion_event, "velocity_3s", 0) or 0)
        v9 = float(getattr(explosion_event, "velocity_9s", 0) or 0)
        daily = float(getattr(explosion_event, "daily_move_pct", 0) or 0)
        peak = float(getattr(explosion_event, "peak_move_pct", 0) or 0)

    mom_thresh = settings.explosion_peak_chase_min_premium_mom_pct
    hot = (
        v3 >= mom_thresh
        or v9 >= mom_thresh * 1.2
        or daily >= settings.explosion_peak_chase_min_session_move_pct
        or peak >= settings.explosion_peak_chase_min_session_move_pct
    )
    if hot:
        return False, f"explosion_peak_chase_deep_otm_{depth}"
    return True, "ok"


def check_explosion_macd_alignment(
    side: Side | str,
    snap: SymbolSnapshot,
) -> tuple[bool, str]:
    """Require MACD bias to align with explosion side (no bearish MACD CALLs)."""
    settings = get_settings()
    if not settings.explosion_macd_alignment_required:
        return True, "ok"

    chart = snap.spotChart
    if not chart:
        return True, "ok"

    macd_bias = str(chart.macdBias or "NEUTRAL").upper()
    side_val = _side_val(side)

    if side_val == "CALL" and macd_bias == "BEARISH":
        return False, "explosion_macd_bearish_blocks_call"
    if side_val == "PUT" and macd_bias == "BULLISH":
        return False, "explosion_macd_bullish_blocks_put"
    return True, "ok"
