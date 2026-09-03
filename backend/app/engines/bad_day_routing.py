"""Bad-day routing — fading expiry index, cross-index preference, high-confidence only."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.config import get_settings
from app.engines.capital_allocator import compute_session_pnl
from app.engines.expiry_day_guards import (
    expiry_symbols,
    in_expiry_afternoon_window,
    is_expiry_session,
    is_near_expiry_day,
    is_pre_expiry_day,
    is_symbol_expiry_day,
    near_expiry_symbols,
)
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


def _snap_expiry_date(snap: Optional[SymbolSnapshot]) -> Optional[str]:
    if snap is None or not getattr(snap, "dataAvailable", False):
        return None
    raw = getattr(snap, "optionExpiry", None)
    if not raw:
        return None
    return str(raw)[:10]


def expiry_proximity_ranks(
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[list[str], list[str]]:
    """
    Return (nearest_symbols, same_week_next_symbols) by optionExpiry date.

    Weekly schedule: Tue NIFTY / Thu SENSEX — whichever date is sooner is #1;
    the other index within a few days is #2. Roles flip through the week.
    """
    settings = get_settings()
    by_date: dict[str, list[str]] = {}
    for sym, snap in snapshots.items():
        d = _snap_expiry_date(snap)
        if not d:
            continue
        by_date.setdefault(d, []).append(sym.upper())
    if not by_date:
        return [], []
    dates = sorted(by_date.keys())
    nearest = list(by_date[dates[0]])
    nxt: list[str] = []
    if len(dates) >= 2:
        try:
            d0 = datetime.strptime(dates[0], "%Y-%m-%d")
            d1 = datetime.strptime(dates[1], "%Y-%m-%d")
            max_gap = int(getattr(settings, "expiry_day_same_week_next_max_days", 3) or 3)
            if 0 < (d1 - d0).days <= max_gap:
                nxt = list(by_date[dates[1]])
        except ValueError:
            nxt = []
    return nearest, nxt


def is_same_week_next_index(
    snap: SymbolSnapshot,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """True when this index is #2 by expiry proximity (e.g. Thu SENSEX on Tue)."""
    _nearest, nxt = expiry_proximity_ranks(snapshots)
    return snap.symbol.upper() in nxt


def pre_expiry_index_restricted(
    snap: SymbolSnapshot,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, Optional[str]]:
    """
    Soft-route away from FAR expiry only — never from the near-expiry priority index.

    Near expiry (today or tomorrow / nearest date) stays tradeable. Legacy
    alternate routing only hits an index that is NOT the nearest expiry.
    """
    settings = get_settings()
    if not settings.pre_expiry_cross_index_enabled or not settings.bad_day_routing_enabled:
        return False, None
    if not snap.dataAvailable:
        return False, None
    # Near-expiry priority mode: never demote today/tomorrow / nearest index.
    if getattr(settings, "expiry_day_prefer_same_day_enabled", True):
        nearest, nxt = expiry_proximity_ranks(snapshots)
        sym = snap.symbol.upper()
        if sym in nearest or sym in nxt or is_near_expiry_day(snap):
            return False, None
        return False, None
    # Legacy path (prefer disabled): tomorrow pre-expiry → alternate.
    if not is_pre_expiry_day(snap):
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
    if side_aligned_with_breadth(side_val, snap.breadth.bias):
        return True
    from app.engines.local_base_chart_bypass import local_base_overrides_side_bias

    alert = getattr(candidate, "alert", None)
    if not isinstance(alert, dict):
        alert = None
    return local_base_overrides_side_bias(
        side_val,
        snap,
        event=getattr(candidate, "explosion_event", None),
        alert=alert,
    )


