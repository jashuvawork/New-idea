"""Worst-day defensive ITM fade + alternate-index quick scalps."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.premium_filter import premium_in_band, premium_reject_reason
from app.engines.quick_sideways import (
    _collect_itm_strike_candidates,
    _micro_velocity,
    _pick_side,
    check_quick_sideways_entry,
    detect_slow_bounce_signal,
    get_quick_sideways_profile,
    is_sideways_snapshot,
    score_quick_sideways,
    score_slow_bounce,
)
from app.models.schemas import OptimizedProfile, PaperTrade, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _minutes_now() -> int:
    now = datetime.now(IST)
    return now.hour * 60 + now.minute


def in_worst_day_dead_zone() -> bool:
    """11:00–12:00 IST — historically 0% WR; block new quick/defensive entries."""
    settings = get_settings()
    if not settings.worst_day_dead_zone_enabled:
        return False
    from app.services.upstox import get_market_phase

    if get_market_phase() != "LIVE_MARKET":
        return False
    current = _minutes_now()
    start = settings.worst_day_dead_zone_start_hour * 60 + settings.worst_day_dead_zone_start_minute
    end = settings.worst_day_dead_zone_end_hour * 60 + settings.worst_day_dead_zone_end_minute
    return start <= current < end


_TIER_RANK = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}


def dead_zone_allows_candidate(candidate: Any) -> tuple[bool, str]:
    """
    Dead zone blocks quick/defensive entries but allows ELITE/EXPLODING vertical rips
    with material session peak or retained spike velocity.
    """
    if not in_worst_day_dead_zone():
        return True, "ok"
    settings = get_settings()
    if not getattr(settings, "worst_day_dead_zone_explosion_bypass_enabled", True):
        return False, "worst_day_dead_zone"

    mode = str(getattr(candidate, "mode", "") or "")
    if mode != "explosion":
        return False, "worst_day_dead_zone"

    tier = "WATCH"
    peak_move = 0.0
    vel3 = 0.0
    daily_move = 0.0
    event = getattr(candidate, "explosion_event", None)
    if event is not None:
        tier = str(getattr(event, "tier", "WATCH") or "WATCH")
        peak_move = float(getattr(event, "peak_move_pct", 0) or 0)
        vel3 = float(getattr(event, "velocity_3s", 0) or 0)
        daily_move = float(getattr(event, "daily_move_pct", 0) or 0)
    else:
        tier = str(getattr(candidate, "tier", "WATCH") or "WATCH")

    min_tier = str(getattr(settings, "worst_day_dead_zone_bypass_min_tier", "EXPLODING") or "EXPLODING").upper()
    if _TIER_RANK.get(tier.upper(), 0) < _TIER_RANK.get(min_tier, 3):
        return False, "worst_day_dead_zone"

    min_peak = float(getattr(settings, "worst_day_dead_zone_bypass_min_peak_pct", 30.0) or 30.0)
    min_vel = float(getattr(settings, "worst_day_dead_zone_bypass_min_velocity_3s", 2.0) or 2.0)
    min_session = float(
        getattr(settings, "worst_day_dead_zone_bypass_min_session_move_pct", 35.0) or 35.0,
    )
    if peak_move >= min_peak or daily_move >= min_session or vel3 >= min_vel:
        return True, "ok"
    if vel3 < min_vel and peak_move >= min_peak * 0.85:
        return True, "ok"
    return False, "worst_day_dead_zone"


def worst_day_defensive_session_active(
    state: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    from app.engines.bad_day_routing import bad_day_session_active
    from app.engines.worst_day_guard import session_entry_policy

    active, _ = bad_day_session_active(state, snapshots)
    if active:
        return True
    policy, _ = session_entry_policy(state, snapshots)
    return policy in ("BREAKOUT_ONLY", "PAUSED")


def _fading_or_near_symbols(
    state: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> set[str]:
    from app.engines.bad_day_routing import fading_expiry_symbols
    from app.engines.expiry_day_guards import near_expiry_symbols

    fading = set(fading_expiry_symbols(state, snapshots).keys())
    near = set(near_expiry_symbols(snapshots))
    return fading | near


def is_worst_day_alternate_symbol(
    snap: SymbolSnapshot,
    state: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Eligible non-fading index when another symbol is expiry/fading."""
    settings = get_settings()
    if not settings.worst_day_quick_alternate_only and not settings.worst_day_itm_fade_alternate_only:
        return True
    if not worst_day_defensive_session_active(state, snapshots):
        return True

    sym = snap.symbol.upper()
    restricted = _fading_or_near_symbols(state, snapshots)
    if not restricted:
        return True

    from app.engines.bad_day_routing import alternate_index_for

    for restricted_sym in restricted:
        if sym == restricted_sym.upper():
            return False
        alt = alternate_index_for(restricted_sym, snapshots)
        if alt and sym == alt.upper():
            return True

    from app.engines.bad_day_routing import pm_itm_alternate_symbol_active

    return pm_itm_alternate_symbol_active(snap, state, snapshots)


