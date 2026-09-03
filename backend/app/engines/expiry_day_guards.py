"""Expiry-day playbook — fewer trades, morning focus, worst-day prediction, dual CE/PE scalp."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.capital_allocator import compute_session_pnl
from app.engines.chop_day_guards import is_chop_session
from app.engines.pretrade_validator import collect_session_trades, compute_symbol_stats
from app.engines.whipsaw_guards import is_bearish_sideways_session
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _minutes_now() -> int:
    now = datetime.now(IST)
    return now.hour * 60 + now.minute


def _today_str() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _tomorrow_str() -> str:
    today_dt = datetime.strptime(_today_str(), "%Y-%m-%d").replace(tzinfo=IST)
    return (today_dt + timedelta(days=1)).strftime("%Y-%m-%d")


def is_symbol_expiry_day(snap: SymbolSnapshot) -> bool:
    """True when today's session date matches the option chain expiry."""
    settings = get_settings()
    if not settings.expiry_day_guards_enabled:
        return False
    if not snap.dataAvailable or not snap.optionExpiry:
        return False
    expiry = str(snap.optionExpiry)[:10]
    return expiry == _today_str()


def expiry_itm_monitor_active(snap: SymbolSnapshot | None = None) -> bool:
    """
    Expiry-day ITM CE+PE coverage mode — widen scan/depth so most ITM strikes
    on both sides stay on radar (not just ATM ±2).
    """
    settings = get_settings()
    if not bool(getattr(settings, "expiry_itm_monitor_enabled", True)):
        return False
    if snap is not None:
        return is_symbol_expiry_day(snap)
    return any_expiry_session_active()


def expiry_itm_max_steps() -> int:
    settings = get_settings()
    base = int(getattr(settings, "moneyness_max_itm_steps", 2) or 2)
    if not bool(getattr(settings, "expiry_itm_monitor_enabled", True)):
        return base
    return max(base, int(getattr(settings, "expiry_max_itm_steps", 6) or 6))


def resolve_expiry_itm_scan_range(symbol: str) -> float:
    """ATM ± range wide enough to cover expiry_max_itm_steps on both CE and PE."""
    settings = get_settings()
    if symbol.upper() == "SENSEX":
        return float(getattr(settings, "expiry_sensex_itm_scan_range", 1200) or 1200)
    return float(getattr(settings, "expiry_itm_scan_range", 800) or 800)


_expiry_session_active: bool = False


def refresh_expiry_session(snapshots: dict[str, SymbolSnapshot]) -> None:
    """Cache expiry-session flag for fast entry-scan cadence without snapshot coupling."""
    global _expiry_session_active
    _expiry_session_active = is_expiry_session(snapshots)


def any_expiry_session_active() -> bool:
    return _expiry_session_active


def expiry_symbols(snapshots: dict[str, SymbolSnapshot]) -> list[str]:
    return [sym.upper() for sym, snap in snapshots.items() if is_symbol_expiry_day(snap)]


def near_expiry_symbols(snapshots: dict[str, SymbolSnapshot]) -> list[str]:
    """Symbols whose chain expires today or tomorrow (pre-expiry + expiry session)."""
    return [sym.upper() for sym, snap in snapshots.items() if is_near_expiry_day(snap)]


def is_pre_expiry_day(snap: SymbolSnapshot) -> bool:
    """True when chain expires tomorrow only — not yet expiry day."""
    if not snap.dataAvailable or not snap.optionExpiry:
        return False
    expiry = str(snap.optionExpiry)[:10]
    return expiry == _tomorrow_str()


def is_expiry_session(snapshots: dict[str, SymbolSnapshot]) -> bool:
    return len(expiry_symbols(snapshots)) > 0


def in_expiry_afternoon_window() -> bool:
    """After expiry morning focus — Sep03 post-win FOMO trap landed ~13:45."""
    settings = get_settings()
    if not settings.expiry_day_guards_enabled:
        return False
    morning_end = (
        settings.expiry_morning_end_hour * 60 + settings.expiry_morning_end_minute
    )
    return _minutes_now() >= morning_end


def session_post_small_win(state: AutoTraderState | None) -> tuple[bool, dict[str, Any]]:
    """Small closed winner — post-win FOMO sizing risk (shared with fake-trap guards)."""
    if state is None:
        return False, {}
    from app.engines.explosion_entry_guards import _post_small_win

    return _post_small_win(state)


def expiry_post_win_afternoon_fomo_risk(
    state: AutoTraderState | None,
    *,
    require_post_win: bool = True,
) -> tuple[bool, list[str]]:
    """
    Sep03 pattern: SENSEX expiry session, morning WORST scalp won, afternoon
    day-type flipped GOOD/AGGRESSIVE → 38-lot post-win explosion trap on NIFTY.

    Uses session-level expiry (any symbol expiring today), not per-symbol expiry.
    """
    settings = get_settings()
    if not settings.expiry_day_guards_enabled:
        return False, []
    if not any_expiry_session_active():
        return False, []
    if not in_expiry_afternoon_window():
        return False, []
    reasons = ["expiry_session", "expiry_afternoon"]
    if require_post_win:
        post_win, meta = session_post_small_win(state)
        if not post_win:
            return False, []
        reasons.append("post_small_win")
        if meta.get("lastPnlInr") is not None:
            reasons.append(f"last_pnl_{meta['lastPnlInr']:.0f}")
    return True, reasons


def _candidate_explosion_score(candidate: Any) -> float:
    event = getattr(candidate, "explosion_event", None)
    if event is not None:
        return float(getattr(event, "explosion_score", 0) or 0)
    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        return float(alert.get("explosionScore") or 0)
    return float(getattr(candidate, "score", 0) or 0)


def _candidate_velocity_3s(candidate: Any) -> float:
    event = getattr(candidate, "explosion_event", None)
    if event is not None:
        return float(getattr(event, "velocity_3s", 0) or 0)
    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        return float(alert.get("velocity3s") or alert.get("velocity_3s") or 0)
    return 0.0


def _candidate_explosion_tier(candidate: Any) -> str:
    event = getattr(candidate, "explosion_event", None)
    tier = str(
        getattr(event, "tier", None)
        or getattr(candidate, "tier", "")
        or ""
    ).upper()
    if tier:
        return tier
    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        return str(alert.get("tier") or "").upper()
    return ""