def _candidate_session_move(candidate: Any) -> float:
    ev = getattr(candidate, "explosion_event", None)
    if ev is not None:
        daily = float(getattr(ev, "daily_move_pct", 0) or 0)
        peak = float(getattr(ev, "peak_move_pct", 0) or 0)
        return max(daily, peak)
    alert = getattr(candidate, "alert", None) or {}
    daily = float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)
    peak = float(alert.get("peakMovePct") or 0)
    return max(daily, peak)


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
        from app.engines.expiry_day_guards import is_near_expiry_day, is_symbol_expiry_day
        from app.engines.open_gap_capture import open_gap_near_expiry_symbol_allow

        # Jul29: SENSEX near-expiry CE rip must trade on SENSEX, not only NIFTY alternate.
        if open_gap_near_expiry_symbol_allow(candidate, snap):
            meta["openGapNearExpiryAllow"] = True
            return True, "ok", meta
        if (
            mode == "explosion"
            and (is_symbol_expiry_day(snap) or is_near_expiry_day(snap))
            and aligned
            and tier in ("EXPLODING", "ELITE")
            and score >= settings.pre_expiry_expiry_symbol_explosion_min_rank
        ):
            meta["nearExpirySymbolExplosionAllow"] = True
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
        from app.engines.grade_a_ftv_capture import is_grade_a_ftv_first_lift_candidate
        from app.engines.top_ftv_v_expiry_bypass import is_top_ftv_or_v_candidate

        if is_grade_a_ftv_first_lift_candidate(candidate):
            min_req = float(
                getattr(settings, "grade_a_ftv_first_lift_min_rank", 40.0) or 40.0
            )
            meta["gradeAFtvBypass"] = True
            if score >= min_req:
                return True, "ok", meta
            return False, f"grade_a_ftv_rank_below_{min_req:.0f}", meta
        if is_top_ftv_or_v_candidate(candidate):
            min_req = float(
                getattr(settings, "top_ftv_v_expiry_bypass_min_rank", 0.0) or 0.0
            )
            meta["topFtvVBypass"] = True
            if score >= min_req:
                return True, "ok", meta
            return False, f"top_ftv_v_rank_below_{min_req:.0f}", meta
        from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass

        event = getattr(candidate, "explosion_event", None)
        if event is not None and qualifies_for_vertical_rip_bypass(event, snap=snap):
            routed_away = bool(pre_restricted and pre_alt and sym.upper() != pre_alt.upper())
            if not routed_away:
                meta["verticalRipBypass"] = True
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
        from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass

        event = getattr(candidate, "explosion_event", None)
        if mode == "explosion" and event is not None and qualifies_for_vertical_rip_bypass(event, snap=snap):
            meta["verticalRipBypass"] = True
            return True, "ok", meta
        return False, f"bad_day_rank_below_{floor:.0f}", meta

    return True, "ok", meta


