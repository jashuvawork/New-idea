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
    # When a local base is known, maturity is measured from THAT base (15%+), not
    # day-session % — otherwise a post-dump V-bottom always looks "mature" from open.
    base_move = float(getattr(ict, "base_relative_move_pct", 0) or 0) if ict is not None else 0.0
    if (
        ict is not None
        and getattr(settings, "explosion_chase_use_local_base", True)
        and base_move > 0
    ):
        local_floor = float(
            getattr(settings, "explosion_local_base_entry_min_move_pct", 15.0) or 15.0
        )
        if base_move >= local_floor:
            return False, ""
        return True, f"immature_local_base_{base_move:.1f}%"

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


def _ict_structure_confirmed(ict: Any) -> bool:
    """True ICT structure — not displacement-only / sticky-tier noise."""
    if ict is None:
        return False
    if not bool(getattr(ict, "active", False)):
        return False
    if bool(getattr(ict, "flat_then_vertical", False)):
        return True
    if bool(getattr(ict, "mega_rip", False)):
        return True
    if bool(getattr(ict, "premium_fvg", False)) and (
        bool(getattr(ict, "volume_awakening", False))
        or bool(getattr(ict, "displacement", False))
    ):
        return True
    if bool(getattr(ict, "volume_awakening", False)) and bool(
        getattr(ict, "displacement", False)
    ):
        return True
    # Dump→V-bottom reclaim with heat + early local-base expansion.
    settings = get_settings()
    local_floor = float(
        getattr(settings, "explosion_local_base_entry_min_move_pct", 15.0) or 15.0
    )
    base_rel = float(getattr(ict, "base_relative_move_pct", 0) or 0)
    if (
        bool(getattr(ict, "local_swing_base", False))
        and base_rel >= local_floor
        and (
            bool(getattr(ict, "volume_awakening", False))
            or bool(getattr(ict, "displacement", False))
        )
    ):
        return True
    return False


