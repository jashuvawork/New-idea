"""Bad-day routing — fading expiry index, cross-index preference, high-confidence only."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.capital_allocator import compute_session_pnl
from app.engines.expiry_day_guards import is_near_expiry_day, is_symbol_expiry_day, near_expiry_symbols
from app.engines.pretrade_validator import collect_session_trades
from app.engines.symbol_cooldown import side_aligned_with_breadth
from app.engines.whipsaw_guards import is_bearish_sideways_session
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot


def symbol_session_pnl(symbol: str, state: AutoTraderState) -> float:
    sym = symbol.upper()
    return sum(
        float(t.pnl_inr or 0)
        for t in collect_session_trades(state)
        if str(t.symbol).upper() == sym
    )


def expiry_index_fading(
    snap: SymbolSnapshot,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, list[str]]:
    """
    Expiry symbol bleeding / chop — route away unless very high confidence.
    """
    settings = get_settings()
    if not settings.bad_day_routing_enabled or not is_symbol_expiry_day(snap):
        return False, []

    reasons: list[str] = []
    sym_pnl = symbol_session_pnl(snap.symbol, state)
    if sym_pnl <= settings.expiry_fading_symbol_loss_inr:
        reasons.append(f"symbol_loss_{sym_pnl:.0f}")

    if is_bearish_sideways_session(snapshots):
        reasons.append("bearish_sideways")

    if float(snap.tradeQualityScore or 0) < settings.expiry_fading_max_symbol_tqs:
        reasons.append(f"low_tqs_{snap.tradeQualityScore:.0f}")

    chart = snap.spotChart
    if chart and abs(float(chart.momentum5Pct or 0)) < 0.02 and sym_pnl < 0:
        reasons.append("stale_momentum_while_losing")

    session_pnl = compute_session_pnl(state)
    if session_pnl <= settings.expiry_fading_session_loss_inr:
        reasons.append(f"session_loss_{session_pnl:.0f}")

    return bool(reasons), reasons


def fading_expiry_symbols(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        fading, reasons = expiry_index_fading(snap, state, snapshots)
        if fading:
            out[sym.upper()] = reasons
    return out


def pm_itm_alternate_symbols(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> set[str]:
    """Non-expiry alternate indices eligible for PM ITM when another index is near-expiry."""
    settings = get_settings()
    if not settings.expiry_pm_itm_alternate_index_enabled:
        return set()
    from app.engines.expiry_day_guards import in_expiry_pm_itm_window, is_expiry_session

    if not in_expiry_pm_itm_window():
        return set()

    near = near_expiry_symbols(snapshots)
    if not is_expiry_session(snapshots) and not near:
        return set()

    restricted: set[str] = set()
    if is_expiry_session(snapshots):
        fading = fading_expiry_symbols(state, snapshots)
        restricted.update(fading.keys())
    restricted.update(near)

    if not restricted:
        return set()

    out: set[str] = set()
    for restricted_sym in restricted:
        alt = alternate_index_for(restricted_sym, snapshots)
        if alt:
            out.add(alt)
    return out


def pm_itm_alternate_symbol_active(
    snap: SymbolSnapshot,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    if not snap.dataAvailable:
        return False
    return snap.symbol.upper() in pm_itm_alternate_symbols(state, snapshots)


def alternate_index_for(fading_symbol: str, snapshots: dict[str, SymbolSnapshot]) -> Optional[str]:
    """Healthier non-near-expiry index when another symbol is expiry/fading."""
    fading = fading_symbol.upper()
    best: Optional[str] = None
    best_tqs = -1.0
    for sym, snap in snapshots.items():
        if not snap.dataAvailable or sym.upper() == fading:
            continue
        if is_symbol_expiry_day(snap) or is_near_expiry_day(snap):
            continue
        tqs = float(snap.tradeQualityScore or 0)
        if tqs > best_tqs:
            best_tqs = tqs
            best = sym.upper()
    return best


def pre_expiry_index_restricted(
    snap: SymbolSnapshot,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, Optional[str]]:
    """
    Near-expiry symbol (today or tomorrow) with a healthier alternate index.
  Used to route explosion/scalp to NIFTY when SENSEX is pre-expiry, and vice versa.
    """
    settings = get_settings()
    if not settings.pre_expiry_cross_index_enabled or not settings.bad_day_routing_enabled:
        return False, None
    if not snap.dataAvailable or not is_near_expiry_day(snap):
        return False, None
    alt = alternate_index_for(snap.symbol.upper(), snapshots)
    if not alt:
        return False, None
    return True, alt


def bad_day_session_active(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, list[str]]:
    settings = get_settings()
    if not settings.bad_day_routing_enabled:
        return False, []

    reasons: list[str] = []
    if is_bearish_sideways_session(snapshots):
        reasons.append("bearish_sideways")

    if fading_expiry_symbols(state, snapshots):
        reasons.append("expiry_index_fading")

    from app.engines.expiry_day_guards import is_expiry_session, predict_worst_expiry_day

    if is_expiry_session(snapshots):
        worst, score, worst_reasons = predict_worst_expiry_day(state, snapshots)
        if worst:
            reasons.append(f"expiry_worst_{score:.0f}")
            reasons.extend(worst_reasons[:2])

    session_pnl = compute_session_pnl(state)
    if session_pnl <= settings.bad_day_session_loss_inr:
        reasons.append(f"session_loss_{session_pnl:.0f}")

    trades = collect_session_trades(state)
    if len(trades) >= 2:
        recent = trades[-3:]
        losses = sum(1 for t in recent if t.pnl_inr < 0)
        if losses >= settings.bad_day_recent_loss_count:
            reasons.append(f"recent_losses_{losses}")

    return bool(reasons), reasons


def bad_day_min_rank_floor(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> float:
    settings = get_settings()
    if settings.dual_mode_enabled:
        from app.engines.daily_18pct_strategy import get_session_limits
        from app.engines.dual_mode_strategy import (
            resolve_trading_session_mode,
            skip_bad_day_rank_floor,
        )

        limits = get_session_limits()
        day_mode = str(getattr(limits, "dayMode", "") or "") if limits else ""
        tier = str(getattr(limits, "confidenceTier", "") or "MEDIUM") if limits else "MEDIUM"
        mode, _ = resolve_trading_session_mode(
            state, snapshots, day_mode=day_mode, confidence_tier=tier,
        )
        if skip_bad_day_rank_floor(mode) and settings.aggressive_good_day_bypass_bad_day_floor:
            return 0.0

    active, _ = bad_day_session_active(state, snapshots)
    if not active:
        return 0.0
    floor = settings.bad_day_high_confidence_min_rank
    session_pnl = compute_session_pnl(state)
    if session_pnl <= settings.bad_day_severe_session_loss_inr:
        floor = max(floor, settings.bad_day_severe_min_rank)
    return floor


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _breadth_aligned(candidate: Any, snap: SymbolSnapshot) -> bool:
    side_val = _side_val(candidate.side)
    return side_aligned_with_breadth(side_val, snap.breadth.bias)


def _candidate_session_move(candidate: Any) -> float:
    ev = getattr(candidate, "explosion_event", None)
    if ev is not None:
        return float(getattr(ev, "daily_move_pct", 0) or 0)
    alert = getattr(candidate, "alert", None) or {}
    return float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)


def _extreme_explosion_bypass(candidate: Any) -> bool:
    """Session rip +4520% — don't apply bad-day / pre-expiry blocks meant for chop days."""
    settings = get_settings()
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False
    open_move = _candidate_session_move(candidate)
    score = float(getattr(candidate, "score", 0) or 0)
    if open_move >= settings.all_day_explosion_extreme_move_min_pct:
        return score >= settings.all_day_explosion_min_score - 5
    if open_move >= settings.all_day_explosion_session_move_min_pct:
        return score >= settings.all_day_explosion_min_score
    return False