def in_worst_day_itm_fade_window(
    snap: SymbolSnapshot,
    state: Any = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> bool:
    settings = get_settings()
    if not settings.worst_day_itm_fade_enabled:
        return False
    from app.engines.expiry_day_guards import (
        in_expiry_pm_itm_window,
        in_morning_slow_bounce_window,
        is_near_expiry_day,
        slow_bounce_session_active,
    )

    if slow_bounce_session_active(snap, state, snapshots):
        return True
    if in_expiry_pm_itm_window() and state is not None and snapshots is not None:
        if is_worst_day_alternate_symbol(snap, state, snapshots):
            return True
    if in_morning_slow_bounce_window() and is_near_expiry_day(snap):
        if state is None or snapshots is None or is_worst_day_alternate_symbol(snap, state, snapshots):
            return True
    return False


def _itm_depth_ok(side: Side, strike: float, snap: SymbolSnapshot) -> bool:
    from app.engines.moneyness import atm_strike, classify_moneyness, steps_from_atm

    settings = get_settings()
    spot = snap.spot or snap.atmStrike or 0.0
    if spot <= 0:
        return False
    atm = float(snap.atmStrike or 0) or atm_strike(spot, snap.symbol)
    if classify_moneyness(side, strike, spot, symbol=snap.symbol, atm=atm) != "ITM":
        return False
    depth = abs(steps_from_atm(strike, spot, snap.symbol, atm=atm))
    return depth <= settings.worst_day_itm_fade_max_itm_steps


def _breadth_aligned(side: Side, snap: SymbolSnapshot) -> bool:
    from app.engines.symbol_cooldown import side_aligned_with_breadth

    bias = (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"
    return side_aligned_with_breadth(side.value, bias)


def get_worst_day_itm_fade_profile(entry_premium: float | None = None) -> OptimizedProfile:
    settings = get_settings()
    return OptimizedProfile(
        targetPoints=settings.worst_day_itm_fade_target_points,
        stopPoints=settings.worst_day_itm_fade_stop_points,
        microTargetPoints=settings.worst_day_itm_fade_micro_target_points,
        maxHoldSeconds=settings.worst_day_itm_fade_max_hold_seconds,
        sessionLabel="worst_day_itm_fade",
    )


def cap_worst_day_itm_fade_lots(lots: int) -> int:
    settings = get_settings()
    return min(lots, settings.worst_day_itm_fade_lot_cap)


def check_worst_day_itm_fade_entry(
    snap: SymbolSnapshot,
    side: Side,
    strike: float,
    premium: float,
    *,
    velocity_pct: float = 0.0,
    state: Any = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not settings.worst_day_itm_fade_enabled:
        return False, "worst_day_itm_fade_disabled", meta
    if state is None or snapshots is None:
        return False, "worst_day_itm_fade_requires_session", meta
    if not worst_day_defensive_session_active(state, snapshots):
        return False, "worst_day_itm_fade_requires_bad_day", meta
    if in_worst_day_dead_zone():
        return False, "worst_day_dead_zone", meta
    if not in_worst_day_itm_fade_window(snap, state, snapshots):
        return False, "worst_day_itm_fade_window_closed", meta
    if not is_worst_day_alternate_symbol(snap, state, snapshots):
        return False, "worst_day_itm_fade_alternate_only", meta
    if not _breadth_aligned(side, snap):
        return False, "worst_day_itm_fade_requires_alignment", meta
    if not _itm_depth_ok(side, strike, snap):
        return False, "worst_day_itm_fade_itm_depth", meta
    if premium < settings.worst_day_itm_fade_min_premium_inr:
        return False, "worst_day_itm_fade_premium_below_min", meta
    from app.engines.expiry_day_guards import slow_bounce_premium_max_inr

    if premium > slow_bounce_premium_max_inr(snap):
        return False, "worst_day_itm_fade_premium_above_max", meta
    if float(snap.tradeQualityScore or 0) < settings.worst_day_itm_fade_min_tqs:
        return False, f"worst_day_itm_fade_tqs_below_{settings.worst_day_itm_fade_min_tqs:.0f}", meta

    chart = snap.spotChart
    mom5 = abs(chart.momentum5Pct or 0) if chart else 0.0
    vel = max(velocity_pct, _micro_velocity(snap, side, strike), mom5)
    meta["velocityPct"] = round(vel, 3)
    if vel < settings.worst_day_itm_fade_min_velocity_pct:
        return False, f"worst_day_itm_fade_velocity_below_{settings.worst_day_itm_fade_min_velocity_pct}", meta
    if vel > settings.worst_day_itm_fade_max_velocity_pct:
        return False, "worst_day_itm_fade_velocity_too_hot", meta

    sig_ok, sig_reason, sig_meta = detect_slow_bounce_signal(snap, side, strike, premium)
    meta["slowBounceSignal"] = sig_meta
    if sig_ok:
        meta["signal"] = "slow_bounce"
        return True, sig_reason, meta

    if chart:
        side_val = side.value
        direction = (chart.direction or "NEUTRAL").upper()
        aligned_chart = (
            (side_val == "CALL" and direction in ("BULLISH", "NEUTRAL"))
            or (side_val == "PUT" and direction in ("BEARISH", "NEUTRAL"))
        )
        if aligned_chart and vel <= settings.worst_day_quick_max_velocity_pct:
            meta["signal"] = "aligned_itm_fade"
            return True, "worst_day_itm_fade", meta

    return False, "no_worst_day_itm_fade_signal", meta


def score_worst_day_itm_fade(
    snap: SymbolSnapshot,
    side: Side,
    strike: float,
    premium: float,
    velocity_pct: float,
    signal_meta: dict[str, Any],
    *,
    state: Any = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> float:
    settings = get_settings()
    if signal_meta.get("slowBounceSignal"):
        base = score_slow_bounce(snap, side, strike, premium, velocity_pct, signal_meta.get("slowBounceSignal") or {})
    else:
        base = score_slow_bounce(snap, side, strike, premium, velocity_pct, {})
    score = base + settings.worst_day_itm_fade_rank_bonus
    if state is not None and snapshots is not None and is_worst_day_alternate_symbol(snap, state, snapshots):
        score += 6.0
    if _breadth_aligned(side, snap):
        score += 4.0
    return round(score, 2)


def scan_worst_day_itm_fade_setups(
    symbol: str,
    snap: SymbolSnapshot,
    state: Any = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> list[dict]:
    settings = get_settings()
    if not settings.worst_day_itm_fade_enabled or state is None or snapshots is None:
        return []
    if not worst_day_defensive_session_active(state, snapshots):
        return []

    chart = snap.spotChart
    if not chart:
        return []

    setups: list[dict] = []
    for side in (Side.PUT, Side.CALL):
        if not _breadth_aligned(side, snap):
            continue
        for strike, premium in _collect_itm_strike_candidates(snap, side):
            vel = _micro_velocity(snap, side, strike)
            ok, reason, meta = check_worst_day_itm_fade_entry(
                snap, side, strike, premium,
                velocity_pct=vel, state=state, snapshots=snapshots,
            )
            if not ok:
                continue
            setups.append({
                "symbol": symbol,
                "side": side,
                "strike": strike,
                "premium": premium,
                "velocityPct": vel,
                "score": score_worst_day_itm_fade(
                    snap, side, strike, premium, vel, meta,
                    state=state, snapshots=snapshots,
                ),
                "reason": reason,
                "mode": "worst_day_itm_fade",
                "worstDayFadeMeta": meta,
            })

    setups.sort(key=lambda s: s["score"], reverse=True)
    return setups[:2]


def worst_day_quick_trade_allowed(
    candidate: Any,
    state: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str]:
    """Quick sideways on alternate index during bad-day chop — not dead zone."""
    settings = get_settings()
    if getattr(settings, "worst_day_block_quick_trades", True):
        return False, "worst_day_blocks_quick_sideways"
    if not settings.worst_day_quick_enabled:
        return False, "worst_day_quick_disabled"
    if str(getattr(candidate, "mode", "") or "") != "quick_sideways":
        return False, "not_quick_sideways"
    if not worst_day_defensive_session_active(state, snapshots):
        return False, "worst_day_quick_requires_bad_day"
    if in_worst_day_dead_zone():
        return False, "worst_day_dead_zone"
    snap = snapshots.get(candidate.symbol.upper()) or candidate.snap
    if not is_worst_day_alternate_symbol(snap, state, snapshots):
        return False, "worst_day_quick_alternate_only"
    if not is_sideways_snapshot(snap):
        return False, "worst_day_quick_requires_chop"
    if not _breadth_aligned(candidate.side, snap):
        return False, "worst_day_quick_requires_alignment"
    score = float(getattr(candidate, "score", 0) or 0)
    if score < settings.worst_day_quick_min_rank:
        return False, f"worst_day_quick_rank_below_{settings.worst_day_quick_min_rank:.0f}"
    chart = snap.spotChart
    mom5 = abs(chart.momentum5Pct or 0) if chart else 0.0
    vel = max(
        float((getattr(candidate, "pretrade_meta", None) or {}).get("velocityPct") or 0),
        mom5,
    )
    if vel > settings.worst_day_quick_max_velocity_pct:
        return False, "worst_day_quick_velocity_too_hot"
    return True, "ok"


def check_worst_day_quick_entry(
    snap: SymbolSnapshot,
    side: Side,
    strike: float,
    premium: float,
    *,
    velocity_pct: float = 0.0,
    state: Any = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> tuple[bool, str]:
    ok, reason = check_quick_sideways_entry(
        snap, side, strike, premium,
        velocity_pct=velocity_pct, state=state, snapshots=snapshots,
    )
    if not ok:
        return False, reason
    if state is None or snapshots is None:
        return False, "worst_day_quick_requires_session"
    if not worst_day_defensive_session_active(state, snapshots):
        return True, "passed"
    if in_worst_day_dead_zone():
        return False, "worst_day_dead_zone"
    if not is_worst_day_alternate_symbol(snap, state, snapshots):
        return False, "worst_day_quick_alternate_only"
    if not _breadth_aligned(side, snap):
        return False, "worst_day_quick_requires_alignment"
    vel = max(velocity_pct, _micro_velocity(snap, side, strike))
    settings = get_settings()
    if vel > settings.worst_day_quick_max_velocity_pct:
        return False, "worst_day_quick_velocity_too_hot"
    return True, "passed"


def scan_worst_day_quick_setups(
    symbol: str,
    snap: SymbolSnapshot,
    state: Any = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> list[dict]:
    """Alternate-index quick scalps when bad-day session is active."""
    settings = get_settings()
    if not settings.worst_day_quick_enabled or state is None or snapshots is None:
        return []
    if not worst_day_defensive_session_active(state, snapshots):
        return []
    if not is_worst_day_alternate_symbol(snap, state, snapshots):
        return []
    if not is_sideways_snapshot(snap):
        return []

    chart = snap.spotChart
    if not chart:
        return []

    side = _pick_side(chart, snap)
    if not side or not _breadth_aligned(side, snap):
        return []

    from app.engines.quick_sideways import _collect_strike_candidates

    setups: list[dict] = []
    for strike, premium in _collect_strike_candidates(snap, side):
        vel = _micro_velocity(snap, side, strike)
        ok, reason = check_worst_day_quick_entry(
            snap, side, strike, premium,
            velocity_pct=vel, state=state, snapshots=snapshots,
        )
        if not ok:
            continue
        score = score_quick_sideways(
            snap, side, strike, premium, vel, state=state, snapshots=snapshots,
        ) + settings.worst_day_quick_rank_bonus
        if score < settings.worst_day_quick_min_rank:
            continue
        setups.append({
            "symbol": symbol,
            "side": side,
            "strike": strike,
            "premium": premium,
            "velocityPct": vel,
            "score": round(score, 2),
            "reason": reason,
            "mode": "quick_sideways",
            "worstDayQuick": True,
        })

    setups.sort(key=lambda s: s["score"], reverse=True)
    return setups[:2]


def evaluate_worst_day_itm_fade_exit(
    trade: PaperTrade,
    current_premium: float,
    lot_multiplier: int,
    *,
    snap: SymbolSnapshot | None = None,
) -> tuple[Optional[str], float]:
    """Tight defensive exits — reuse quick sideways evaluator with fade profile."""
    from app.engines.quick_sideways import evaluate_quick_sideways_exit

    settings = get_settings()
    profile = get_worst_day_itm_fade_profile(trade.entryPremium)
    ctx = trade.entryContext or {}
    ctx = {**ctx, "exitPlan": {
        "targetPoints": profile.targetPoints,
        "stopPoints": profile.stopPoints,
        "microTargetPoints": profile.microTargetPoints,
    }}
    trade.entryContext = ctx
    reason, pnl = evaluate_quick_sideways_exit(
        trade, current_premium, lot_multiplier, snap=snap,
    )
    if reason:
        return reason.replace("quick_sideways", "worst_day_itm_fade"), pnl
    hold = (datetime.now(IST) - trade.openedAt.astimezone(IST)).total_seconds()
    if hold >= profile.maxHoldSeconds:
        pnl_pts = current_premium - trade.entryPremium
        pnl_inr = pnl_pts * trade.lots * lot_multiplier
        if pnl_pts > 0:
            return "worst_day_itm_fade_time_profit", pnl_inr
        return "worst_day_itm_fade_time_scratch", pnl_inr
    return None, (current_premium - trade.entryPremium) * trade.lots * lot_multiplier


def worst_day_trades_summary(
    state: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.worst_day_itm_fade_enabled,
        "quickEnabled": settings.worst_day_quick_enabled,
        "defensiveSession": worst_day_defensive_session_active(state, snapshots),
        "deadZone": in_worst_day_dead_zone(),
        "alternateSymbols": [
            sym for sym, snap in snapshots.items()
            if snap.dataAvailable and is_worst_day_alternate_symbol(snap, state, snapshots)
        ],
    }