def live_explosion_confirmation_blocked(
    explosion_event: Any,
    *,
    ict: Any = None,
    midday_chop: Optional[bool] = None,
    premium_capture: bool = False,
) -> tuple[bool, str]:
    """
    Hard-block wrong-timing explosions that look ELITE but lack live confirmation.

    Jul23 day book failures this stops:
    - NIFTY 23900 PE ELITE with v3=0.26 / ictPattern=watch (stale sticky tier)
    - NIFTY 23900 PE ELITE v3=2.35 displacement-only (no flat→vertical)
    - SENSEX 76200 PE midday displacement spike without structure

    Still allows: ICT flat→vertical with live heat (Jul23 76300 PE profile), and
    genuine volume-backed premium/afternoon captures (slow grinds, low velocity by
    design — e.g. NIFTY 24250 PE 1pm consolidation breakout).
    """
    settings = get_settings()
    if not getattr(settings, "explosion_live_confirm_enabled", True):
        return False, ""
    if explosion_event is None:
        return False, ""

    tier = str(getattr(explosion_event, "tier", "") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False, ""

    v3 = float(getattr(explosion_event, "velocity_3s", 0) or 0)
    v9 = float(getattr(explosion_event, "velocity_9s", 0) or 0)
    min_v3 = float(
        getattr(settings, "explosion_live_confirm_min_velocity_3s", 2.0) or 2.0
    )
    # Soft floor for confirmed ICT flat→vertical mid-burst (brief velocity dip).
    ict_min_v3 = float(
        getattr(settings, "explosion_live_confirm_ict_min_velocity_3s", 1.5) or 1.5
    )
    structure = _ict_structure_confirmed(ict)

    # Genuine premium/afternoon capture is a validated slow-grind path (in-window +
    # score + volume + consolidation + chart alignment). It is live-confirmed by that
    # classification, not by raw velocity — afternoon consolidation breakouts are slow
    # by design. Require a real volume surge (or ICT structure) so a structure-less,
    # low-volume displacement spike cannot ride this bypass.
    if premium_capture and getattr(
        settings, "explosion_live_confirm_premium_capture_bypass", True
    ):
        vol_surge = float(getattr(explosion_event, "volume_surge", 0) or 0)
        min_vol = float(
            getattr(settings, "explosion_live_confirm_premium_min_vol_surge", 1.3) or 1.3
        )
        if structure or vol_surge >= min_vol:
            return False, ""

    # 1) Stale / cooled live velocity — sticky ELITE alone is not enough.
    if structure:
        if v3 < ict_min_v3 and v9 < min_v3:
            return True, f"stale_live_velocity_v3_{v3:.2f}_ict"
    elif v3 < min_v3:
        return True, f"stale_live_velocity_v3_{v3:.2f}"

    # 2) Structure confirmation — displacement-only / watch must not enter.
    require_structure = bool(
        getattr(settings, "explosion_live_confirm_require_structure", True)
    )
    if require_structure and not structure:
        # Allow extreme hot velocity + real session rip without ICT object only
        # when both v3 and session move clear early-window floors.
        move = _session_peak_move(explosion_event)
        if ict is not None:
            move = max(move, float(getattr(ict, "session_move_pct", 0) or 0))
        early_min = float(
            getattr(settings, "explosion_early_window_min_move_pct", 28.0) or 28.0
        )
        hot_v3 = float(
            getattr(settings, "explosion_live_confirm_hot_velocity_3s", 8.0) or 8.0
        )
        # Midday chop: never allow structure-less entries (FOMO spikes).
        if midday_chop is None:
            midday_chop = _midday_chop_active()
        if midday_chop:
            return True, "midday_no_ict_structure"
        if not (v3 >= hot_v3 and move >= early_min):
            return True, "no_ict_structure_confirmation"

    return False, ""


def extended_session_chase_blocked(
    explosion_event: Any,
    *,
    ict: Any = None,
) -> tuple[bool, str]:
    """
    Hard-block EXPLOSIVE entries after the move is already mostly done.

    Prefer LOCAL BASE move (flat consolidation or dump→V-bottom swing low) when
    known — day-session % alone always looks like a chase after an earlier run-up
    (Jul23 SENSEX 76400 PE: +471% day-move at the 14:35 local base reclaim).

    Tradeable local window: entry_min (28%) … chase_max (70%). Outside that,
    either wait (too early — handled by immature) or block as local chase.
    """
    settings = get_settings()
    if not getattr(settings, "explosion_extended_chase_block_enabled", True):
        return False, ""
    if explosion_event is None:
        return False, ""

    move = _session_peak_move(explosion_event)
    if ict is not None:
        move = max(move, float(getattr(ict, "session_move_pct", 0) or 0))

    base_move = float(getattr(ict, "base_relative_move_pct", 0) or 0) if ict is not None else 0.0
    if (
        ict is not None
        and getattr(settings, "explosion_chase_use_local_base", True)
        and base_move > 0
    ):
        # Hard ceiling from local base (default 40%). Soft 55% only shrinks size.
        local_max = float(
            getattr(settings, "explosion_local_base_chase_max_move_pct", 40.0) or 40.0
        )
        # Inclusive ceiling: block only once past 40% from the local launch.
        if base_move > local_max:
            return True, f"explosion_extended_chase_local_{base_move:.0f}%"
        # Local base still inside the tradeable window — never block on day %.
        return False, ""

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

    # Legacy base-relative bypass when local-primary path is off / no base_move.
    if (
        ict is not None
        and getattr(settings, "ict_base_relative_chase_bypass_enabled", True)
        and bool(getattr(ict, "flat_then_vertical", False))
        and bool(getattr(ict, "active", False))
        and (
            bool(getattr(ict, "volume_awakening", False))
            or bool(getattr(ict, "displacement", False))
        )
    ):
        base_max = float(
            getattr(settings, "ict_base_relative_chase_max_move_pct", 55.0) or 55.0
        )
        abs_cap = float(
            getattr(settings, "ict_base_relative_chase_abs_move_cap_pct", 160.0) or 160.0
        )
        ignore_abs = bool(
            getattr(settings, "ict_base_relative_ignore_abs_cap", True)
        )
        if 0 < base_move <= base_max and (ignore_abs or move <= abs_cap):
            return False, ""

    return True, f"explosion_extended_chase_{move:.0f}%"


def cap_extended_chase_lots(lots: int, explosion_event: Any, *, ict: Any = None) -> int:
    """Shrink size in the soft extended zone; hard-cap all explosion size."""
    settings = get_settings()
    hard_cap = int(getattr(settings, "explosion_hard_lot_cap", 10) or 10)
    lots = min(max(1, lots), hard_cap)
    move = _session_peak_move(explosion_event)
    base_move = float(getattr(ict, "base_relative_move_pct", 0) or 0) if ict is not None else 0.0
    base_max = float(
        getattr(settings, "ict_base_relative_chase_max_move_pct", 55.0) or 55.0
    )
    # Local / flat base still inside the soft early window → full size.
    if ict is not None and 0 < base_move <= base_max:
        return lots
    # Soft-cap using local base when day-move is misleadingly large.
    if (
        ict is not None
        and getattr(settings, "explosion_chase_use_local_base", True)
        and base_move > base_max
    ):
        soft_cap = int(getattr(settings, "explosion_extended_soft_lot_cap", 6) or 6)
        return min(lots, soft_cap)
    # ICT flat→vertical still inside base-relative early window keeps full size.
    if (
        ict is not None
        and bool(getattr(ict, "flat_then_vertical", False))
        and bool(getattr(ict, "active", False))
        and 0 < base_move <= base_max
    ):
        return lots
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


def _regime_chopish(snap: SymbolSnapshot) -> bool:
    regime = str(snap.regime.value if hasattr(snap.regime, "value") else snap.regime or "").upper()
    if regime in ("CHOP", "RANGE_BOUND"):
        return True
    chart = snap.spotChart
    if chart is None:
        return False
    mom = abs(float(getattr(chart, "momentum5Pct", 0) or 0))
    strength = float(getattr(chart, "trendStrength", 100) or 100)
    return mom < 0.25 and strength < 45


def _midday_chop_active() -> bool:
    """Time-window chop — independent of scalp-block toggle."""
    try:
        from app.engines.session_timing import _minutes_now
        from app.services.upstox import get_market_phase

        if get_market_phase() != "LIVE_MARKET":
            return False
        settings = get_settings()
        current = _minutes_now()
        start = settings.midday_chop_start_hour * 60 + settings.midday_chop_start_minute
        end = settings.midday_chop_end_hour * 60 + settings.midday_chop_end_minute
        return start <= current < end
    except Exception:
        return False


def _or_position(snap: SymbolSnapshot) -> str:
    chart = snap.spotChart
    if chart is None:
        return ""
    return str(getattr(chart, "orPosition", "") or "").upper()


def _premium_mom_flat(premium_chart: Any) -> bool:
    """Live premium already cooled — FOMO fill risk (Jul20 mom3/5=0, NEUTRAL)."""
    if premium_chart is None:
        return False
    settings = get_settings()
    max_mom = float(
        getattr(settings, "fake_explosion_trap_max_premium_mom_pct", 0.15) or 0.15
    )
    if isinstance(premium_chart, dict):
        mom3 = float(premium_chart.get("momentum3Pct") or 0)
        mom5 = float(premium_chart.get("momentum5Pct") or 0)
        direction = str(premium_chart.get("direction") or "").upper()
    else:
        mom3 = float(getattr(premium_chart, "momentum3Pct", 0) or 0)
        mom5 = float(getattr(premium_chart, "momentum5Pct", 0) or 0)
        direction = str(getattr(premium_chart, "direction", "") or "").upper()
    flat_mom = abs(mom3) <= max_mom and abs(mom5) <= max_mom
    return flat_mom or direction == "NEUTRAL"


def _post_small_win(state: Any) -> tuple[bool, dict[str, Any]]:
    """Last closed trade was a small green — size-up FOMO risk unless trail-proved."""
    settings = get_settings()
    meta: dict[str, Any] = {}
    if state is None:
        return False, meta
    try:
        from app.engines.pretrade_validator import collect_session_trades
    except Exception:
        return False, meta

    lookback = int(getattr(settings, "fake_explosion_trap_post_win_lookback", 1) or 1)
    trades = collect_session_trades(state)
    if not trades:
        return False, meta
    recent = trades[-lookback:]
    last = recent[-1]
    pnl = float(getattr(last, "pnl_inr", 0) or 0)
    reason = str(getattr(last, "exit_reason", "") or "").lower()
    max_pnl = float(
        getattr(settings, "fake_explosion_trap_post_win_max_pnl_inr", 3000.0) or 3000.0
    )
    meta = {
        "lastPnlInr": round(pnl, 2),
        "lastExitReason": reason,
    }
    if pnl <= 0:
        return False, meta
    # Trail / runner / target exits proved the move — allow normal size.
    if any(tok in reason for tok in ("trail", "runner", "target", "tp")):
        if pnl >= max_pnl:
            return False, meta
        # Small trail win still clamps — Jul20 +₹446 trail then 49-lot trap.
        meta["postSmallWin"] = True
        meta["trailProvedButSmall"] = True
        return True, meta
    if pnl < max_pnl:
        meta["postSmallWin"] = True
        return True, meta
    return False, meta


def detect_fake_explosion_trap(
    candidate: Any,
    snap: SymbolSnapshot,
    *,
    state: Any = None,
    premium_chart: Any = None,
    ict: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Detect FOMO / fake-rip explosion traps (Jul20 NIFTY 24300 CE).

    Returns (should_block, reason, meta).
    meta.action is "block" or "cut_size"; lotCap / psychologyEscalate when cutting.
    """
    settings = get_settings()
    meta: dict[str, Any] = {"fakeExplosionTrap": False}
    if not getattr(settings, "fake_explosion_trap_enabled", True):
        return False, "ok", meta
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "ok", meta

    event = getattr(candidate, "explosion_event", None)
    tier = str(
        getattr(event, "tier", None)
        or getattr(candidate, "tier", "")
        or ""
    ).upper()
    v3 = float(getattr(event, "velocity_3s", 0) or 0) if event else 0.0
    move = _session_peak_move(event)
    if ict is not None:
        move = max(move, float(getattr(ict, "session_move_pct", 0) or 0))

    chop_regime = _regime_chopish(snap)
    midday = _midday_chop_active()
    chopish = chop_regime or midday
    elite_hot = tier in ("ELITE", "EXPLODING") and (
        v3 >= 2.0 or tier == "ELITE"
    )
    # "Extended" = chase territory past the early base window — NOT the entry min.
    # Using min_move (28%) here hard-blocked Jul15 ATM ELITE winners (32–45% moves).
    min_move = float(
        getattr(settings, "fake_explosion_trap_min_session_move_pct", 28.0) or 28.0
    )
    extended_move = float(
        getattr(settings, "fake_explosion_trap_extended_move_pct", 0) or 0
    )
    if extended_move <= 0:
        extended_move = float(
            getattr(settings, "explosion_early_window_max_move_pct", 55.0) or 55.0
        )
    session_extended = move >= extended_move
    in_base_window = min_move <= move < extended_move
    premium_flat = _premium_mom_flat(premium_chart)

    depth, money, atm = _strike_depth(candidate.side, float(candidate.strike), snap)
    from app.engines.moneyness import resolve_preferred_moneyness

    preferred = resolve_preferred_moneyness(
        "explosion", snap, candidate_score=float(getattr(candidate, "score", 0) or 0),
        side=candidate.side,
    )
    or_pos = _or_position(snap)
    otm_inside_or = (
        getattr(settings, "fake_explosion_trap_otm_requires_or_breakout", True)
        and money == "OTM"
        and preferred == "ATM"
        and or_pos == "INSIDE"
    )
    post_win, post_meta = _post_small_win(state)
    meta.update(post_meta)

    flags: list[str] = []
    if chop_regime:
        flags.append("chop_regime")
    if midday:
        flags.append("midday_chop")
    if elite_hot:
        flags.append("elite_hot")
    if session_extended:
        flags.append("session_extended")
    if in_base_window:
        flags.append("base_window")
    if premium_flat:
        flags.append("premium_flat")
    if otm_inside_or:
        flags.append("otm_inside_or")
    if post_win:
        flags.append("post_small_win")

    meta.update({
        "fakeExplosionTrap": False,
        "conflictFlags": flags,
        "conflictCount": len(flags),
        "explosionTier": tier,
        "sessionMovePct": round(move, 2),
        "velocity3s": round(v3, 2),
        "moneyness": money,
        "preferredMoneyness": preferred,
        "orPosition": or_pos,
        "atmStrike": atm,
        "strikeStepsFromAtm": depth,
        "chopRegime": chop_regime,
        "middayChop": midday,
        "premiumFlat": premium_flat,
    })

    if not flags:
        return False, "ok", meta

    lot_cap = int(
        getattr(settings, "fake_explosion_trap_chop_elite_lot_cap", 6) or 6
    )
    post_cap = int(
        getattr(settings, "fake_explosion_trap_post_win_lot_cap", 8) or 8
    )
    action = ""
    reason = ""
    psych = ""

    # Hard block: classic fake rip — extension already printed, premium cooled,
    # or OTM inside OR on chop with elite narrative.
    hard_block = False
    if getattr(settings, "fake_explosion_trap_block_on_conflict", True):
        if premium_flat and session_extended and (chopish or elite_hot):
            hard_block = True
            reason = "fake_explosion_trap_premium_flat_extension"
        elif otm_inside_or and chopish and elite_hot:
            hard_block = True
            reason = "fake_explosion_trap_otm_inside_or"
        elif (
            chopish
            and elite_hot
            and session_extended
            and otm_inside_or
            and post_win
        ):
            hard_block = True
            reason = "fake_explosion_trap_fomo_stack"
        else:
            min_flags = int(
                getattr(settings, "fake_explosion_trap_min_conflict_flags", 3) or 3
            )
            # Require chop + elite + at least one structural risk (extension/OTM/flat/post-win)
            structural = {
                "session_extended",
                "premium_flat",
                "otm_inside_or",
                "post_small_win",
            }
            if (
                len(flags) >= min_flags
                and (chop_regime or midday)
                and elite_hot
                and structural.intersection(flags)
            ):
                hard_block = True
                reason = "fake_explosion_trap_conflict"

    if hard_block:
        meta.update({
            "fakeExplosionTrap": True,
            "action": "block",
            "psychologyEscalate": "FOMO" if post_win else "OVERCONFIDENCE",
        })
        return True, reason, meta

    # Midday/chop + elite narrative without ICT structure → hard block.
    # Soft lot-cap alone still let Jul23 displacement spikes through.
    if (
        getattr(settings, "fake_explosion_trap_midday_require_structure", True)
        and chopish
        and elite_hot
        and not _ict_structure_confirmed(ict)
    ):
        meta.update({
            "fakeExplosionTrap": True,
            "action": "block",
            "psychologyEscalate": "FOMO" if post_win else "OVERCONFIDENCE",
            "structureMissing": True,
        })
        return True, "fake_explosion_trap_midday_no_structure", meta

    # Soft cut: chop+elite full-size forbidden; post-small-win clamp.
    # Exception: ATM/ITM inside the early base window (28–55%) is the capture
    # profile — soft-cutting those to 6 lots is how Jul23 76300 PE high-conv died.
    skip_soft = bool(
        getattr(settings, "fake_explosion_trap_skip_soft_cut_base_window", True)
    ) and in_base_window and money in ("ATM", "ITM") and not session_extended and not otm_inside_or

    cut = False
    if chopish and elite_hot and not skip_soft:
        cut = True
        action = "cut_size"
        reason = "fake_explosion_trap_chop_elite_size"
        lot_cap = min(lot_cap, int(
            getattr(settings, "fake_explosion_trap_chop_elite_lot_cap", 6) or 6
        ))
        psych = "OVERCONFIDENCE"
    if post_win and not skip_soft:
        cut = True
        action = "cut_size"
        reason = reason or "fake_explosion_trap_post_win_size"
        lot_cap = min(lot_cap, post_cap) if chopish and elite_hot else post_cap
        psych = "FOMO" if psych != "OVERCONFIDENCE" else "OVERCONFIDENCE"

    if cut:
        if getattr(settings, "fake_explosion_trap_psychology_escalate", True):
            # Conflict stack escalates label even on soft cut.
            conflict_heavy = len(flags) >= 3 and chopish and elite_hot
            if conflict_heavy and post_win:
                psych = "FOMO"
            elif conflict_heavy:
                psych = psych or "OVERCONFIDENCE"
        meta.update({
            "fakeExplosionTrap": True,
            "action": action,
            "lotCap": lot_cap,
            "psychologyEscalate": psych or None,
        })
        # Soft cut does not block entry — open path applies lotCap.
        return False, reason, meta

    return False, "ok", meta


def cap_fake_explosion_trap_lots(
    lots: int,
    trap_meta: Optional[dict[str, Any]],
    *,
    bypass_soft_cap: bool = False,
) -> int:
    """Apply trap lot cap after good-day max-lot force (Jul20 49-lot hole)."""
    if not trap_meta or not trap_meta.get("fakeExplosionTrap"):
        return lots
    if trap_meta.get("action") == "block":
        return 0
    # High-conviction / elevated ATM base rips keep max lots; hard block still wins.
    if bypass_soft_cap and trap_meta.get("action") == "cut_size":
        return lots
    cap = trap_meta.get("lotCap")
    if cap is None:
        return lots
    return min(max(0, lots), int(cap))