def expiry_afternoon_deep_itm_routing_active(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """After 13:30 on any expiry session — route to expiring-symbol deep ITM."""
    settings = get_settings()
    if not getattr(settings, "expiry_afternoon_deep_itm_routing_enabled", True):
        return False
    if not settings.expiry_day_guards_enabled:
        return False
    if not is_expiry_session(snapshots):
        return False
    return in_expiry_afternoon_window()


def _candidate_itm_depth(candidate: Any, snap: SymbolSnapshot) -> int:
    from app.engines.moneyness import _depth_steps, classify_moneyness

    side = _side_val(candidate.side)
    strike = float(getattr(candidate, "strike", 0) or 0)
    spot = float(snap.spot or 0)
    if spot <= 0 or strike <= 0:
        return 0
    atm = float(snap.atmStrike or 0)
    if classify_moneyness(side, strike, spot, symbol=snap.symbol, atm=atm or None) != "ITM":
        return 0
    return _depth_steps(side, strike, spot, snap.symbol.upper(), atm or spot)


def is_expiry_deep_itm_candidate(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Deep ITM leg on today's expiring index (e.g. SENSEX 76600 PE on Thu expiry)."""
    settings = get_settings()
    if not expiry_afternoon_deep_itm_routing_active(snapshots):
        return False
    sym = candidate.symbol.upper()
    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None or not is_symbol_expiry_day(snap):
        return False
    min_steps = int(getattr(settings, "expiry_afternoon_deep_itm_min_steps", 2) or 2)
    return _candidate_itm_depth(candidate, snap) >= min_steps


def _scan_expiring_deep_itm_heatmap(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Core scan — expiring index heatmap has tradeable deep ITM premium."""
    settings = get_settings()
    from app.engines.moneyness import atm_strike, classify_moneyness, steps_from_atm

    min_steps = int(getattr(settings, "expiry_afternoon_deep_itm_min_steps", 2) or 2)
    max_prem = float(getattr(settings, "expiry_pm_itm_premium_max_inr", 280.0) or 280.0)
    min_prem = float(getattr(settings, "expiry_day_min_option_premium_inr", 15.0) or 15.0)

    for sym in expiry_symbols(snapshots):
        snap = snapshots.get(sym)
        if snap is None or not snap.dataAvailable or not snap.heatmap:
            continue
        spot = float(snap.spot or 0)
        if spot <= 0:
            continue
        atm = float(snap.atmStrike or 0) or atm_strike(spot, sym)
        for side in (Side.PUT, Side.CALL):
            for row in snap.heatmap:
                strike = float(getattr(row, "strike", 0) or 0)
                if strike <= 0:
                    continue
                prem = float(
                    getattr(row, "putLtp", 0) or 0
                    if side == Side.PUT
                    else getattr(row, "callLtp", 0) or 0
                )
                if prem < min_prem or prem > max_prem:
                    continue
                if classify_moneyness(side, strike, spot, symbol=sym, atm=atm) != "ITM":
                    continue
                if abs(steps_from_atm(strike, spot, sym, atm=atm)) >= min_steps:
                    return True
    return False


def _expiry_deep_itm_pm_modes() -> tuple[str, ...]:
    return ("quick_sideways", "slow_bounce", "worst_day_itm_fade", "explosion")


def in_expiry_power_hour_deep_itm_context(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """15:00–15:30 on an expiry session — canonical close deep ITM window."""
    settings = get_settings()
    if not getattr(settings, "expiry_power_hour_deep_itm_enabled", True):
        return False
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return False
    from app.engines.power_hour_guards import in_power_hour_window

    return in_power_hour_window()


def snapshots_have_expiring_deep_itm_session_setup(
    snapshots: dict[str, SymbolSnapshot],
    state: AutoTraderState | None = None,
) -> bool:
    """
    Expiring index shows deep ITM on heatmap during PM ITM / afternoon / power hour.
    Lifts power-hour top-only, expiry evening block, and severe session pause.
    """
    settings = get_settings()
    if not getattr(settings, "expiry_afternoon_deep_itm_routing_enabled", True):
        return False
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return False

    from app.engines.expiry_day_guards import (
        expiry_pm_itm_quick_session_active,
        in_expiry_afternoon_window,
    )
    from app.engines.power_hour_guards import in_power_hour_window

    window_open = (
        in_expiry_afternoon_window()
        or in_power_hour_window()
        or expiry_pm_itm_quick_session_active(snapshots, state)
    )
    if not window_open:
        return False
    return _scan_expiring_deep_itm_heatmap(snapshots)


def snapshots_have_expiring_deep_itm_power_hour_setup(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Power-hour carve-out: deep ITM on expiring symbol during 15:00–15:30."""
    if not in_expiry_power_hour_deep_itm_context(snapshots):
        return False
    return _scan_expiring_deep_itm_heatmap(snapshots)


def severe_pause_expiring_deep_itm_lift_active(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """
    Session <= severe loss stop but expiring deep ITM close setup is live —
    allow ONLY expiring-symbol deep ITM entries (Sep03 76600 PE after -22k).
    """
    settings = get_settings()
    if not getattr(settings, "expiry_severe_pause_deep_itm_lift_enabled", True):
        return False
    session_pnl = compute_session_pnl(state)
    if session_pnl > float(getattr(settings, "worst_day_full_pause_loss_inr", -20_000.0) or -20_000.0):
        return False
    return snapshots_have_expiring_deep_itm_power_hour_setup(snapshots)


def _expiring_symbol_snapshots(
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, SymbolSnapshot]:
    return {
        sym.upper(): snap
        for sym, snap in snapshots.items()
        if is_symbol_expiry_day(snap)
    }


def snapshots_have_expiring_top_trade_signal(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Top FTV/V/ELITE/EXPLODING on a same-day expiry index (not cross-index)."""
    settings = get_settings()
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return False
    expiring = _expiring_symbol_snapshots(snapshots)
    if not expiring:
        return False
    from app.engines.top_signal_session_lift import snapshots_have_top_signal_session_lift

    return snapshots_have_top_signal_session_lift(expiring)


def expiry_daily_loss_stop_bypass_active(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Daily loss stop hit, but same-day expiry index has a top trade on radar."""
    settings = get_settings()
    if not getattr(settings, "expiry_daily_loss_stop_bypass_enabled", True):
        return False
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return False
    loss_stop = float(getattr(settings, "daily_loss_stop_inr", 0) or 0)
    if loss_stop <= 0:
        return False
    session_pnl = compute_session_pnl(state)
    if session_pnl > -abs(loss_stop):
        return False
    return snapshots_have_expiring_top_trade_signal(snapshots)


def candidate_qualifies_expiry_daily_loss_stop_bypass(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Per-candidate gate when daily loss stop is lifted for expiry top trades only."""
    settings = get_settings()
    if not getattr(settings, "expiry_daily_loss_stop_bypass_enabled", True):
        return False
    if getattr(settings, "expiry_daily_loss_stop_bypass_same_day_only", True):
        sym = str(getattr(candidate, "symbol", "") or "").upper()
        snap = snapshots.get(sym) or getattr(candidate, "snap", None)
        if snap is None or not is_symbol_expiry_day(snap):
            return False
    from app.engines.top_signal_session_lift import candidate_qualifies_top_signal_session_lift

    return candidate_qualifies_top_signal_session_lift(candidate)


def expiry_daily_loss_recovery_rank_adjustment(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> float:
    """Extra rank for same-day expiry top trades when daily loss stop bypass is live."""
    if not expiry_daily_loss_stop_bypass_active(state, snapshots):
        return 0.0
    if not candidate_qualifies_expiry_daily_loss_stop_bypass(candidate, snapshots):
        return 0.0
    settings = get_settings()
    return float(
        getattr(settings, "expiry_daily_loss_recovery_rank_bonus", 35.0) or 35.0
    )


def candidate_is_expiry_deep_itm_trade(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
    *,
    power_hour_only: bool = False,
) -> bool:
    """Expiring-symbol deep ITM candidate (PM ITM / power-hour close vertical)."""
    settings = get_settings()
    if not getattr(settings, "expiry_afternoon_deep_itm_routing_enabled", True):
        return False
    if power_hour_only and not getattr(settings, "expiry_power_hour_deep_itm_enabled", True):
        return False
    if not is_expiry_session(snapshots):
        return False

    sym = str(getattr(candidate, "symbol", "") or "").upper()
    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None or not is_symbol_expiry_day(snap):
        return False

    min_steps = int(getattr(settings, "expiry_afternoon_deep_itm_min_steps", 2) or 2)
    if _candidate_itm_depth(candidate, snap) < min_steps:
        return False

    mode = str(getattr(candidate, "mode", "") or "")
    if mode not in _expiry_deep_itm_pm_modes():
        return False

    if power_hour_only:
        return in_expiry_power_hour_deep_itm_context(snapshots)

    from app.engines.expiry_day_guards import (
        expiry_pm_itm_quick_active,
        in_expiry_afternoon_window,
    )
    from app.engines.power_hour_guards import in_power_hour_window

    return (
        in_expiry_afternoon_window()
        or in_power_hour_window()
        or expiry_pm_itm_quick_active(snap, None, snapshots)
    )


def expiring_symbol_has_deep_itm_heatmap(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """True when an expiring index heatmap shows tradeable deep ITM premium."""
    if not expiry_afternoon_deep_itm_routing_active(snapshots):
        return False
    return _scan_expiring_deep_itm_heatmap(snapshots)


def is_cross_index_expiry_afternoon_explosion(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Non-expiring index explosion during expiry-session afternoon routing."""
    if not expiry_afternoon_deep_itm_routing_active(snapshots):
        return False
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False
    sym = candidate.symbol.upper()
    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None or is_symbol_expiry_day(snap):
        return False
    return True


def expiry_afternoon_deep_itm_rank_adjustment(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> float:
    """Boost expiring-symbol deep ITM; penalize cross-index afternoon explosions."""
    _ = state
    settings = get_settings()
    if not expiry_afternoon_deep_itm_routing_active(snapshots):
        return 0.0

    bonus = 0.0
    if is_expiry_deep_itm_candidate(candidate, snapshots):
        bonus += float(
            getattr(settings, "expiry_afternoon_deep_itm_rank_bonus", 50.0) or 50.0
        )
        if in_expiry_power_hour_deep_itm_context(snapshots):
            bonus += float(
                getattr(settings, "expiry_power_hour_deep_itm_rank_bonus", 35.0) or 35.0
            )
    elif is_cross_index_expiry_afternoon_explosion(candidate, snapshots):
        if expiring_symbol_has_deep_itm_heatmap(snapshots):
            bonus -= float(
                getattr(settings, "expiry_afternoon_cross_index_explosion_penalty", 45.0)
                or 45.0
            )
    return bonus


def check_expiry_afternoon_cross_index_explosion(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """Hard block cross-index explosion when expiring symbol has deep ITM available."""
    _ = state
    settings = get_settings()
    meta: dict[str, Any] = {"expiryAfternoonDeepItmRouting": True}
    if not getattr(settings, "expiry_afternoon_cross_index_explosion_block_enabled", True):
        return True, "ok", meta
    if not is_cross_index_expiry_afternoon_explosion(candidate, snapshots):
        return True, "ok", meta
    if not expiring_symbol_has_deep_itm_heatmap(snapshots):
        return True, "ok", meta

    from app.engines.grade_a_ftv_capture import is_grade_a_ftv_first_lift_candidate
    from app.engines.top_ftv_v_expiry_bypass import is_top_ftv_or_v_candidate

    if is_grade_a_ftv_first_lift_candidate(candidate) or is_top_ftv_or_v_candidate(candidate):
        meta["expiryAfternoonCrossIndexBypass"] = "ftv"
        return True, "ok", meta

    event = getattr(candidate, "explosion_event", None)
    score = float(getattr(event, "explosion_score", 0) or 0) if event else float(
        getattr(candidate, "score", 0) or 0
    )
    move = _candidate_session_move(candidate)
    min_score = float(
        getattr(settings, "expiry_afternoon_cross_index_explosion_bypass_min_score", 95.0)
        or 95.0
    )
    min_move = float(
        getattr(settings, "expiry_afternoon_cross_index_explosion_bypass_min_move_pct", 120.0)
        or 120.0
    )
    meta["crossIndexExplosionScore"] = score
    meta["crossIndexSessionMovePct"] = move
    if score >= min_score and move >= min_move:
        meta["expiryAfternoonCrossIndexBypass"] = "extreme_rip"
        return True, "ok", meta
    return False, "expiry_afternoon_prefer_expiring_deep_itm", meta


def cross_index_rank_adjustment(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> float:
    """Nearest expiry index #1, same-week next #2 — flips Tue NIFTY ↔ Thu SENSEX."""
    settings = get_settings()
    if not settings.bad_day_routing_enabled:
        return 0.0

    fading_map = fading_expiry_symbols(state, snapshots)
    sym = candidate.symbol.upper()
    snap = snapshots.get(sym) or candidate.snap
    bonus = 0.0

    if getattr(settings, "expiry_day_prefer_same_day_enabled", True):
        nearest, nxt = expiry_proximity_ranks(snapshots)
        if not nearest and not nxt and not fading_map:
            return 0.0
        if sym in nearest:
            bonus += float(getattr(settings, "expiry_day_symbol_rank_bonus", 22.0) or 22.0)
            if sym in fading_map:
                from app.engines.best_side_selection import best_side_fading_rank_waive

                bonus -= settings.bad_day_fading_symbol_penalty
                bonus += best_side_fading_rank_waive(candidate, snap)
            return bonus
        if sym in nxt:
            bonus += float(
                getattr(settings, "expiry_day_same_week_next_rank_bonus", 12.0) or 12.0
            )
            return bonus
        # Far index: only boost if nearest expiry index is fading hard.
        if fading_map and any(s in fading_map for s in nearest):
            for restricted_sym in nearest:
                if restricted_sym not in fading_map:
                    continue
                alt = alternate_index_for(restricted_sym, snapshots)
                if alt and sym == alt:
                    fading_snap = snapshots.get(restricted_sym)
                    if fading_snap and float(snap.tradeQualityScore or 0) >= float(
                        fading_snap.tradeQualityScore or 0
                    ) - 5:
                        bonus += settings.bad_day_alternate_index_bonus
                    if _breadth_aligned(candidate, snap):
                        bonus += settings.bad_day_alternate_aligned_bonus
        return bonus

    # Legacy: demote near-expiry / boost alternate (prefer flag off).
    today_ex = set(expiry_symbols(snapshots))
    near = near_expiry_symbols(snapshots)
    tomorrow_only = [s for s in near if s not in today_ex]
    if not fading_map and not near:
        return 0.0
    restricted = set(fading_map.keys()) | set(tomorrow_only) | today_ex
    for restricted_sym in restricted:
        alt = alternate_index_for(restricted_sym, snapshots)
        if sym == restricted_sym:
            if restricted_sym in fading_map:
                from app.engines.best_side_selection import best_side_fading_rank_waive

                bonus -= settings.bad_day_fading_symbol_penalty
                bonus += best_side_fading_rank_waive(candidate, snap)
            elif settings.pre_expiry_cross_index_enabled:
                bonus -= settings.pre_expiry_symbol_rank_penalty
            continue
        if alt and sym == alt:
            fading_snap = snapshots.get(restricted_sym)
            if fading_snap and float(snap.tradeQualityScore or 0) >= float(
                fading_snap.tradeQualityScore or 0
            ) - 5:
                bonus += settings.bad_day_alternate_index_bonus
            if _breadth_aligned(candidate, snap):
                bonus += settings.bad_day_alternate_aligned_bonus
    return bonus


def _hottest_elite_rip(
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[float, str, str]:
    """Best ELITE session move across all indices."""
    best_move = 0.0
    best_sym = ""
    best_side = ""
    for sym, snap in snapshots.items():
        for alert in snap.explosionAlerts or []:
            if str(alert.get("tier") or "").upper() != "ELITE":
                continue
            move = max(
                float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
                float(alert.get("peakMovePct") or 0),
            )
            score = float(alert.get("explosionScore") or 0)
            rank = move + score * 0.05
            if rank > best_move:
                best_move = rank
                best_sym = sym.upper()
                best_side = str(alert.get("side") or "").upper()
    return best_move, best_sym, best_side


def cross_index_elite_priority_bonus(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> float:
    """
    Prefer the hottest ELITE rip on an alternate index (e.g. NIFTY 24400 CE)
    over weaker setups on the other index.
    """
    settings = get_settings()
    if expiry_afternoon_deep_itm_routing_active(snapshots):
        sym = candidate.symbol.upper()
        snap = snapshots.get(sym) or getattr(candidate, "snap", None)
        if snap is not None and not is_symbol_expiry_day(snap):
            return 0.0
    if not getattr(settings, "cross_index_elite_priority_enabled", True):
        return 0.0
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return 0.0
    event = getattr(candidate, "explosion_event", None)
    if event is None:
        return 0.0
    tier = str(getattr(event, "tier", "") or "").upper()
    if tier != "ELITE":
        return 0.0

    session_move = max(
        float(getattr(event, "daily_move_pct", 0) or 0),
        float(getattr(event, "peak_move_pct", 0) or 0),
    )
    min_move = float(getattr(settings, "cross_index_elite_min_session_move_pct", 40.0) or 40.0)
    if session_move < min_move:
        return 0.0

    hot_rank, hot_sym, hot_side = _hottest_elite_rip(snapshots)
    if not hot_sym or hot_sym != candidate.symbol.upper():
        return 0.0
    side_val = candidate.side.value if hasattr(candidate.side, "value") else str(candidate.side).upper()
    if hot_side and hot_side != side_val:
        return 0.0

    score = float(getattr(event, "explosion_score", 0) or 0)
    if score < 90:
        return 0.0

    base = float(getattr(settings, "cross_index_elite_priority_bonus", 22.0) or 22.0)
    return min(base + 8, base + session_move * 0.12)


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
    nearest, nxt = expiry_proximity_ranks(snapshots)
    prefer_near = bool(getattr(settings, "expiry_day_prefer_same_day_enabled", True))
    # When near-expiry is priority, do NOT advertise near→far alternates (misleading
    # Aug12 SENSEX→NIFTY stand-down). Only list alternates for fading nearest expiry.
    if prefer_near:
        pre_alts = {
            sym: alternate_index_for(sym, snapshots)
            for sym in fading.keys()
            if alternate_index_for(sym, snapshots)
        }
    else:
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
        "nearExpiryPriority": nearest if prefer_near else [],
        "sameWeekNextSymbols": nxt if prefer_near else [],
        "preExpiryAlternates": pre_alts,
        "alternateIndex": alts,
        "pmItmAlternateSymbols": pm_alts,
        "expiryAfternoonDeepItmRouting": expiry_afternoon_deep_itm_routing_active(snapshots),
        "expiringSymbolDeepItmHeatmap": expiring_symbol_has_deep_itm_heatmap(snapshots),
        "expiringDeepItmPowerHourSetup": snapshots_have_expiring_deep_itm_power_hour_setup(
            snapshots,
        ),
        "expiringTopTradeSignal": snapshots_have_expiring_top_trade_signal(snapshots),
        "dailyLossStopExpiryTopBypass": expiry_daily_loss_stop_bypass_active(
            state, snapshots,
        ),
        "sessionPnlInr": round(compute_session_pnl(state), 2),
    }
