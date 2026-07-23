"""Chop-day guardrails — Jun 25 playbook for RANGE_BOUND / NEUTRAL sessions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot
from app.services.upstox import get_market_phase

IST = ZoneInfo("Asia/Kolkata")

_session_loss_streak: int = 0
_pause_until: Optional[datetime] = None
_large_loss_pause_until: Optional[datetime] = None
_session_date: Optional[str] = None


def _reset_session_if_new_day() -> None:
    global _session_loss_streak, _pause_until, _large_loss_pause_until, _session_date
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _session_date = today
        _session_loss_streak = 0
        _pause_until = None
        _large_loss_pause_until = None


def record_session_trade_close(pnl_inr: float) -> None:
    """Global loss streak — pause new entries after N consecutive losses or one large hit."""
    global _session_loss_streak, _pause_until, _large_loss_pause_until
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return
    _reset_session_if_new_day()
    now = datetime.now(IST)
    if pnl_inr <= -settings.session_large_loss_pause_inr:
        _large_loss_pause_until = now + timedelta(seconds=settings.session_large_loss_pause_seconds)
    if pnl_inr < -50:
        _session_loss_streak += 1
        if _session_loss_streak >= settings.loss_streak_pause_count:
            _pause_until = now + timedelta(seconds=settings.loss_streak_pause_seconds)
    elif pnl_inr > 50:
        _session_loss_streak = 0


def session_pause_active() -> tuple[bool, str]:
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return False, "ok"
    _reset_session_if_new_day()
    now = datetime.now(IST)
    if _large_loss_pause_until is not None:
        until = (
            _large_loss_pause_until
            if _large_loss_pause_until.tzinfo
            else _large_loss_pause_until.replace(tzinfo=IST)
        )
        if now < until.astimezone(IST):
            secs = int((until.astimezone(IST) - now).total_seconds())
            return True, f"large_loss_pause_{secs}s"
    if _pause_until is None:
        return False, "ok"
    until = _pause_until if _pause_until.tzinfo else _pause_until.replace(tzinfo=IST)
    if now < until.astimezone(IST):
        secs = int((until.astimezone(IST) - now).total_seconds())
        return True, f"loss_streak_pause_{secs}s"
    return False, "ok"


def loss_streak_elite_bypass_tiers() -> set[str]:
    settings = get_settings()
    raw = str(getattr(settings, "loss_streak_elite_bypass_tiers_csv", "ELITE,EXPLODING") or "ELITE")
    return {t.strip().upper() for t in raw.split(",") if t.strip()}


def _alert_session_move(alert: dict[str, Any]) -> float:
    return max(
        float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
        float(alert.get("peakMovePct") or 0),
    )


def _loss_streak_move_ok(
    move: float,
    min_move: float,
    max_move: float,
    *,
    flat_then_vertical: bool = False,
    base_relative_move: float = 0.0,
) -> bool:
    if min_move <= move <= max_move:
        return True
    # Confirmed flat→vertical base rip: accept on base-relative move so a fast
    # rip past the off-low ceiling can still lift the loss-streak pause.
    if flat_then_vertical and min_move <= float(base_relative_move or 0) <= max_move:
        return True
    return False


def _loss_streak_confidence_ok(
    alert: dict[str, Any],
    snap: Optional[SymbolSnapshot],
    side: str,
    min_chart_conf: float,
) -> bool:
    """Chart confidence, or ICT structure signals that stand in for conviction."""
    if bool(alert.get("ictMegaRip")) or bool(alert.get("ictFlatThenVertical")):
        return True
    if float(alert.get("ictScore") or 0) >= 70.0 and bool(alert.get("ictBreakout")):
        return True
    if snap is None or side not in ("CALL", "PUT"):
        return False
    try:
        from app.engines.chart_exit_levels import chart_trade_confidence
        from app.models.schemas import Side

        conf, _ = chart_trade_confidence(snap, Side(side))
        return float(conf or 0) >= min_chart_conf
    except Exception:
        return False


def alert_is_loss_streak_elite_bypass(
    alert: dict[str, Any],
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """True for high-confidence ELITE / top explosive worth lifting loss-streak pause."""
    settings = get_settings()
    if not getattr(settings, "loss_streak_elite_bypass_enabled", True):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in loss_streak_elite_bypass_tiers():
        return False
    score = float(alert.get("explosionScore") or 0)
    min_score = float(getattr(settings, "loss_streak_elite_bypass_min_score", 90.0) or 90.0)
    if score < min_score:
        return False
    # EXPLODING needs ICT structure confirmation — bare EXPLODING is not "top explosive".
    if tier != "ELITE" and not (
        bool(alert.get("ictFlatThenVertical"))
        or bool(alert.get("ictMegaRip"))
        or (bool(alert.get("ictBreakout")) and float(alert.get("ictScore") or 0) >= 70.0)
    ):
        return False
    move = _alert_session_move(alert)
    min_move = float(getattr(settings, "loss_streak_elite_bypass_min_move_pct", 28.0) or 28.0)
    max_move = float(getattr(settings, "loss_streak_elite_bypass_max_move_pct", 70.0) or 70.0)
    if not _loss_streak_move_ok(
        move,
        min_move,
        max_move,
        flat_then_vertical=bool(alert.get("ictFlatThenVertical")),
        base_relative_move=float(alert.get("ictBaseRelativeMovePct") or 0),
    ):
        return False
    side = str(alert.get("side") or "").upper()
    min_conf = float(
        getattr(settings, "loss_streak_elite_bypass_min_chart_confidence", 56.9) or 56.9
    )
    if not _loss_streak_confidence_ok(alert, snap, side, min_conf):
        return False
    if snap is not None and snap.spotChart and side in ("CALL", "PUT"):
        from app.engines.spot_direction import side_aligned_with_chart

        if not side_aligned_with_chart(side, snap.spotChart):
            breadth = str(snap.breadth.bias if snap.breadth else "NEUTRAL").upper()
            if not (
                (side == "CALL" and breadth == "BULLISH")
                or (side == "PUT" and breadth == "BEARISH")
            ):
                return False
    return True


def snapshots_have_loss_streak_elite_bypass(snapshots: dict[str, SymbolSnapshot]) -> bool:
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            if alert_is_loss_streak_elite_bypass(alert, snap):
                return True
    return False


def is_loss_streak_elite_bypass_candidate(candidate: Any) -> bool:
    """Per-candidate gate when loss-streak pause is lifted for elite-only entries."""
    settings = get_settings()
    if not getattr(settings, "loss_streak_elite_bypass_enabled", True):
        return False
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False
    alert = getattr(candidate, "alert", None) if isinstance(getattr(candidate, "alert", None), dict) else {}
    snap = getattr(candidate, "snap", None)
    if alert:
        # Prefer the live alert dict (has ICT fields); enrich missing tier/score from candidate.
        enriched = dict(alert)
        if not enriched.get("tier"):
            enriched["tier"] = getattr(candidate, "tier", None)
        if not enriched.get("explosionScore"):
            enriched["explosionScore"] = getattr(candidate, "confidence", None) or getattr(
                candidate, "score", None
            )
        if not enriched.get("side"):
            side = getattr(candidate, "side", None)
            enriched["side"] = side.value if hasattr(side, "value") else side
        return alert_is_loss_streak_elite_bypass(enriched, snap)

    # Fallback when candidate has no alert payload.
    tier = str(getattr(candidate, "tier", "") or "").upper()
    if tier not in loss_streak_elite_bypass_tiers():
        return False
    score = float(getattr(candidate, "confidence", 0) or getattr(candidate, "score", 0) or 0)
    min_score = float(getattr(settings, "loss_streak_elite_bypass_min_score", 90.0) or 90.0)
    if score < min_score:
        return False
    event = getattr(candidate, "explosion_event", None)
    move = 0.0
    flat = False
    base_rel = 0.0
    if event is not None:
        move = max(
            float(getattr(event, "daily_move_pct", 0) or 0),
            float(getattr(event, "peak_move_pct", 0) or 0),
        )
        try:
            from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

            ict = analyze_explosion_event_ict(event, snap)
            flat = bool(ict.active and ict.flat_then_vertical)
            base_rel = float(ict.base_relative_move_pct or 0)
            if ict.mega_rip:
                flat = True
        except Exception:
            pass
    min_move = float(getattr(settings, "loss_streak_elite_bypass_min_move_pct", 28.0) or 28.0)
    max_move = float(getattr(settings, "loss_streak_elite_bypass_max_move_pct", 70.0) or 70.0)
    if not _loss_streak_move_ok(
        move, min_move, max_move, flat_then_vertical=flat, base_relative_move=base_rel,
    ):
        return False
    side_obj = getattr(candidate, "side", None)
    side = side_obj.value if hasattr(side_obj, "value") else str(side_obj or "").upper()
    min_conf = float(
        getattr(settings, "loss_streak_elite_bypass_min_chart_confidence", 56.9) or 56.9
    )
    synthetic = {
        "tier": tier,
        "explosionScore": score,
        "side": side,
        "ictFlatThenVertical": flat,
        "ictMegaRip": False,
        "ictBreakout": flat,
        "ictScore": 80.0 if flat else 0.0,
        "dailyMovePct": move,
        "ictBaseRelativeMovePct": base_rel,
    }
    return _loss_streak_confidence_ok(synthetic, snap, side, min_conf)


def resolve_session_entry_pause(
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Entry-gate pause resolver.

    large_loss_pause is never bypassed.
    loss_streak_pause lifts when a high-confidence ELITE / top explosive is on radar;
    caller must then restrict entries to those candidates only (meta lossStreakEliteOnly).
    """
    paused, reason = session_pause_active()
    meta: dict[str, Any] = {"rawPaused": paused, "rawReason": reason if paused else None}
    if not paused:
        return False, "ok", meta
    if reason.startswith("large_loss_pause"):
        return True, reason, meta
    if not reason.startswith("loss_streak_pause"):
        return True, reason, meta
    if snapshots is None:
        return True, reason, meta
    settings = get_settings()
    if not getattr(settings, "loss_streak_elite_bypass_enabled", True):
        return True, reason, meta
    if not snapshots_have_loss_streak_elite_bypass(snapshots):
        return True, reason, meta
    meta["lossStreakEliteOnly"] = True
    meta["lossStreakEliteBypass"] = True
    return False, "loss_streak_elite_bypass", meta