def check_expiry_afternoon_explosion_confirmation(
    candidate: Any,
    state: AutoTraderState | None = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Small confirmation lift after expiry morning — ELITE vs EXPLODING tiers.

    Session-level (any index expiring today), so cross-index NIFTY entries on
    SENSEX expiry afternoons are covered. Sep03 loss: EXPLODING 80.5 / v3 2.62.
    """
    settings = get_settings()
    meta: dict[str, Any] = {"expiryAfternoonConfirm": False}
    if not getattr(settings, "expiry_afternoon_explosion_confirm_enabled", True):
        return True, "ok", meta
    if not settings.expiry_day_guards_enabled:
        return True, "ok", meta
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return True, "ok", meta
    if not any_expiry_session_active():
        return True, "ok", meta
    if not in_expiry_afternoon_window():
        return True, "ok", meta

    tier = _candidate_explosion_tier(candidate)
    if tier not in ("ELITE", "EXPLODING"):
        return True, "ok", meta

    # Already-confirmed top signals carry their own proof — skip the generic lift.
    if snapshots is not None and state is not None:
        from app.engines.grade_a_ftv_capture import is_grade_a_ftv_first_lift_candidate
        from app.engines.top_ftv_v_expiry_bypass import is_top_ftv_or_v_candidate

        if is_expiry_elite_top_candidate(candidate):
            meta["expiryAfternoonConfirmBypass"] = "elite_top"
            return True, "ok", meta
        if is_grade_a_ftv_first_lift_candidate(candidate):
            meta["expiryAfternoonConfirmBypass"] = "grade_a_ftv"
            return True, "ok", meta
        if is_top_ftv_or_v_candidate(candidate):
            meta["expiryAfternoonConfirmBypass"] = "top_ftv_v"
            return True, "ok", meta

    score = _candidate_explosion_score(candidate)
    v3 = _candidate_velocity_3s(candidate)
    meta["expiryAfternoonConfirm"] = True
    meta["expiryAfternoonTier"] = tier
    meta["expiryAfternoonScore"] = round(score, 2)
    meta["expiryAfternoonVelocity3s"] = round(v3, 3)

    if tier == "ELITE":
        min_score = float(
            getattr(settings, "expiry_afternoon_elite_min_explosion_score", 85.0) or 85.0
        )
        min_v3 = float(
            getattr(settings, "expiry_afternoon_elite_min_velocity_3s", 2.5) or 2.5
        )
    else:
        min_score = float(
            getattr(settings, "expiry_afternoon_exploding_min_explosion_score", 90.0) or 90.0
        )
        min_v3 = float(
            getattr(settings, "expiry_afternoon_exploding_min_velocity_3s", 3.0) or 3.0
        )
    meta["expiryAfternoonMinScore"] = min_score
    meta["expiryAfternoonMinVelocity3s"] = min_v3

    if score < min_score:
        return False, f"expiry_afternoon_{tier.lower()}_score_below_{min_score:.0f}", meta
    if v3 < min_v3:
        return False, f"expiry_afternoon_{tier.lower()}_v3_below_{min_v3:g}", meta
    return True, "ok", meta


def is_near_expiry_day(snap: SymbolSnapshot) -> bool:
    """True when chain expiry is today or tomorrow (pre-expiry + expiry session)."""
    if not snap.dataAvailable or not snap.optionExpiry:
        return False
    expiry = str(snap.optionExpiry)[:10]
    return expiry in (_today_str(), _tomorrow_str())


def in_expiry_pm_itm_window() -> bool:
    """14:00–15:30 IST window for small ITM quick scalps near expiry."""
    from app.services.upstox import get_market_phase

    settings = get_settings()
    if not settings.expiry_pm_itm_quick_enabled or get_market_phase() != "LIVE_MARKET":
        return False
    current = _minutes_now()
    start = settings.expiry_pm_itm_window_start_hour * 60 + settings.expiry_pm_itm_window_start_minute
    end = settings.expiry_pm_itm_window_end_hour * 60 + settings.expiry_pm_itm_window_end_minute
    return start <= current < end


def expiry_pm_itm_quick_active(
    snap: SymbolSnapshot,
    state: AutoTraderState | None = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> bool:
    if not in_expiry_pm_itm_window():
        return False
    if is_near_expiry_day(snap):
        return True
    if state is not None and snapshots is not None:
        from app.engines.bad_day_routing import pm_itm_alternate_symbol_active

        return pm_itm_alternate_symbol_active(snap, state, snapshots)
    return False


def in_morning_slow_bounce_window() -> bool:
    """10:30–13:30 IST — post-open consolidation bounces on near-expiry ITM."""
    from app.services.upstox import get_market_phase

    settings = get_settings()
    if not settings.morning_slow_bounce_enabled or get_market_phase() != "LIVE_MARKET":
        return False
    current = _minutes_now()
    start = settings.morning_slow_bounce_start_hour * 60 + settings.morning_slow_bounce_start_minute
    end = settings.morning_slow_bounce_end_hour * 60 + settings.morning_slow_bounce_end_minute
    return start <= current < end


def slow_bounce_premium_max_inr(snap: SymbolSnapshot) -> float:
    """Higher cap on near-expiry days (e.g. SENSEX 77600 PE at ₹216)."""
    settings = get_settings()
    if is_near_expiry_day(snap):
        return settings.expiry_near_expiry_premium_max_inr
    return settings.expiry_pm_itm_premium_max_inr


def slow_bounce_session_active(
    snap: SymbolSnapshot,
    state: AutoTraderState | None = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> bool:
    """PM ITM window (14:00+) or morning consolidation window on near-expiry."""
    if expiry_pm_itm_quick_active(snap, state, snapshots):
        return True
    if in_morning_slow_bounce_window() and is_near_expiry_day(snap):
        return True
    return False


def slow_bounce_session_active_any(
    snapshots: dict[str, SymbolSnapshot],
    state: AutoTraderState | None = None,
) -> bool:
    if expiry_pm_itm_quick_session_active(snapshots, state):
        return True
    if not in_morning_slow_bounce_window():
        return False
    return any(is_near_expiry_day(s) for s in snapshots.values() if s.dataAvailable)


def expiry_pm_itm_quick_session_active(
    snapshots: dict[str, SymbolSnapshot],
    state: AutoTraderState | None = None,
) -> bool:
    if not in_expiry_pm_itm_window():
        return False
    if any(is_near_expiry_day(s) for s in snapshots.values() if s.dataAvailable):
        return True
    if state is not None:
        from app.engines.bad_day_routing import pm_itm_alternate_symbols

        return bool(pm_itm_alternate_symbols(state, snapshots))
    return False


def expiry_pm_itm_chart_bypass_allowed(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    mode: str = "",
    state: AutoTraderState | None = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> bool:
    """Allow ITM quick scalps through opposite 5m chart when breadth aligns (PM expiry window)."""
    settings = get_settings()
    if not settings.expiry_pm_itm_chart_bypass_breadth:
        return False
    if str(mode or "") not in ("quick_sideways", "slow_bounce", "worst_day_itm_fade"):
        return False
    if not expiry_pm_itm_quick_active(snap, state, snapshots) and not (
        in_morning_slow_bounce_window() and is_near_expiry_day(snap)
    ):
        return False
    return _breadth_aligned_for_side(side, snap.breadth)


def in_expiry_morning_window() -> bool:
    """Preferred entry window on expiry — before afternoon theta crush."""
    settings = get_settings()
    current = _minutes_now()
    start = settings.entry_earliest_hour * 60 + settings.entry_earliest_minute
    end = settings.expiry_morning_end_hour * 60 + settings.expiry_morning_end_minute
    return start <= current < end


def in_expiry_explosion_open_block() -> bool:
    """First N minutes after entry window on expiry — block noisy EXPLODING opens."""
    from app.services.upstox import get_market_phase

    settings = get_settings()
    if not settings.expiry_day_guards_enabled or get_market_phase() != "LIVE_MARKET":
        return False
    start = settings.entry_earliest_hour * 60 + settings.entry_earliest_minute
    end = start + settings.expiry_explosion_open_block_minutes
    return start <= _minutes_now() < end


def _breadth_aligned_for_side(side: Side | str, breadth: Any) -> bool:
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    side_bias = "BULLISH" if side_val == "CALL" else "BEARISH"
    bias = (getattr(breadth, "bias", None) or "NEUTRAL")
    if hasattr(bias, "upper"):
        bias = bias.upper()
    else:
        bias = str(bias).upper()
    aligned = bool(getattr(breadth, "aligned", False))
    return aligned or bias == side_bias


def check_expiry_explosion_open_block(
    *,
    snap: SymbolSnapshot,
    tier: str,
    side: Side | str,
    breadth: Any,
) -> tuple[bool, str]:
    """
    On expiry, block EXPLODING tier in the first minutes after open.
    ELITE + breadth-aligned legs may still enter.
    Returns (blocked, reason).
    """
    if not is_symbol_expiry_day(snap):
        return False, "ok"
    if not in_expiry_explosion_open_block():
        return False, "ok"
    tier_u = str(tier or "").upper()
    if tier_u == "ELITE" and _breadth_aligned_for_side(side, breadth):
        return False, "ok"
    if tier_u in ("EXPLODING", "BUILDING"):
        return True, "expiry_open_block_exploding"
    return False, "ok"


def in_expiry_evening_block() -> bool:
    """Optional hard stop for expiry entries — default off through market close."""
    settings = get_settings()
    if not settings.expiry_day_guards_enabled:
        return False
    if not getattr(settings, "expiry_evening_block_enabled", False):
        return False
    current = _minutes_now()
    block_from = settings.expiry_evening_block_hour * 60 + settings.expiry_evening_block_minute
    return current >= block_from


def snapshots_have_afternoon_top_signal(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Alias — expiry evening bypass uses the same top-signal detector."""
    from app.engines.power_hour_guards import snapshots_have_power_hour_top_signal

    return snapshots_have_power_hour_top_signal(snapshots)


def _session_declining(state: AutoTraderState, snapshots: dict[str, SymbolSnapshot]) -> bool:
    """Session PnL bleeding + bearish sideways — hard to make money trending."""
    settings = get_settings()
    session_pnl = compute_session_pnl(state)
    if session_pnl <= settings.expiry_decline_session_loss_inr:
        return True
    trades = collect_session_trades(state)
    if len(trades) >= 3:
        stats = compute_symbol_stats(trades)
        net = sum(s.net_pnl_inr for s in stats.values())
        if net <= settings.expiry_decline_session_loss_inr:
            return True
    if is_bearish_sideways_session(snapshots):
        declining = 0
        for snap in snapshots.values():
            if not snap.dataAvailable or not snap.spotChart:
                continue
            mom = float(snap.spotChart.momentum5Pct or 0)
            if mom < -0.03:
                declining += 1
        live = sum(1 for s in snapshots.values() if s.dataAvailable)
        if live and declining >= max(1, live // 2):
            return True
    return False


def predict_worst_expiry_day(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, float, list[str]]:
    """
    Predict a worst expiry chop day before taking more risk.
    Returns (is_worst, score 0-100, human reasons).
    """
    settings = get_settings()
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return False, 0.0, []

    score = 0.0
    reasons: list[str] = []

    if is_chop_session(snapshots):
        score += 25
        reasons.append("chop_regime")
    if is_bearish_sideways_session(snapshots):
        score += 25
        reasons.append("bearish_sideways")
    session_pnl = compute_session_pnl(state)
    if session_pnl <= settings.expiry_worst_day_session_loss_inr:
        score += 20
        reasons.append(f"session_loss_{session_pnl:.0f}")
    trades = collect_session_trades(state)
    if len(trades) >= 2:
        losses = sum(1 for t in trades if t.pnl_inr < 0)
        if losses >= settings.expiry_worst_day_loss_count:
            score += 15
            reasons.append(f"loss_cluster_{losses}")
    if _session_declining(state, snapshots):
        score += 15
        reasons.append("declining_session")
    if in_expiry_evening_block():
        score += 10
        reasons.append("expiry_evening")

    is_worst = score >= settings.expiry_worst_day_score_threshold
    return is_worst, round(score, 1), reasons


def expiry_trade_cap(state: AutoTraderState, snapshots: dict[str, SymbolSnapshot]) -> tuple[int, str]:
    settings = get_settings()
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return 999, "normal"
    is_worst, _, _ = predict_worst_expiry_day(state, snapshots)
    if is_worst:
        return settings.expiry_worst_day_max_trades, "expiry_worst"
    return settings.expiry_max_trades_per_day, "expiry_day"


def expiry_trades_cap_reached(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str]:
    from app.engines.session_trade_integrity import real_session_closed_count

    cap, label = expiry_trade_cap(state, snapshots)
    closed = real_session_closed_count(state)
    if closed >= cap:
        return True, f"expiry_trade_cap_{closed}>={cap}_{label}"
    return False, "ok"


def expiry_min_rank_score(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> float:
    settings = get_settings()
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return 0.0
    is_worst, _, _ = predict_worst_expiry_day(state, snapshots)
    if is_worst:
        return settings.expiry_worst_day_min_rank_score
    return settings.expiry_min_rank_score


def expiry_elite_top_tiers() -> set[str]:
    settings = get_settings()
    raw = str(getattr(settings, "expiry_worst_day_elite_top_tiers_csv", "ELITE") or "ELITE")
    return {t.strip().upper() for t in raw.split(",") if t.strip()}


def _alert_session_move(alert: dict[str, Any]) -> float:
    return max(
        float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
        float(alert.get("peakMovePct") or 0),
    )


def _elite_top_move_ok(
    move: float,
    min_move: float,
    max_move: float,
    *,
    flat_then_vertical: bool = False,
    base_relative_move: float = 0.0,
) -> bool:
    """Move gate for the expiry worst-day elite-top halt bypass.

    A fast flat→vertical base rip blows past the off-the-low ceiling before ELITE
    confirms; for a confirmed flat→vertical break also accept on the base-relative
    move (distance from the consolidation base) so a genuine base rip still lifts the
    worst-day halt. Mirrors the sizing + extended-chase entry-guard base-relative
    bypass. Purely additive — only widens acceptance, never removes it.
    """
    if min_move <= move <= max_move:
        return True
    if flat_then_vertical and min_move <= float(base_relative_move or 0) <= max_move:
        return True
    return False


def alert_is_expiry_elite_top(alert: dict[str, Any], snap: Optional[SymbolSnapshot] = None) -> bool:
    """True for early-window ELITE rips worth lifting the expiry-worst halt."""
    settings = get_settings()
    if not getattr(settings, "expiry_worst_day_elite_top_bypass_enabled", True):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in expiry_elite_top_tiers():
        return False
    score = float(alert.get("explosionScore") or 0)
    min_score = float(getattr(settings, "expiry_worst_day_elite_top_min_score", 70.0) or 70.0)
    if score < min_score:
        return False
    move = _alert_session_move(alert)
    min_move = float(getattr(settings, "expiry_worst_day_elite_top_min_move_pct", 28.0) or 28.0)
    max_move = float(getattr(settings, "expiry_worst_day_elite_top_max_move_pct", 55.0) or 55.0)
    if not _elite_top_move_ok(
        move,
        min_move,
        max_move,
        flat_then_vertical=bool(alert.get("ictFlatThenVertical")),
        base_relative_move=float(alert.get("ictBaseRelativeMovePct") or 0),
    ):
        return False
    prem = alert.get("premium")
    from app.engines.premium_filter import premium_in_band

    if not premium_in_band(prem, mode="explosion", peak_move_pct=move):
        return False
    if snap is not None and snap.spotChart:
        from app.engines.spot_direction import side_aligned_with_chart

        side = str(alert.get("side") or "").upper()
        if side in ("CALL", "PUT") and not side_aligned_with_chart(side, snap.spotChart):
            breadth = str(snap.breadth.bias if snap.breadth else "NEUTRAL").upper()
            if not (
                (side == "CALL" and breadth == "BULLISH")
                or (side == "PUT" and breadth == "BEARISH")
            ):
                return False
    return True


def snapshots_have_expiry_elite_top(snapshots: dict[str, SymbolSnapshot]) -> bool:
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            if alert_is_expiry_elite_top(alert, snap):
                return True
    return False


def alert_is_early_pad_prelaunch_strict_launch(
    alert: dict[str, Any],
    snap: SymbolSnapshot,
) -> bool:
    """Prelaunch pad at local base before armed_base_launch stamps (Aug27 PUT 77300)."""
    settings = get_settings()
    if not bool(getattr(settings, "early_radar_pad_capture_enabled", True)):
        return False
    from app.engines.early_radar_pad_capture import (
        alert_has_early_radar_pad_capture,
        early_radar_pad_shallow_otm_ok,
    )

    if not alert_has_early_radar_pad_capture(alert):
        return False
    if not bool(alert.get("tradeable")):
        return False
    if not bool(alert.get("ictBaseArmed")):
        return False
    if bool(alert.get("ictArmedBaseLaunch")):
        return False
    if not bool(alert.get("ictFirstLift")):
        return False
    if str(alert.get("tier") or "").upper() not in ("EXPLODING", "ELITE"):
        return False
    if float(alert.get("explosionScore") or 0) < float(
        getattr(settings, "ict_armed_base_launch_min_score", 45.0) or 45.0
    ):
        return False
    if float(snap.tradeQualityScore or 0) < float(
        getattr(settings, "ict_armed_base_launch_min_tqs", 50.0) or 50.0
    ):
        return False
    samples = int(alert.get("ictArmedBaseSamples") or 0)
    span = float(alert.get("ictArmedBaseSpanSeconds") or 0)
    base_range = float(alert.get("ictArmedBaseRangePct") or 0)
    if (
        samples < int(getattr(settings, "ict_armed_base_min_samples", 6) or 6)
        or span < float(getattr(settings, "ict_armed_base_min_span_seconds", 15.0) or 15.0)
        or base_range
        > float(getattr(settings, "ict_armed_base_max_range_pct", 5.0) or 5.0)
    ):
        return False

    base_move = float(
        alert.get("ictBaseRelativeMovePct")
        or alert.get("localBaseMovePct")
        or 0
    )
    pad_min = float(getattr(settings, "ict_elite_base_ready_min_move_pct", 2.0) or 2.0)
    pad_max = float(getattr(settings, "early_radar_pad_max_local_move_pct", 20.0) or 20.0)
    if not (pad_min <= base_move <= pad_max + 1e-6):
        return False

    side = str(alert.get("side") or "").upper()
    strike = float(alert.get("strike") or 0)
    from app.engines.moneyness import atm_itm_entry_allows
    from app.models.schemas import Side

    if side not in ("CALL", "PUT") or strike <= 0:
        return False
    if not atm_itm_entry_allows(Side(side), strike, snap)[0]:
        if not early_radar_pad_shallow_otm_ok(alert, snap):
            return False

    timing = alert.get("timingAssessment") or {}
    timing_assessment = str(
        timing.get("assessment") if isinstance(timing, dict) else timing
    ).upper()
    timing_action = str(
        timing.get("action") if isinstance(timing, dict) else ""
    ).lower()
    if (
        alert.get("fadedRip")
        or alert.get("faded")
        or alert.get("exhaustedReentry")
        or timing_assessment in ("FAILED_LAUNCH", "FADING", "EXHAUSTED")
        or timing_action == "block"
    ):
        return False

    return bool(
        alert.get("ictVolumeAwakening")
        or alert.get("volumeAwaken")
        or alert.get("orderflowConfirmed")
        or alert.get("optionCvdBuying")
        or float(alert.get("volumeSurge") or 0) >= 1.2
        or alert.get("ictFlatThenVertical")
    )


def _shallow_otm_local_base_strict_rank_one_launch(
    alert: dict[str, Any],
    snap: SymbolSnapshot,
) -> bool:
    """#427 tradeable stamp — armed_base_launch at 1-step OTM local base (Aug27 PUT 77200)."""
    settings = get_settings()
    from app.engines.early_radar_pad_capture import early_radar_pad_shallow_otm_ok

    if not bool(alert.get("shallowOtmLocalBaseTradeable")):
        return False
    if not early_radar_pad_shallow_otm_ok(alert, snap):
        return False
    if not bool(alert.get("tradeable")):
        return False
    if not bool(alert.get("ictBaseArmed")) or not bool(alert.get("ictArmedBaseLaunch")):
        return False
    if str(alert.get("tier") or "").upper() not in ("EXPLODING", "ELITE"):
        return False
    if float(alert.get("explosionScore") or 0) < float(
        getattr(settings, "ict_armed_base_launch_min_score", 45.0) or 45.0
    ):
        return False
    min_tqs = float(
        getattr(settings, "shallow_otm_local_base_min_tqs", 45.0) or 45.0
    )
    if float(snap.tradeQualityScore or 0) < min_tqs:
        return False
    samples = int(alert.get("ictArmedBaseSamples") or 0)
    span = float(alert.get("ictArmedBaseSpanSeconds") or 0)
    base_range = float(alert.get("ictArmedBaseRangePct") or 0)
    if (
        samples < int(getattr(settings, "ict_armed_base_min_samples", 6) or 6)
        or span < float(getattr(settings, "ict_armed_base_min_span_seconds", 15.0) or 15.0)
        or base_range
        > float(getattr(settings, "ict_armed_base_max_range_pct", 5.0) or 5.0)
    ):
        return False
    base_move = float(
        alert.get("ictBaseRelativeMovePct")
        or alert.get("localBaseMovePct")
        or 0
    )
    min_lb = float(getattr(settings, "shallow_otm_local_base_min_move_pct", 2.0) or 2.0)
    max_lb = float(getattr(settings, "shallow_otm_local_base_max_move_pct", 25.0) or 25.0)
    if not (min_lb <= base_move <= max_lb + 1e-6):
        return False
    timing = alert.get("timingAssessment") or {}
    timing_assessment = str(
        timing.get("assessment") if isinstance(timing, dict) else timing
    ).upper()
    timing_action = str(
        timing.get("action") if isinstance(timing, dict) else ""
    ).lower()
    if (
        alert.get("fadedRip")
        or alert.get("faded")
        or alert.get("exhaustedReentry")
        or timing_assessment in ("FAILED_LAUNCH", "FADING", "EXHAUSTED")
        or timing_action == "block"
    ):
        return False
    orderflow = bool(
        alert.get("ictVolumeAwakening")
        or alert.get("volumeAwaken")
        or alert.get("orderflowConfirmed")
        or alert.get("optionCvdBuying")
        or float(alert.get("volumeSurge") or 0) >= 1.2
    )
    if not bool(alert.get("ictFlatThenVertical")) or not orderflow:
        return False
    from app.engines.trade_ranking import rank_trade_evidence

    ranking = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": alert.get("tier"),
            "explosionScore": alert.get("explosionScore"),
            "tqs": snap.tradeQualityScore,
            "velocity3s": alert.get("velocity3s"),
            "velocity9s": alert.get("velocity9s"),
            "localBaseMovePct": base_move,
            "armedBaseLaunch": True,
            "flatThenVertical": alert.get("ictFlatThenVertical"),
            "flatVerticalQuality": alert.get("flatVerticalQuality"),
            "orderflowPositive": orderflow,
            "shallowOtmLocalBaseTradeable": True,
        }
    )
    return str(ranking.get("grade") or "").upper() in ("S", "A")


def alert_is_strict_rank_one_launch(
    alert: dict[str, Any],
    snap: SymbolSnapshot,
) -> bool:
    """Whether one snapshot alert has enough causal proof to evaluate through the halt."""
    if alert_is_early_pad_prelaunch_strict_launch(alert, snap):
        return True
    if _shallow_otm_local_base_strict_rank_one_launch(alert, snap):
        return True
    if not bool(alert.get("tradeable")):
        return False
    if not bool(alert.get("ictBaseArmed")):
        return False
    armed_launch = bool(alert.get("ictArmedBaseLaunch"))
    elite_ready = bool(alert.get("ictEliteBaseReady"))
    if not (armed_launch or elite_ready):
        return False

    settings = get_settings()
    if str(alert.get("tier") or "").upper() not in ("EXPLODING", "ELITE"):
        return False
    if float(alert.get("explosionScore") or 0) < float(
        getattr(settings, "ict_armed_base_launch_min_score", 45.0) or 45.0
    ):
        return False
    if float(snap.tradeQualityScore or 0) < float(
        getattr(settings, "ict_armed_base_launch_min_tqs", 50.0) or 50.0
    ):
        return False
    samples = int(alert.get("ictArmedBaseSamples") or 0)
    span = float(alert.get("ictArmedBaseSpanSeconds") or 0)
    base_range = float(alert.get("ictArmedBaseRangePct") or 0)
    if (
        samples < int(getattr(settings, "ict_armed_base_min_samples", 6) or 6)
        or span < float(getattr(settings, "ict_armed_base_min_span_seconds", 15.0) or 15.0)
        or base_range
        > float(getattr(settings, "ict_armed_base_max_range_pct", 5.0) or 5.0)
    ):
        return False

    base_move = float(
        alert.get("ictBaseRelativeMovePct")
        or alert.get("localBaseMovePct")
        or 0
    )
    if elite_ready and not (
        float(getattr(settings, "ict_elite_base_ready_min_move_pct", 2.0) or 2.0)
        <= base_move
        < float(getattr(settings, "ict_elite_base_ready_max_move_pct", 5.0) or 5.0)
    ):
        return False
    if armed_launch and not (0 < base_move <= 40.0):
        return False

    side = str(alert.get("side") or "").upper()
    strike = float(alert.get("strike") or 0)
    from app.engines.moneyness import atm_itm_entry_allows
    from app.models.schemas import Side

    if side not in ("CALL", "PUT") or strike <= 0:
        return False
    from app.engines.early_radar_pad_capture import early_radar_pad_shallow_otm_ok

    shallow_otm_ok = early_radar_pad_shallow_otm_ok(alert, snap)
    if not atm_itm_entry_allows(Side(side), strike, snap)[0] and not shallow_otm_ok:
        return False

    timing = alert.get("timingAssessment") or {}
    timing_assessment = str(
        timing.get("assessment") if isinstance(timing, dict) else timing
    ).upper()
    timing_action = str(
        timing.get("action") if isinstance(timing, dict) else ""
    ).lower()
    if (
        alert.get("fadedRip")
        or alert.get("faded")
        or alert.get("exhaustedReentry")
        or timing_assessment in ("FAILED_LAUNCH", "FADING", "EXHAUSTED")
        or timing_action == "block"
    ):
        return False

    orderflow = bool(
        alert.get("ictVolumeAwakening")
        or alert.get("volumeAwaken")
        or alert.get("orderflowConfirmed")
        or alert.get("optionCvdBuying")
        or float(alert.get("volumeSurge") or 0) >= 1.2
    )
    from app.engines.trade_ranking import rank_trade_evidence

    ranking = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": alert.get("tier"),
            "explosionScore": alert.get("explosionScore"),
            "tqs": snap.tradeQualityScore,
            "velocity3s": alert.get("velocity3s"),
            "velocity9s": alert.get("velocity9s"),
            "localBaseMovePct": base_move,
            "firstLift": alert.get("ictFirstLift"),
            "eliteBaseReady": elite_ready,
            "armedBaseLaunch": armed_launch,
            "flatThenVertical": alert.get("ictFlatThenVertical"),
            "flatVerticalQuality": alert.get("flatVerticalQuality"),
            "orderflowPositive": orderflow,
            "timingAssessment": timing_assessment,
            "timingAction": timing_action,
            "exhaustedReentry": alert.get("exhaustedReentry"),
        }
    )
    return bool(
        ranking.get("grade") == "S"
        and ranking.get("topRankEligible")
        and (
            armed_launch
            or ranking.get("executionAuthorization") == "S_PREAUTHORIZED"
        )
    )