def check_bad_day_candidate(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """High-confidence only on bad days; block fading expiry index unless elite."""
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not settings.bad_day_routing_enabled:
        return True, "ok", meta

    active, session_reasons = bad_day_session_active(state, snapshots)
    meta["badDaySession"] = active
    meta["badDayReasons"] = session_reasons
    if not active:
        return True, "ok", meta

    sym = candidate.symbol.upper()
    snap = snapshots.get(sym) or candidate.snap
    score = float(getattr(candidate, "score", 0) or 0)
    mode = str(getattr(candidate, "mode", "") or "")
    tier = str(getattr(candidate, "tier", "") or "").upper()
    aligned = _breadth_aligned(candidate, snap)
    meta["breadthAligned"] = aligned

    floor = bad_day_min_rank_floor(state, snapshots)
    meta["badDayMinRank"] = floor

    fading, fade_reasons = expiry_index_fading(snap, state, snapshots)
    meta["expiryIndexFading"] = fading
    meta["fadingReasons"] = fade_reasons
    pre_restricted, pre_alt = pre_expiry_index_restricted(snap, snapshots)
    meta["preExpiryRestricted"] = pre_restricted
    meta["preExpiryAlternate"] = pre_alt

    if fading:
        alt = alternate_index_for(sym, snapshots)
        meta["alternateIndex"] = alt
        if mode == "scalp":
            return False, "bad_day_no_regular_scalps_on_fading_expiry", meta
        if mode == "slow_bounce":
            return False, "bad_day_slow_bounce_on_fading_expiry", meta
        if mode == "worst_day_itm_fade":
            return False, "bad_day_worst_day_itm_fade_on_fading_expiry", meta
        if mode == "explosion":
            if tier not in ("ELITE", "EXPLODING"):
                return False, "bad_day_fading_expiry_explosion_tier", meta
            if not aligned:
                return False, "bad_day_fading_expiry_requires_alignment", meta
            min_req = min(settings.bad_day_fading_expiry_min_rank, floor)
            if tier == "EXPLODING" and aligned:
                min_req = min(min_req, max(floor, settings.best_trades_min_rank_score))
            if score < min_req:
                return False, f"bad_day_fading_expiry_rank_below_{min_req:.0f}", meta
            return True, "ok", meta

    if pre_restricted and pre_alt:
        meta["alternateIndex"] = pre_alt
        if _extreme_explosion_bypass(candidate):
            return True, "ok", meta
        from app.engines.expiry_day_guards import is_symbol_expiry_day

        if (
            mode == "explosion"
            and is_symbol_expiry_day(snap)
            and aligned
            and tier in ("EXPLODING", "ELITE")
            and score >= settings.pre_expiry_expiry_symbol_explosion_min_rank
        ):
            return True, "ok", meta
        if mode in ("quick_sideways", "slow_bounce"):
            return True, "ok", meta
        if mode == "scalp":
            return False, "pre_expiry_route_to_alternate_index", meta
        if mode == "explosion":
            if tier != "ELITE" and score < settings.pre_expiry_alternate_min_rank:
                return False, "pre_expiry_explosion_route_to_alternate", meta
        elif score < settings.pre_expiry_alternate_min_rank:
            return False, "pre_expiry_route_to_alternate_index", meta

    if mode == "scalp" and score < floor:
        return False, f"bad_day_scalp_rank_below_{floor:.0f}", meta

    if mode == "explosion":
        if _extreme_explosion_bypass(candidate):
            return True, "ok", meta
        if tier != "ELITE" and score < floor:
            return False, f"bad_day_explosion_rank_below_{floor:.0f}", meta
        if not aligned and score < settings.high_confidence_min_score:
            return False, "bad_day_explosion_counter_breadth", meta
        if float(snap.tradeQualityScore or 0) < settings.bad_day_min_symbol_tqs:
            return False, f"bad_day_symbol_tqs_below_{settings.bad_day_min_symbol_tqs:.0f}", meta
        return True, "ok", meta

    if mode == "slow_bounce":
        from app.engines.expiry_day_guards import expiry_pm_itm_quick_active

        if expiry_pm_itm_quick_active(snap, state, snapshots):
            sb_floor = settings.quick_sideways_slow_bounce_min_rank_score
            if score >= sb_floor and _breadth_aligned(candidate, snap):
                return True, "ok", meta
        return False, "bad_day_slow_bounce_requires_pm_itm_alternate", meta

    if mode == "worst_day_itm_fade":
        from app.engines.worst_day_itm_fade import is_worst_day_alternate_symbol

        if is_worst_day_alternate_symbol(snap, state, snapshots) and _breadth_aligned(candidate, snap):
            if score >= settings.worst_day_itm_fade_min_rank:
                return True, "ok", meta
        return False, "bad_day_worst_day_itm_fade_requires_alternate", meta

    pre_meta = getattr(candidate, "pretrade_meta", None) or {}
    if mode == "quick_sideways" and pre_meta.get("worstDayQuick"):
        from app.engines.worst_day_itm_fade import is_worst_day_alternate_symbol

        if is_worst_day_alternate_symbol(snap, state, snapshots) and _breadth_aligned(candidate, snap):
            if score >= settings.worst_day_quick_min_rank:
                return True, "ok", meta
        return False, "bad_day_worst_day_quick_requires_alternate", meta

    if score < floor:
        return False, f"bad_day_rank_below_{floor:.0f}", meta

    return True, "ok", meta


def cross_index_rank_adjustment(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> float:
    """Prefer healthier non-expiry index when expiry symbol is fading."""
    settings = get_settings()
    if not settings.bad_day_routing_enabled:
        return 0.0

    fading_map = fading_expiry_symbols(state, snapshots)
    near = near_expiry_symbols(snapshots)
    if not fading_map and not near:
        return 0.0

    sym = candidate.symbol.upper()
    snap = snapshots.get(sym) or candidate.snap
    bonus = 0.0
    settings = get_settings()

    restricted = set(fading_map.keys()) | set(near)
    for restricted_sym in restricted:
        alt = alternate_index_for(restricted_sym, snapshots)
        if sym == restricted_sym:
            if restricted_sym in fading_map:
                bonus -= settings.bad_day_fading_symbol_penalty
            elif settings.pre_expiry_cross_index_enabled:
                bonus -= settings.pre_expiry_symbol_rank_penalty
            continue
        if alt and sym == alt:
            fading_snap = snapshots.get(restricted_sym)
            if fading_snap and float(snap.tradeQualityScore or 0) >= float(fading_snap.tradeQualityScore or 0) - 5:
                bonus += settings.bad_day_alternate_index_bonus
            if _breadth_aligned(candidate, snap):
                bonus += settings.bad_day_alternate_aligned_bonus

    return bonus


def bad_day_lot_cap(premium: float, lots: int, state: AutoTraderState, snapshots: dict) -> int:
    settings = get_settings()
    active, _ = bad_day_session_active(state, snapshots)
    if not active or premium > settings.bad_day_cheap_premium_threshold_inr:
        return lots
    return min(lots, settings.bad_day_cheap_premium_lot_cap)


def bad_day_routing_summary(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, Any]:
    settings = get_settings()
    active, reasons = bad_day_session_active(state, snapshots)
    fading = fading_expiry_symbols(state, snapshots)
    near = near_expiry_symbols(snapshots)
    alts = {sym: alternate_index_for(sym, snapshots) for sym in set(fading.keys()) | set(near)}
    pm_alts = sorted(pm_itm_alternate_symbols(state, snapshots))
    pre_alts = {
        sym: alternate_index_for(sym, snapshots)
        for sym in near
        if alternate_index_for(sym, snapshots)
    }
    return {
        "enabled": settings.bad_day_routing_enabled,
        "badDaySession": active,
        "badDayReasons": reasons,
        "minRankFloor": bad_day_min_rank_floor(state, snapshots),
        "fadingExpirySymbols": fading,
        "nearExpirySymbols": near,
        "preExpiryAlternates": pre_alts,
        "alternateIndex": alts,
        "pmItmAlternateSymbols": pm_alts,
        "sessionPnlInr": round(compute_session_pnl(state), 2),
    }
