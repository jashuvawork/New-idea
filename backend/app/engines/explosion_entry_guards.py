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


def _session_peak_move(explosion_event: Any) -> float:
    if explosion_event is None:
        return 0.0
    daily = float(getattr(explosion_event, "daily_move_pct", 0) or 0)
    peak = float(getattr(explosion_event, "peak_move_pct", 0) or 0)
    return max(daily, peak)


def immature_explosion_blocked(
    explosion_event: Any,
    *,
    ict: Any = None,
) -> tuple[bool, str]:
    """
    Block hot-velocity / displacement noise before a real premium rip prints.

    Jul20 NIFTY CALL losses entered at +0.8% / +1.4% session move with
    ictPattern=displacement — not a base→vertical. Require a minimum session
    move unless true flat→vertical early ICT is already confirmed.
    """
    settings = get_settings()
    if not getattr(settings, "explosion_immature_block_enabled", True):
        return False, ""
    if explosion_event is None:
        return False, ""

    move = _session_peak_move(explosion_event)
    if ict is not None:
        move = max(move, float(getattr(ict, "session_move_pct", 0) or 0))

    min_move = float(
        getattr(settings, "explosion_immature_min_session_move_pct", 22.0) or 22.0
    )
    early_min = float(
        getattr(settings, "ict_early_vertical_min_session_move_pct", 28.0) or 28.0
    )
    if move >= min_move:
        return False, ""

    # Only exception: confirmed flat→vertical already at early ICT floor.
    if (
        ict is not None
        and bool(getattr(ict, "active", False))
        and bool(getattr(ict, "flat_then_vertical", False))
        and (
            bool(getattr(ict, "volume_awakening", False))
            or bool(getattr(ict, "displacement", False))
        )
        and move >= early_min
    ):
        return False, ""

    return True, f"immature_explosion_move_{move:.1f}%"


def extended_session_chase_blocked(
    explosion_event: Any,
    *,
    ict: Any = None,
) -> tuple[bool, str]:
    """
    Hard-block EXPLOSIVE entries after the move is already mostly done.

    Hot velocity at +90% is still a chase (Jul17 NIFTY 24250 CE) — not a start.
    Early flat→vertical inside the early window remains allowed.
    """
    settings = get_settings()
    if not getattr(settings, "explosion_extended_chase_block_enabled", True):
        return False, ""
    if explosion_event is None:
        return False, ""

    move = _session_peak_move(explosion_event)
    if ict is not None:
        move = max(move, float(getattr(ict, "session_move_pct", 0) or 0))

    hard = float(getattr(settings, "explosion_extended_chase_min_move_pct", 70.0) or 70.0)
    early_max = float(getattr(settings, "explosion_early_window_max_move_pct", 55.0) or 55.0)
    if move < hard:
        return False, ""

    # Keep true early base-break ICT inside the early window only.
    # (premium_fvg chases at +91% stay blocked — that is the PF killer.)
    if (
        ict is not None
        and bool(getattr(ict, "flat_then_vertical", False))
        and bool(getattr(ict, "active", False))
        and move <= early_max
    ):
        return False, ""

    return True, f"explosion_extended_chase_{move:.0f}%"


def cap_extended_chase_lots(lots: int, explosion_event: Any) -> int:
    """Shrink size in the soft extended zone; hard-cap all explosion size."""
    settings = get_settings()
    hard_cap = int(getattr(settings, "explosion_hard_lot_cap", 10) or 10)
    lots = min(max(1, lots), hard_cap)
    move = _session_peak_move(explosion_event)
    soft = float(getattr(settings, "explosion_extended_soft_min_move_pct", 50.0) or 50.0)
    if move >= soft:
        soft_cap = int(getattr(settings, "explosion_extended_soft_lot_cap", 6) or 6)
        lots = min(lots, soft_cap)
    return lots


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