def snapshots_have_strict_rank_one_launch(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Snapshot-only session-halt escape; candidate gates still run afterward."""
    return any(
        alert_is_strict_rank_one_launch(alert, snap)
        for snap in snapshots.values()
        if snap.dataAvailable
        for alert in (snap.explosionAlerts or [])
    )


def snapshots_have_grade_a_ftv_first_lift(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    from app.engines.grade_a_ftv_capture import snapshots_have_grade_a_ftv_first_lift as _have

    return _have(snapshots)


def snapshots_have_top_ftv_or_v(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    from app.engines.top_ftv_v_expiry_bypass import snapshots_have_top_ftv_or_v as _have

    return _have(snapshots)


def is_expiry_elite_top_candidate(candidate: Any) -> bool:
    """Per-candidate elite-top check used under expiry-worst declining sessions."""
    settings = get_settings()
    if not getattr(settings, "expiry_worst_day_elite_top_bypass_enabled", True):
        return False
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False
    tier = str(getattr(candidate, "tier", "") or "").upper()
    alert = getattr(candidate, "alert", None) if isinstance(getattr(candidate, "alert", None), dict) else {}
    if not tier:
        tier = str(alert.get("tier") or "").upper()
    if tier not in expiry_elite_top_tiers():
        return False
    event = getattr(candidate, "explosion_event", None)
    score = float(
        getattr(candidate, "confidence", 0)
        or alert.get("explosionScore")
        or getattr(event, "explosion_score", 0)
        or 0
    )
    min_score = float(getattr(settings, "expiry_worst_day_elite_top_min_score", 70.0) or 70.0)
    if score < min_score:
        return False
    move = max(
        float(getattr(event, "daily_move_pct", 0) or 0) if event is not None else 0.0,
        float(getattr(event, "peak_move_pct", 0) or 0) if event is not None else 0.0,
        _alert_session_move(alert) if alert else 0.0,
    )
    min_move = float(getattr(settings, "expiry_worst_day_elite_top_min_move_pct", 28.0) or 28.0)
    max_move = float(getattr(settings, "expiry_worst_day_elite_top_max_move_pct", 55.0) or 55.0)
    # Confirmed flat→vertical base rip → also accept on base-relative move (from the alert,
    # else from the event's ICT analysis) so a fast rip past the off-low ceiling still lifts
    # the worst-day halt.
    snap_for_ict = getattr(candidate, "snap", None)
    flat_then_vertical = bool(alert.get("ictFlatThenVertical")) if alert else False
    base_rel_move = float(alert.get("ictBaseRelativeMovePct") or 0) if alert else 0.0
    if event is not None and (not flat_then_vertical or base_rel_move <= 0):
        try:
            from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

            ict = analyze_explosion_event_ict(event, snap_for_ict)
            if ict.active and ict.flat_then_vertical:
                flat_then_vertical = True
                base_rel_move = max(base_rel_move, float(ict.base_relative_move_pct or 0))
        except Exception:
            pass
    if not _elite_top_move_ok(
        move,
        min_move,
        max_move,
        flat_then_vertical=flat_then_vertical,
        base_relative_move=base_rel_move,
    ):
        return False
    prem = float(getattr(candidate, "premium", 0) or alert.get("premium") or 0)
    from app.engines.premium_filter import premium_in_band

    if not premium_in_band(prem, mode="explosion", peak_move_pct=move):
        return False
    snap = getattr(candidate, "snap", None)
    if snap is not None and snap.spotChart:
        from app.engines.spot_direction import side_aligned_with_chart

        side = getattr(candidate, "side", None)
        side_v = side.value if hasattr(side, "value") else str(side or "").upper()
        if side_v in ("CALL", "PUT") and not side_aligned_with_chart(side_v, snap.spotChart):
            breadth = str(snap.breadth.bias if snap.breadth else "NEUTRAL").upper()
            if not (
                (side_v == "CALL" and breadth == "BULLISH")
                or (side_v == "PUT" and breadth == "BEARISH")
            ):
                return False
    return True


def candidate_is_expiry_pm_local_base_explosion_bypass(
    candidate: Any,
    snap: SymbolSnapshot,
) -> bool:
    """Allow ELITE/EXPLODING local-base explosion on expiry symbol during PM ITM window.

    Aug25 NIFTY CALL 24200: ELITE first-lift at lb=16.5%, funnel MFE=138%, blocked
    by expiry_pm_itm_quick_only while all other gates passed. PM ITM routing to
    SENSEX quick scalps must not suppress a genuine expiry-symbol base rip.
    """
    settings = get_settings()
    if not getattr(settings, "expiry_pm_itm_local_base_explosion_bypass_enabled", True):
        return False
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False
    if not is_near_expiry_day(snap):
        return False

    alert = getattr(candidate, "alert", None) if isinstance(getattr(candidate, "alert", None), dict) else {}
    event = getattr(candidate, "explosion_event", None)
    tier = str(getattr(candidate, "tier", "") or alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False

    score = float(
        getattr(candidate, "confidence", 0)
        or alert.get("explosionScore")
        or getattr(event, "explosion_score", 0)
        or 0
    )
    min_score = float(
        getattr(settings, "expiry_pm_itm_local_base_min_explosion_score", 75.0) or 75.0
    )
    if score < min_score:
        return False

    local_move = float(
        alert.get("localBaseMovePct")
        or alert.get("ictBaseRelativeMovePct")
        or getattr(event, "local_base_move_pct", 0)
        or 0
    )
    min_lb = float(getattr(settings, "expiry_pm_itm_local_base_min_move_pct", 2.0) or 2.0)
    max_lb = float(getattr(settings, "expiry_pm_itm_local_base_max_move_pct", 25.0) or 25.0)
    if not (min_lb <= local_move <= max_lb):
        return False

    daily_move = max(
        float(getattr(event, "daily_move_pct", 0) or 0) if event is not None else 0.0,
        float(getattr(event, "peak_move_pct", 0) or 0) if event is not None else 0.0,
        _alert_session_move(alert) if alert else 0.0,
    )
    if daily_move >= 25.0 and local_move < 5.0:
        return False

    if bool(alert.get("midRipCoil") or alert.get("faded") or alert.get("exhaustedReentry")):
        return False

    has_base_trigger = bool(
        alert.get("ictFirstLift")
        or alert.get("ictVRipReady")
        or alert.get("vRipReady")
        or alert.get("ictArmedBaseLaunch")
        or alert.get("ictEliteBaseReady")
        or (
            alert.get("ictFlatThenVertical")
            and alert.get("ictBreakout")
        )
    )
    if not has_base_trigger:
        return False

    prem = float(getattr(candidate, "premium", 0) or alert.get("premium") or 0)
    from app.engines.premium_filter import premium_in_band

    if not premium_in_band(prem, mode="explosion", peak_move_pct=daily_move):
        return False
    return True


def check_expiry_entry_allowed(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """Session-level expiry gates before any new entry."""
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not settings.expiry_day_guards_enabled:
        return True, "ok", meta

    has_expiry_today = is_expiry_session(snapshots)
    pm_itm = expiry_pm_itm_quick_session_active(snapshots, state)
    meta["expiryPmItmQuickActive"] = pm_itm

    if not has_expiry_today and not pm_itm:
        return True, "ok", meta

    if has_expiry_today:
        meta["expirySymbols"] = expiry_symbols(snapshots)
        is_worst, worst_score, worst_reasons = predict_worst_expiry_day(state, snapshots)
        meta["worstDay"] = is_worst
        meta["worstDayScore"] = worst_score
        meta["worstDayReasons"] = worst_reasons

    if pm_itm:
        meta["expiryPmItmQuickOnly"] = True
        if not has_expiry_today:
            return True, "ok", meta

    if in_expiry_evening_block() and has_expiry_today:
        if snapshots_have_afternoon_top_signal(snapshots):
            meta["expiryEveningTopSignalBypass"] = True
            return True, "ok", meta
        from app.engines.extreme_explosion_moment import snapshots_have_all_in_explosion

        if (
            settings.expiry_evening_all_in_explosion_bypass
            and snapshots_have_all_in_explosion(snapshots)
        ):
            meta["expiryEveningAllInBypass"] = True
            return True, "ok", meta
        return False, "expiry_evening_block", meta

    if not in_expiry_morning_window() and settings.expiry_morning_only and has_expiry_today:
        if pm_itm:
            return True, "ok", meta
        from app.engines.morning_premium_capture import (
            in_afternoon_premium_capture_window,
            in_all_day_explosion_window,
        )

        if in_all_day_explosion_window():
            meta["expiryAfternoonExplosionAllowed"] = True
            return True, "ok", meta
        from app.engines.bullish_local_base import snapshots_have_bullish_local_base_pad

        if snapshots_have_bullish_local_base_pad(snapshots):
            meta["expiryAfternoonLocalBasePad"] = True
            return True, "ok", meta
        if (
            in_afternoon_premium_capture_window()
            and snapshots_have_top_ftv_or_v(snapshots)
        ):
            meta["expiryAfternoonTopFtvV"] = True
            return True, "ok", meta
        return False, "expiry_afternoon_wait", meta

    if has_expiry_today:
        cap_hit, cap_reason = expiry_trades_cap_reached(state, snapshots)
        if cap_hit:
            # Hard 3-trade expiry_worst cap must not skip ELITE / top EXPLODING.
            if (
                is_worst
                and getattr(settings, "expiry_worst_day_elite_top_bypass_enabled", True)
                and getattr(settings, "expiry_worst_day_elite_top_bypasses_trade_cap", True)
                and snapshots_have_expiry_elite_top(snapshots)
            ):
                meta["expiryWorstDayEliteTopBypass"] = True
                meta["expiryWorstDayEliteTopOnly"] = True
                meta["dailyCapEliteBypass"] = True
                meta["rawCapReason"] = cap_reason
                return True, "ok", meta
            if (
                is_worst
                and getattr(settings, "expiry_worst_day_top_ftv_v_bypass_enabled", True)
                and getattr(settings, "expiry_worst_day_top_ftv_v_bypasses_trade_cap", True)
                and snapshots_have_top_ftv_or_v(snapshots)
            ):
                meta["expiryWorstDayTopFtvVBypass"] = True
                meta["expiryWorstDayTopFtvVOnly"] = True
                meta["dailyCapTopFtvVBypass"] = True
                meta["rawCapReason"] = cap_reason
                return True, "ok", meta
            return False, cap_reason, meta

        if is_worst and settings.expiry_worst_day_halt_entries:
            if _session_declining(state, snapshots):
                if (
                    getattr(settings, "expiry_worst_day_elite_top_bypass_enabled", True)
                    and snapshots_have_strict_rank_one_launch(snapshots)
                ):
                    meta["expiryWorstDayStrictRankOneBypass"] = True
                    meta["expiryWorstDayStrictRankOneOnly"] = True
                    return True, "ok", meta
                if (
                    getattr(settings, "expiry_worst_day_grade_a_ftv_bypass_enabled", True)
                    and snapshots_have_grade_a_ftv_first_lift(snapshots)
                ):
                    meta["expiryWorstDayGradeAFtvBypass"] = True
                    meta["expiryWorstDayGradeAFtvOnly"] = True
                    return True, "ok", meta
                if (
                    getattr(settings, "expiry_worst_day_top_ftv_v_bypass_enabled", True)
                    and snapshots_have_top_ftv_or_v(snapshots)
                ):
                    meta["expiryWorstDayTopFtvVBypass"] = True
                    meta["expiryWorstDayTopFtvVOnly"] = True
                    return True, "ok", meta
                from app.engines.bullish_local_base import (
                    snapshots_have_bullish_local_base_pad,
                )

                if snapshots_have_bullish_local_base_pad(snapshots):
                    meta["expiryWorstDayBullishLocalBasePad"] = True
                    meta["expiryWorstDayBullishLocalBasePadOnly"] = True
                    return True, "ok", meta
                # A genuine intraday index breakout lifts the stale expiry chop halt too.
                if bool(
                    getattr(settings, "worst_day_intraday_trend_override_enabled", True)
                ):
                    try:
                        from app.engines.index_tick_helpers import (
                            index_trend_override_active,
                        )

                        trend_ok, trend_meta = index_trend_override_active(snapshots)
                        if trend_ok:
                            meta["expiryWorstDayTrendOverride"] = trend_meta
                            return True, "ok", meta
                    except Exception:
                        pass
                return False, "expiry_worst_day_declining_halt", meta

    return True, "ok", meta


def check_expiry_candidate(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """Per-candidate expiry rules."""
    settings = get_settings()
    meta: dict[str, Any] = {}
    sym = candidate.symbol.upper()
    snap = snapshots.get(sym) or candidate.snap
    score = float(getattr(candidate, "score", 0) or 0)
    mode = str(getattr(candidate, "mode", "") or "")

    confirm_ok, confirm_reason, confirm_meta = check_expiry_afternoon_explosion_confirmation(
        candidate, state, snapshots,
    )
    meta.update(confirm_meta)
    if not confirm_ok:
        return False, confirm_reason, meta

    pm_itm = expiry_pm_itm_quick_active(snap, state, snapshots)
    meta["expiryPmItmQuick"] = pm_itm

    if pm_itm:
        if mode not in ("quick_sideways", "slow_bounce", "worst_day_itm_fade"):
            if (
                candidate_is_expiry_pm_local_base_explosion_bypass(candidate, snap)
            ):
                meta["expiryPmItmLocalBaseBypass"] = True
                return True, "ok", meta
            return False, "expiry_pm_itm_quick_only", meta
        from app.engines.moneyness import classify_moneyness

        money = classify_moneyness(
            candidate.side, float(candidate.strike), float(snap.spot or 0),
            symbol=sym, atm=float(snap.atmStrike or 0) or None,
        )
        meta["moneyness"] = money
        if money != "ITM":
            return False, "expiry_pm_itm_strike_only", meta
        floor = settings.expiry_pm_itm_min_rank_score
        if score < floor:
            return False, f"expiry_pm_itm_rank_below_{floor:.0f}", meta
        return True, "ok", meta

    if not is_symbol_expiry_day(snap):
        return True, "ok", meta

    is_worst, _, _ = predict_worst_expiry_day(state, snapshots)
    declining = is_worst and _session_declining(state, snapshots)
    cap_hit = False
    if (
        is_worst
        and getattr(settings, "expiry_worst_day_elite_top_bypass_enabled", True)
        and getattr(settings, "expiry_worst_day_elite_top_bypasses_trade_cap", True)
    ):
        cap_hit, _ = expiry_trades_cap_reached(state, snapshots)
    elite_only = bool(
        getattr(settings, "expiry_worst_day_elite_top_bypass_enabled", True)
        and (declining or cap_hit)
    )
    if elite_only:
        # The declining halt uses the strict rank-one launch proof. The existing
        # broader elite-top policy remains unchanged for post-cap handling.
        from app.engines.grade_a_ftv_capture import is_grade_a_ftv_first_lift_candidate
        from app.engines.top_ftv_v_expiry_bypass import is_top_ftv_or_v_candidate

        strict_declining = bool(
            declining
            and (
                alert_is_strict_rank_one_launch(
                    getattr(candidate, "alert", None)
                    if isinstance(getattr(candidate, "alert", None), dict)
                    else {},
                    snap,
                )
                or is_grade_a_ftv_first_lift_candidate(candidate)
                or is_top_ftv_or_v_candidate(candidate)
            )
        )
        if declining and not strict_declining:
            return False, "expiry_worst_day_strict_rank_one_only", meta
        if (
            cap_hit
            and not is_expiry_elite_top_candidate(candidate)
            and not is_grade_a_ftv_first_lift_candidate(candidate)
            and not is_top_ftv_or_v_candidate(candidate)
        ):
            return False, "expiry_worst_day_elite_top_only", meta
        meta["expiryEliteTop"] = bool(cap_hit)
        meta["expiryStrictRankOneLaunch"] = strict_declining
        meta["expiryGradeAFtv"] = is_grade_a_ftv_first_lift_candidate(candidate)
        meta["expiryTopFtvV"] = is_top_ftv_or_v_candidate(candidate)
        # Still run open-block + aligned checks below for explosions.

    if mode == "explosion":
        tier = str(getattr(candidate, "tier", "") or "")
        blocked, block_reason = check_expiry_explosion_open_block(
            snap=snap,
            tier=tier,
            side=candidate.side,
            breadth=snap.breadth,
        )
        if blocked:
            return False, block_reason, meta

        from app.engines.aligned_explosion_bypass import expiry_aligned_explosion_trade_allowed

        if expiry_aligned_explosion_trade_allowed(candidate, snap)[0]:
            meta["expiryAlignedBypass"] = True
            return True, "ok", meta

    # Qualified base-window elite top already cleared tier/score/move/premium/chart —
    # let it skip the expiry worst-day rank floor (72) that would otherwise re-block it.
    if (
        meta.get("expiryEliteTop")
        or meta.get("expiryStrictRankOneLaunch")
        or meta.get("expiryGradeAFtv")
    ):
        return True, "ok", meta

    from app.engines.pretrade_validator import candidate_trade_score

    rank_score = candidate_trade_score(candidate)
    min_rank = expiry_min_rank_score(state, snapshots)
    meta["expiryMinRank"] = min_rank
    meta["rankScore"] = rank_score
    if min_rank > 0 and rank_score < min_rank:
        return False, f"expiry_rank_below_{min_rank:.0f}", meta

    if declining and not getattr(settings, "expiry_worst_day_elite_top_bypass_enabled", True):
        if score < settings.expiry_worst_day_min_rank_score:
            return False, "expiry_worst_day_low_score", meta

    return True, "ok", meta


def expiry_dual_scalp_active(snapshots: dict[str, SymbolSnapshot]) -> bool:
    """On expiry chop, allow managed CE+PE scalps instead of one-sided churn."""
    settings = get_settings()
    return (
        settings.expiry_day_guards_enabled
        and settings.expiry_dual_scalp_mode
        and is_expiry_session(snapshots)
        and is_chop_session(snapshots)
    )


def relax_opposite_side_for_expiry_dual(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """
    On expiry dual-scalp mode, shorten opposite-side cooldown when session is declining
    so we can hedge with the other leg instead of fighting one direction.
    """
    if not expiry_dual_scalp_active(snapshots):
        return False
    if not is_symbol_expiry_day(snap):
        return False
    settings = get_settings()
    return settings.expiry_dual_scalp_relax_whipsaw


def expiry_guard_summary(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, Any]:
    settings = get_settings()
    symbols = expiry_symbols(snapshots)
    is_worst, worst_score, worst_reasons = predict_worst_expiry_day(state, snapshots)
    cap, cap_label = expiry_trade_cap(state, snapshots)
    cap_hit, cap_msg = expiry_trades_cap_reached(state, snapshots)
    allowed, block_reason, _ = check_expiry_entry_allowed(state, snapshots)

    pm_alts: list[str] = []
    if state is not None:
        from app.engines.bad_day_routing import pm_itm_alternate_symbols

        pm_alts = sorted(pm_itm_alternate_symbols(state, snapshots))

    near = near_expiry_symbols(snapshots)
    pre_only = [s for s in near if s not in symbols]
    past_evening = in_expiry_evening_block()
    has_expiry_today = bool(symbols)
    evening_active = past_evening and has_expiry_today
    return {
        "enabled": settings.expiry_day_guards_enabled,
        "expirySession": has_expiry_today,
        "expirySymbols": symbols,
        "nearExpirySymbols": near,
        "preExpirySymbols": pre_only,
        "eveningBlockActive": evening_active,
        "morningWindow": in_expiry_morning_window(),
        "eveningBlock": evening_active,
        "pastEveningBlockTime": past_evening,
        "worstDay": is_worst,
        "worstDayScore": worst_score,
        "worstDayReasons": worst_reasons,
        "decliningSession": _session_declining(state, snapshots),
        "dailyTradeCap": cap,
        "dailyTradeCapLabel": cap_label,
        "tradeCapReached": cap_hit,
        "tradeCapMessage": cap_msg if cap_hit else None,
        "entriesAllowed": allowed,
        "blockReason": block_reason if not allowed else None,
        "dualScalpMode": expiry_dual_scalp_active(snapshots),
        "minRankScore": expiry_min_rank_score(state, snapshots),
        "sessionPnlInr": round(compute_session_pnl(state), 2),
        "expiryPmItmQuickActive": expiry_pm_itm_quick_session_active(snapshots, state),
        "expiryPmItmWindow": in_expiry_pm_itm_window(),
        "expiryPmItmAlternateSymbols": pm_alts,
        "expiryItmMonitor": bool(getattr(settings, "expiry_itm_monitor_enabled", True))
        and has_expiry_today,
        "expiryMaxItmSteps": expiry_itm_max_steps() if has_expiry_today else None,
        "expiryItmBothSides": bool(getattr(settings, "expiry_itm_both_sides", True)),
    }