def reset_session_guards() -> None:
    global _session_loss_streak, _pause_until, _large_loss_pause_until, _session_date
    _session_loss_streak = 0
    _pause_until = None
    _large_loss_pause_until = None
    _session_date = None


def is_chop_session(snapshots: dict[str, SymbolSnapshot]) -> bool:
    """Majority NEUTRAL breadth or RANGE_BOUND regime → chop day rules."""
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return False
    live = [s for s in snapshots.values() if s.dataAvailable]
    if not live:
        return False
    neutral = sum(1 for s in live if (s.breadth.bias or "NEUTRAL").upper() == "NEUTRAL")
    range_bound = sum(
        1 for s in live
        if str(s.regime.value if hasattr(s.regime, "value") else s.regime) == "RANGE_BOUND"
    )
    n = len(live)
    return neutral >= max(1, n // 2) or range_bound >= max(1, (2 * n) // 3)


def _minutes_now() -> int:
    now = datetime.now(IST)
    return now.hour * 60 + now.minute


def before_primary_window() -> bool:
    settings = get_settings()
    start = settings.primary_window_start_hour * 60 + settings.primary_window_start_minute
    return _minutes_now() < start


def daily_trade_cap(state: AutoTraderState, snapshots: dict[str, SymbolSnapshot]) -> tuple[int, str]:
    """Max closed trades allowed today under chop / expiry rules."""
    from app.engines.expiry_day_guards import expiry_trade_cap, is_expiry_session

    if is_expiry_session(snapshots):
        return expiry_trade_cap(state, snapshots)

    settings = get_settings()
    if not settings.chop_day_guards_enabled or not is_chop_session(snapshots):
        return 999, "normal"
    if before_primary_window():
        return settings.daily_max_trades_pre10_chop, "pre10_chop"
    return settings.daily_max_trades_chop, "chop_day"


def trades_cap_reached(state: AutoTraderState, snapshots: dict[str, SymbolSnapshot]) -> tuple[bool, str]:
    cap, label = daily_trade_cap(state, snapshots)
    closed = len(state.closedPaperTrades)
    if closed >= cap:
        return True, f"daily_trade_cap_{closed}>={cap}_{label}"
    return False, "ok"


def in_momentum_rally_window() -> bool:
    """11:00–13:45 IST — premium expansion window (chart-style rallies)."""
    if get_market_phase() != "LIVE_MARKET":
        return False
    settings = get_settings()
    current = _minutes_now()
    start = settings.momentum_rally_start_hour * 60 + settings.momentum_rally_start_minute
    end = settings.momentum_rally_end_hour * 60 + settings.momentum_rally_end_minute
    return start <= current < end


def is_momentum_surge(
    velocity_pct: float = 0.0,
    volume_surge: float = 1.0,
    explosion_score: float = 0.0,
) -> bool:
    """Strong premium velocity / volume — bypass neutral-chop blocks."""
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return False
    return (
        velocity_pct >= settings.momentum_bypass_velocity_pct
        or volume_surge >= settings.momentum_bypass_volume_surge
        or explosion_score >= settings.momentum_bypass_explosion_score
    )


def neutral_breadth_blocks_entry(
    breadth_bias: str,
    trade_score: float,
    velocity_pct: float = 0.0,
    *,
    explosion: bool = False,
    volume_surge: float = 1.0,
) -> tuple[bool, str]:
    """Block NEUTRAL chop unless score/velocity prove edge."""
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return False, "ok"
    if (breadth_bias or "NEUTRAL").upper() != "NEUTRAL":
        return False, "ok"
    if is_momentum_surge(velocity_pct, volume_surge, trade_score if explosion else 0):
        return False, "ok"
    min_score = settings.neutral_breadth_min_score
    if explosion and velocity_pct >= settings.explosion_early_velocity_3s:
        min_score = min(min_score, settings.neutral_breadth_explosion_min_score)
    if trade_score >= min_score:
        return False, "ok"
    return True, f"neutral_breadth_score_below_{min_score}"


def symbol_rank_adjustment(symbol: str, chop: bool) -> float:
    settings = get_settings()
    if not settings.chop_day_guards_enabled or not chop:
        return 0.0
    sym = symbol.upper()
    if sym == "SENSEX":
        return settings.sensex_rank_bonus
    if sym == "NIFTY":
        return -settings.nifty_rank_penalty_chop
    return 0.0


def min_rank_for_entry(chop: bool, snapshots: Optional[dict] = None) -> float:
    settings = get_settings()
    from app.engines.session_timing import in_open_caution_window

    if in_open_caution_window():
        if settings.index_momentum_enabled and snapshots:
            from app.engines.market_momentum import any_index_moment_active
            if any_index_moment_active(snapshots):
                return settings.open_caution_moment_min_rank
        return settings.open_caution_min_rank_score
    if chop and before_primary_window():
        return settings.pre10_chop_min_rank_score
    return 0.0


def apply_tiered_lot_cap(
    lots: int,
    rank_score: float,
    breadth_aligned: bool,
    symbol: str,
    *,
    velocity_pct: float = 0.0,
    volume_surge: float = 1.0,
) -> int:
    """Block weak setups; otherwise keep capital-max lots (85% cap sizing)."""
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return lots

    min_rank = settings.chop_lots_min_rank
    momentum = is_momentum_surge(velocity_pct, volume_surge, 0.0)
    if rank_score < min_rank and not momentum:
        return 0

    return lots


def _symbol_breadth_summary(snapshots: dict[str, SymbolSnapshot]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        regime = str(snap.regime.value if hasattr(snap.regime, "value") else snap.regime)
        out[sym.upper()] = {
            "bias": (snap.breadth.bias or "NEUTRAL").upper(),
            "score": round(float(snap.breadth.score or 50), 1),
            "aligned": bool(snap.breadth.aligned),
            "regime": regime,
        }
    return out


def _day_mode_label(
    chop: bool,
    momentum: bool,
    breadth: dict[str, dict],
    before_primary: bool,
    expiry: bool = False,
    expiry_worst: bool = False,
) -> tuple[str, str, str]:
    """Return (mode, badge tone key, short playbook hint)."""
    if expiry_worst:
        return (
            "EXPIRY WORST",
            "chop",
            "Expiry + chop/loss — max 3 trades, morning only, CE+PE scalp, hold high conf",
        )
    if expiry:
        return (
            "EXPIRY DAY",
            "warn",
            "Weekly expiry — fewer trades, morning focus, dual CE/PE scalp, no evening",
        )
    biases = [b.get("bias", "NEUTRAL") for b in breadth.values()]
    bullish = sum(1 for b in biases if b == "BULLISH")
    bearish = sum(1 for b in biases if b == "BEARISH")
    n = len(biases)

    if momentum and chop:
        return (
            "CHOP + RALLY",
            "rally",
            "Neutral chop — momentum bypass active; ride velocity surges",
        )
    if momentum:
        return (
            "MOMENTUM RALLY",
            "rally",
            "11:00–13:45 window — wider SL, longer holds, velocity entries",
        )
    if chop:
        if before_primary:
            return (
                "CHOP (PRE-10)",
                "chop",
                "Strict chop — max 5 trades, score ≥60, SENSEX preferred",
            )
        return (
            "CHOP DAY",
            "chop",
            "Neutral/range — capped trades, score ≥60, avoid midday noise",
        )
    if n > 0 and bullish == n:
        return ("BULLISH DAY", "bullish", "CALL-biased — full 40 lots on aligned setups")
    if n > 0 and bearish == n:
        return ("BEARISH DAY", "bearish", "PUT-biased — Jun 25 playbook, let runners run")
    if bullish > 0 and bearish > 0:
        return ("MIXED DAY", "mixed", "Index divergence — trade aligned side per symbol")
    if bullish > bearish:
        return ("LEAN BULLISH", "bullish", "CALL edge — counter-trend PUTs need high score")
    if bearish > bullish:
        return ("LEAN BEARISH", "bearish", "PUT edge — counter-trend CALLs need high score")
    return ("NORMAL", "normal", "Standard gates — adaptive SL + micro locks")


def chop_guard_summary(state: AutoTraderState, snapshots: dict[str, SymbolSnapshot]) -> dict:
    chop = is_chop_session(snapshots)
    cap, cap_label = daily_trade_cap(state, snapshots)
    paused, pause_reason = session_pause_active()
    entry_paused, entry_pause_reason, entry_pause_meta = resolve_session_entry_pause(snapshots)
    cap_hit, cap_msg = trades_cap_reached(state, snapshots)
    momentum = in_momentum_rally_window()
    before_primary = before_primary_window()
    breadth = _symbol_breadth_summary(snapshots)

    from app.engines.market_momentum import index_moment_summary
    from app.engines.session_timing import in_midday_chop_window, in_open_caution_window
    from app.engines.simple_profit import get_session_targets
    from app.engines.pretrade_validator import (
        check_last_n_trades_pause,
        last_n_trades_summary,
        resolve_effective_daily_trade_cap,
    )
    from app.engines.whipsaw_guards import whipsaw_guard_summary
    from app.engines.directional_lock import directional_lock_summary
    from app.engines.confidence_hold import high_confidence_close_summary
    from app.engines.moneyness import resolve_preferred_moneyness
    from app.engines.expiry_day_guards import expiry_guard_summary, is_expiry_session, predict_worst_expiry_day
    from app.engines.psychology_hold import psychology_hold_summary
    from app.engines.bad_day_routing import bad_day_routing_summary
    from app.engines.worst_day_guard import worst_day_guard_summary
    from app.engines.worst_day_itm_fade import worst_day_trades_summary
    from app.engines.dual_mode_strategy import dual_mode_summary
    from app.engines.ict_breakout_monitor import ict_monitor_summary
    from app.engines.daily_18pct_strategy import get_session_limits

    session_limits = get_session_limits()
    conf_tier = str(getattr(session_limits, "confidenceTier", None) or "MEDIUM")
    session = get_session_targets()
    settings = get_settings()
    last_n = last_n_trades_summary(state)
    last_n_paused, last_n_reason, _ = check_last_n_trades_pause(state, snapshots)
    expiry_active = is_expiry_session(snapshots)
    expiry_worst, _, _ = predict_worst_expiry_day(state, snapshots) if expiry_active else (False, 0.0, [])
    mode, mode_tone, mode_hint = _day_mode_label(
        chop, momentum, breadth, before_primary, expiry=expiry_active, expiry_worst=expiry_worst,
    )

    effective_cap, cap_source = resolve_effective_daily_trade_cap(state, snapshots)
    return {
        "chopSession": chop,
        "dailyTradeCap": cap,
        "dailyTradeCapLabel": cap_label,
        "closedTrades": len(state.closedPaperTrades),
        "tradeCapReached": cap_hit,
        "tradeCapMessage": cap_msg if cap_hit else None,
        "lossStreak": _session_loss_streak,
        "sessionPaused": paused,
        "pauseReason": pause_reason if paused else None,
        "entriesBlockedByPause": entry_paused,
        "entryPauseReason": None if entry_pause_reason == "ok" else entry_pause_reason,
        "lossStreakEliteBypass": bool(entry_pause_meta.get("lossStreakEliteBypass")),
        "lossStreakEliteOnly": bool(entry_pause_meta.get("lossStreakEliteOnly")),
        "beforePrimaryWindow": before_primary,
        "momentumRallyWindow": momentum,
        "openCautionWindow": in_open_caution_window(),
        "middayChopWindow": in_midday_chop_window(),
        "sessionLabel": session.sessionLabel,
        "sessionTargetPoints": session.targetPoints,
        "guardsEnabled": settings.chop_day_guards_enabled,
        "dayMode": mode,
        "dayModeTone": mode_tone,
        "dayModeHint": mode_hint,
        "symbolBreadth": breadth,
        "indexMoments": {
            sym: index_moment_summary(snapshots[sym])
            for sym in snapshots
            if snapshots[sym].dataAvailable
        },
        "lastNTrades": last_n,
        "lastNTradesPaused": last_n_paused,
        "lastNTradesPauseReason": last_n_reason if last_n_paused else None,
        "controlledDailyCap": effective_cap,
        "controlledDailyCapBase": settings.controlled_max_trades_per_day,
        "controlledDailyCapSource": cap_source,
        "whipsawGuards": whipsaw_guard_summary(state, snapshots),
        "directionalLock": directional_lock_summary(snapshots),
        "confidenceHold": high_confidence_close_summary(),
        "moneynessPolicy": {
            "mode": settings.trade_moneyness_mode,
            "scalpPrefer": settings.moneyness_scalp_chop_prefer,
            "explosionPrefer": settings.moneyness_explosion_prefer,
            "highConfPrefer": settings.moneyness_high_conf_prefer,
            "autoScalpPrefer": resolve_preferred_moneyness(
                "scalp", next(iter(snapshots.values())),
                snapshots=snapshots,
            ) if snapshots else "ATM",
        },
        "expiryGuards": expiry_guard_summary(state, snapshots),
        "psychologyHold": psychology_hold_summary(),
        "badDayRouting": bad_day_routing_summary(state, snapshots),
        "worstDayGuard": worst_day_guard_summary(state, snapshots),
        "worstDayTrades": worst_day_trades_summary(state, snapshots),
        "dualMode": dual_mode_summary(
            state,
            snapshots,
            day_mode=mode,
            confidence_tier=conf_tier,
        ),
        "ictBreakoutMonitor": ict_monitor_summary(snapshots),
    }