def detect_faded_vertical_rip(
    explosion_event: Any,
    snap: Optional[SymbolSnapshot] = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Peak rip already happened but live velocity cooled — same pattern as cheap OTM
    explosion chase on worst days. Take with caution (smaller size, tighter stop).
    """
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not getattr(settings, "explosion_faded_rip_caution_enabled", True):
        return False, meta
    if explosion_event is None:
        return False, meta

    tier = str(getattr(explosion_event, "tier", "") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False, meta

    v3 = float(getattr(explosion_event, "velocity_3s", 0) or 0)
    peak = float(getattr(explosion_event, "peak_move_pct", 0) or 0)
    min_peak = float(getattr(settings, "explosion_faded_rip_min_peak_pct", 35.0) or 35.0)
    max_live = float(getattr(settings, "explosion_faded_rip_max_live_velocity_3s", 0.5) or 0.5)
    if peak < min_peak or v3 > max_live:
        return False, meta

    from app.engines.explosion_detector import retained_peak_velocity_3s
    from app.models.schemas import Side

    side = getattr(explosion_event, "side", Side.CALL)
    peak_v3 = retained_peak_velocity_3s(
        str(getattr(explosion_event, "symbol", "") or ""),
        float(getattr(explosion_event, "strike", 0) or 0),
        side,
    )
    if peak_v3 < float(settings.worst_day_breakout_min_velocity_3s):
        return False, meta

    meta = {
        "fadedVerticalRip": True,
        "fadedRipCaution": True,
        "peakMovePct": round(peak, 2),
        "liveVelocity3s": round(v3, 2),
        "peakVelocity3s": round(peak_v3, 2),
        "cautionLotCap": int(getattr(settings, "explosion_faded_rip_lot_cap", 8) or 8),
    }
    if snap is not None:
        depth, money, atm = _strike_depth(
            side,
            float(getattr(explosion_event, "strike", 0) or 0),
            snap,
        )
        meta["moneyness"] = money
        meta["strikeStepsFromAtm"] = depth
        meta["atmStrike"] = atm
    return True, meta


def cap_faded_rip_lots(lots: int) -> int:
    settings = get_settings()
    cap = int(getattr(settings, "explosion_faded_rip_lot_cap", 8) or 8)
    return min(max(1, lots), cap)


def faded_rip_stop_multiplier() -> float:
    settings = get_settings()
    return float(getattr(settings, "explosion_faded_rip_tighter_stop_mult", 0.85) or 0.85)


def is_faded_rip_caution_trade(trade: Any) -> bool:
    """Explosion-only — faded vertical rip entered with caution sizing."""
    from app.models.schemas import StrategyType

    ctx = getattr(trade, "entryContext", None) or {}
    if not (ctx.get("fadedRipCaution") or ctx.get("fadedVerticalRip")):
        return False
    strategy = getattr(trade, "strategyType", None)
    if strategy == StrategyType.EXPLOSIVE:
        return True
    return str(ctx.get("selectionMode") or "").lower() == "explosion"


def _faded_rip_chart_aligned_hold(trade: Any) -> bool:
    """Strong session rip + chart flipped aligned — keep faded-rip runner."""
    settings = get_settings()
    min_move = float(getattr(settings, "faded_rip_no_green_hold_min_session_move_pct", 60.0) or 60.0)
    ctx = getattr(trade, "entryContext", None) or {}
    session_move = max(
        float(ctx.get("dailyMovePct") or ctx.get("openPremiumMove") or 0),
        float(ctx.get("peakMovePct") or 0),
        float(ctx.get("sessionMovePct") or 0),
    )
    if session_move < min_move:
        return False

    from app.models.schemas import Side

    side = getattr(trade, "side", Side.CALL)
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    for chart in (
        (ctx.get("executionChart") or {}).get("indexChart") or {},
        (ctx.get("executionChart") or {}).get("snapshotChart") or {},
    ):
        direction = str(chart.get("direction", "NEUTRAL")).upper()
        if side_val == "CALL" and direction == "BULLISH":
            return True
        if side_val == "PUT" and direction == "BEARISH":
            return True
    breadth = str(ctx.get("breadth") or "").upper()
    if side_val == "CALL" and breadth == "BULLISH":
        return True
    if side_val == "PUT" and breadth == "BEARISH":
        return True
    return False


def faded_rip_no_green_exit_reason(
    trade: Any,
    *,
    hold_seconds: float,
    best_points: float,
) -> Optional[str]:
    """Exit explosive fade-chase if never went green within the caution window."""
    settings = get_settings()
    if not getattr(settings, "explosion_faded_rip_no_green_exit_enabled", True):
        return None
    if not is_faded_rip_caution_trade(trade):
        return None
    if _faded_rip_chart_aligned_hold(trade):
        return None
    limit = int(getattr(settings, "explosion_faded_rip_no_green_seconds", 60) or 60)
    min_green = float(getattr(settings, "explosion_faded_rip_min_green_points", 0.5) or 0.5)
    if hold_seconds >= limit and best_points < min_green:
        return "explosion_faded_rip_no_green"
    return None
