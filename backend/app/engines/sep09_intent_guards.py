"""
Sep 9 intent — one early, near-base rip per side (CE/PE symmetric).

Block rank-#1 / max-lot chase entries after the move is mostly done (Sep28 22850 PE).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side

IST = ZoneInfo("Asia/Kolkata")


def _side_str(side: Any) -> str:
    if isinstance(side, Side):
        return side.value
    return str(side or "").upper()


def _parse_iso_dt(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except (TypeError, ValueError):
        return None


def _alert_dict(candidate: Any) -> dict[str, Any]:
    alert = getattr(candidate, "alert", None)
    return dict(alert) if isinstance(alert, dict) else {}


def _evidence_from_candidate(candidate: Any, alert: Mapping[str, Any]) -> dict[str, Any]:
    ev = dict(alert)
    for key in (
        "localBaseMovePct",
        "ictBaseRelativeMovePct",
        "flatThenVertical",
        "ictFlatThenVertical",
        "firstLift",
        "ictFirstLift",
        "armedBaseLaunch",
        "ictArmedBaseLaunch",
        "vRipReady",
        "spikeRunPct",
        "peakMovePct",
        "dailyMovePct",
        "sessionMovePct",
        "tier",
        "explosionScore",
    ):
        val = getattr(candidate, key, None)
        if val is not None and key not in ev:
            ev[key] = val
    pre = getattr(candidate, "pretrade_meta", None) or {}
    if isinstance(pre, dict):
        for k, v in pre.items():
            ev.setdefault(k, v)
    return ev


def _armed_base_at(alert: Mapping[str, Any]) -> Optional[datetime]:
    ict = alert.get("ictCaptureMeta") or {}
    if isinstance(ict, dict):
        inner = ict.get("ict") or {}
        if isinstance(inner, dict):
            dt = _parse_iso_dt(inner.get("armedAt"))
            if dt:
                return dt
    dt = _parse_iso_dt(alert.get("armedAt"))
    if dt:
        return dt
    armed_ev = alert.get("ictArmedEvidence") or {}
    if isinstance(armed_ev, dict):
        return _parse_iso_dt(armed_ev.get("armedAt"))
    return None


def _detected_at(alert: Mapping[str, Any]) -> Optional[datetime]:
    for key in ("detectedAt", "firstDetectedAt"):
        dt = _parse_iso_dt(alert.get(key))
        if dt:
            return dt
    return None


def _minutes_since_reference(
    alert: Mapping[str, Any], *, now: Optional[datetime] = None,
) -> tuple[Optional[float], str]:
    now = now or datetime.now(IST)
    armed = _armed_base_at(alert)
    if armed is not None:
        if armed.date() != now.date():
            return None, "replay"
        return max(0.0, (now - armed).total_seconds() / 60.0), "armed"
    detected = _detected_at(alert)
    if detected is not None:
        if detected.date() != now.date():
            return None, "replay"
        return max(0.0, (now - detected).total_seconds() / 60.0), "detect"
    return None, ""


def _spike_run_pct(evidence: Mapping[str, Any], *, symbol: str, strike: float, side: Any) -> float:
    spike = max(
        float(evidence.get("spikeRunPct") or 0),
        float(evidence.get("peakMovePct") or 0),
        float(evidence.get("dailyMovePct") or 0),
        float(evidence.get("sessionMovePct") or 0),
    )
    if spike > 0:
        return spike
    from app.engines.explosion_detector import (
        get_session_low_premium,
        get_session_peak_premium,
    )

    peak = float(get_session_peak_premium(symbol, strike, side) or 0)
    low = float(get_session_low_premium(symbol, strike, side) or 0)
    if low > 0 and peak > low:
        return (peak - low) / low * 100.0
    return 0.0


def _pullback_from_session_peak_pct(
    premium: float,
    *,
    symbol: str,
    strike: float,
    side: Any,
    alert: Mapping[str, Any],
) -> float:
    from app.engines.explosion_detector import get_session_peak_premium

    peak = float(get_session_peak_premium(symbol, strike, side) or 0)
    if peak <= 0:
        peak = float(alert.get("sessionPeakPremium") or alert.get("peakPremium") or 0)
    prem = float(premium or alert.get("premium") or 0)
    if peak <= 0 or prem <= 0:
        return 100.0
    return (peak - prem) / peak * 100.0


def _is_explosion_trade_obj(trade: Any) -> bool:
    ctx = getattr(trade, "entryContext", None) or {}
    if isinstance(ctx, dict):
        mode = str(ctx.get("selectionMode") or "").lower()
    else:
        mode = ""
    mode_attr = str(getattr(trade, "mode", "") or "").lower()
    if mode == "explosion" or mode_attr == "explosion":
        return True
    st = getattr(trade, "strategyType", None)
    st_u = st.value if hasattr(st, "value") else str(st or "").upper()
    return st_u == "EXPLOSIVE"


def session_has_sep09_side_rip(
    state: AutoTraderState | None,
    *,
    symbol: str,
    side: Any,
) -> bool:
    """True if this index side already had an explosion-mode entry this session."""
    if state is None:
        return False
    sym = str(symbol or "").upper()
    side_u = _side_str(side)
    if not sym or side_u not in ("CALL", "PUT"):
        return False

    seen: set[str] = set()

    def _matches(trade: Any) -> bool:
        ts = str(getattr(trade, "symbol", "") or "").upper()
        if ts != sym:
            return False
        if _side_str(getattr(trade, "side", "")) != side_u:
            return False
        return _is_explosion_trade_obj(trade)

    for t in list(state.openPaperTrades or []) + list(state.closedPaperTrades or []):
        tid = str(getattr(t, "id", "") or "")
        if tid:
            seen.add(tid)
        if _matches(t):
            return True

    try:
        from app.engines.pretrade_validator import collect_session_trades

        for rec in collect_session_trades(state):
            if rec.trade_id and rec.trade_id in seen:
                continue
            if str(rec.symbol or "").upper() != sym:
                continue
            if str(rec.side or "").upper() != side_u:
                continue
            if str(rec.mode or "").lower() == "explosion":
                return True
    except Exception:
        pass
    return False


SEP09_LANE_OPEN = "OPEN_PREMIUM"
SEP09_LANE_EARLY = "EARLY_NEAR_BASE"
SEP09_LANE_AFTERNOON = "AFTERNOON_STRUCTURAL"


def _side_explosion_trades(
    state: AutoTraderState | None,
    *,
    symbol: str,
    side: Any,
) -> list[Any]:
    if state is None:
        return []
    sym = str(symbol or "").upper()
    side_u = _side_str(side)
    seen: set[str] = set()
    out: list[Any] = []

    def _append(trade: Any) -> None:
        tid = str(getattr(trade, "id", "") or "")
        if tid and tid in seen:
            return
        if tid:
            seen.add(tid)
        ts = str(getattr(trade, "symbol", "") or "").upper()
        if ts != sym or _side_str(getattr(trade, "side", "")) != side_u:
            return
        if not _is_explosion_trade_obj(trade):
            return
        out.append(trade)

    for t in list(state.openPaperTrades or []) + list(state.closedPaperTrades or []):
        _append(t)
    try:
        from app.engines.pretrade_validator import collect_session_trades

        for rec in collect_session_trades(state):
            if rec.trade_id and rec.trade_id in seen:
                continue
            if str(rec.symbol or "").upper() != sym:
                continue
            if str(rec.side or "").upper() != side_u:
                continue
            if str(rec.mode or "").lower() != "explosion":
                continue
            class _RecTrade:
                pass

            stub = _RecTrade()
            stub.id = rec.trade_id
            stub.symbol = sym
            stub.side = side_u
            stub.strike = float(rec.strike or 0)
            stub.entryContext = {"selectionMode": "explosion"}
            _append(stub)
    except Exception:
        pass
    return out


def _infer_sep09_rip_lane(trade: Any) -> str:
    ctx = getattr(trade, "entryContext", None) or {}
    if isinstance(ctx, dict):
        stamped = str(ctx.get("sep09RipLane") or "").upper()
        if stamped in (SEP09_LANE_OPEN, SEP09_LANE_EARLY, SEP09_LANE_AFTERNOON):
            return stamped
        if ctx.get("openPremiumFirstRip") or ctx.get("sep09OpenPremiumFirstRip"):
            return SEP09_LANE_OPEN
    opened = getattr(trade, "openedAt", None)
    if opened is not None:
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=IST)
        from app.engines.session_timing import in_open_premium_window_at

        if in_open_premium_window_at(opened.astimezone(IST)):
            return SEP09_LANE_OPEN
    return SEP09_LANE_EARLY


def session_sep09_rip_lanes_used(
    state: AutoTraderState | None,
    *,
    symbol: str,
    side: Any,
) -> set[str]:
    return {_infer_sep09_rip_lane(t) for t in _side_explosion_trades(state, symbol=symbol, side=side)}


def _minutes_since_last_side_explosion_close(
    state: AutoTraderState | None,
    *,
    symbol: str,
    side: Any,
    now: Optional[datetime] = None,
) -> Optional[float]:
    now = now or datetime.now(IST)
    latest: Optional[datetime] = None
    for t in _side_explosion_trades(state, symbol=symbol, side=side):
        closed = getattr(t, "closedAt", None)
        if closed is None:
            opened = getattr(t, "openedAt", None)
            if opened is not None:
                return 0.0
            continue
        if closed.tzinfo is None:
            closed = closed.replace(tzinfo=IST)
        if latest is None or closed > latest:
            latest = closed.astimezone(IST)
    if latest is None:
        return None
    return max(0.0, (now.astimezone(IST) - latest).total_seconds() / 60.0)


def _prior_explosion_strikes_on_side(
    state: AutoTraderState | None,
    *,
    symbol: str,
    side: Any,
) -> set[float]:
    strikes: set[float] = set()
    for t in _side_explosion_trades(state, symbol=symbol, side=side):
        strikes.add(float(getattr(t, "strike", 0) or 0))
    return strikes


def in_afternoon_structural_rip_window(
    *,
    now: Optional[datetime] = None,
    settings: Any = None,
) -> bool:
    """12:00+ IST (configurable) through session — not the 9:15 open pad window."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "sep09_intent_afternoon_structural_rip_enabled", True)):
        return False
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    now = now.astimezone(IST)
    from app.services.upstox import get_market_phase

    if get_market_phase() != "LIVE_MARKET":
        return False
    start_h = int(getattr(settings, "sep09_intent_afternoon_structural_min_hour", 12) or 12)
    start_m = int(getattr(settings, "sep09_intent_afternoon_structural_min_minute", 0) or 0)
    start = start_h * 60 + start_m
    end_h = int(getattr(settings, "live_session_close_hour", 15) or 15)
    end_m = int(getattr(settings, "live_session_close_minute", 30) or 30)
    end = end_h * 60 + end_m
    current = now.hour * 60 + now.minute
    if current < start or current >= end:
        return False
    from app.engines.session_timing import in_open_premium_window_at

    return not in_open_premium_window_at(now)


def afternoon_structural_side_rip_ok(
    state: AutoTraderState | None,
    *,
    symbol: str,
    side: Any,
    strike: float,
    premium: float,
    evidence: Mapping[str, Any],
    alert: Mapping[str, Any],
    settings: Any = None,
    now: Optional[datetime] = None,
) -> tuple[bool, str]:
    """
    Second lane per side: afternoon flat→vertical off a fresh local base.

    Requires a prior explosion on the same side; no loss-strike re-entry; different
    strike or min minutes since the prior leg closed.
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "sep09_intent_two_lane_per_side_enabled", True)):
        return False, ""
    if not bool(getattr(settings, "sep09_intent_afternoon_structural_rip_enabled", True)):
        return False, ""
    sym = str(symbol or "").upper()
    if not session_has_sep09_side_rip(state, symbol=sym, side=side):
        return False, "afternoon_requires_prior_side_rip"
    lanes = session_sep09_rip_lanes_used(state, symbol=sym, side=side)
    if SEP09_LANE_AFTERNOON in lanes:
        return False, "afternoon_structural_lane_already_used"

    if not in_afternoon_structural_rip_window(settings=settings, now=now):
        return False, "outside_afternoon_structural_window"

    from app.engines.session_mode_feedback import session_same_strike_loss_reentry_blocked

    loss_blocked, loss_meta = session_same_strike_loss_reentry_blocked(
        state, symbol=sym, side=side, strike=float(strike or 0),
    )
    if loss_blocked:
        return False, str(loss_meta.get("reason") or "loss_strike_blocked")

    from app.engines.best_trade_policy import symmetric_structural_base_evidence

    if not symmetric_structural_base_evidence(evidence, settings=settings):
        return False, "afternoon_requires_structural_local_base"

    max_local = float(
        getattr(settings, "sep09_intent_afternoon_structural_max_local_base_pct", 20.0) or 20.0
    )
    local = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("ictBaseRelativeMovePct") or 0),
    )
    if local > max_local + 1e-6:
        return False, f"afternoon_local_base_{local:.1f}pct_over_{max_local:.0f}"

    chase, chase_reason = sep09_near_peak_after_extended_rip(
        evidence,
        premium=premium,
        symbol=sym,
        strike=strike,
        side=side,
        alert=alert,
        settings=settings,
    )
    if chase:
        return False, f"afternoon_near_peak_block:{chase_reason}"

    prior_strikes = _prior_explosion_strikes_on_side(state, symbol=sym, side=side)
    strike_f = float(strike or 0)
    requires_diff = bool(
        getattr(settings, "sep09_intent_afternoon_structural_requires_different_strike", True)
    )
    min_since = float(
        getattr(settings, "sep09_intent_afternoon_structural_min_minutes_since_prior_close", 20.0)
        or 20.0
    )
    elapsed = _minutes_since_last_side_explosion_close(
        state, symbol=sym, side=side, now=now,
    )
    if requires_diff and strike_f in prior_strikes:
        if elapsed is None or elapsed + 1e-6 < min_since:
            return False, (
                f"afternoon_same_strike_need_{min_since:.0f}min_flat_"
                f"got_{elapsed if elapsed is not None else -1:.1f}"
            )
    elif elapsed is not None and elapsed + 1e-6 < min_since:
        return False, f"afternoon_too_soon_after_prior_{elapsed:.1f}min_min_{min_since:.0f}"

    return True, f"afternoon_structural_local_{local:.1f}pct"


def classify_sep09_rip_lane_for_entry(
    state: AutoTraderState | None,
    candidate: Any,
    snap: Any = None,
    *,
    settings: Any = None,
    now: Optional[datetime] = None,
) -> str:
    """Stamp entryContext.sep09RipLane for session two-lane accounting."""
    settings = settings or get_settings()
    symbol = str(getattr(candidate, "symbol", "") or "").upper()
    side = getattr(candidate, "side", None)
    strike = float(getattr(candidate, "strike", 0) or 0)
    premium = float(getattr(candidate, "premium", 0) or 0)
    alert = _alert_dict(candidate)
    evidence = _evidence_from_candidate(candidate, alert)
    pre = getattr(candidate, "pretrade_meta", None) or {}
    if isinstance(pre, dict):
        if pre.get("afternoonStructuralRip") or pre.get("sep917Waive") == "afternoon_structural_side_rip":
            return SEP09_LANE_AFTERNOON
        if pre.get("openPremiumFirstRip"):
            return SEP09_LANE_OPEN
    aft_ok, _ = afternoon_structural_side_rip_ok(
        state,
        symbol=symbol,
        side=side,
        strike=strike,
        premium=premium,
        evidence=evidence,
        alert=alert,
        settings=settings,
        now=now,
    )
    if aft_ok and session_has_sep09_side_rip(state, symbol=symbol, side=side):
        return SEP09_LANE_AFTERNOON
    open_ok, _ = open_premium_first_side_rip_ok(
        state,
        symbol=symbol,
        side=side,
        strike=strike,
        premium=premium,
        evidence=evidence,
        settings=settings,
    )
    if open_ok:
        return SEP09_LANE_OPEN
    return SEP09_LANE_EARLY


def _coerce_rank(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        s = val.strip()
        if s.isdigit():
            return int(s)
    return None


def candidate_is_rank_one(
    candidate: Any,
    alert: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> bool:
    """True when radar / allocator stamped this setup as rank #1."""
    for src in (evidence, alert):
        if not isinstance(src, Mapping):
            continue
        for key in ("cycleRank", "allocationRank", "rank"):
            rank = _coerce_rank(src.get(key))
            if rank == 1:
                return True
    pre = getattr(candidate, "pretrade_meta", None) or {}
    if isinstance(pre, dict):
        causal = pre.get("causalRanking") or {}
        if isinstance(causal, dict):
            for key in ("cycleRank", "allocationRank", "rank"):
                rank = _coerce_rank(causal.get(key))
                if rank == 1:
                    return True
    for attr in ("cycleRank", "allocationRank"):
        if not hasattr(candidate, attr):
            continue
        rank = _coerce_rank(getattr(candidate, attr, None))
        if rank == 1:
            return True
    return False


def rank_one_timing_in_window(
    evidence: Mapping[str, Any],
    candidate: Any,
) -> bool:
    """Rank-#1 entries must show timingAssessment.inWindow=true (no chase waiver)."""
    sources: list[Any] = [evidence]
    pre = getattr(candidate, "pretrade_meta", None) or {}
    if isinstance(pre, dict):
        sources.append(pre)
    for src in sources:
        if not isinstance(src, Mapping):
            continue
        for key in ("timingAssessment", "timing"):
            block = src.get(key)
            if isinstance(block, dict) and "inWindow" in block:
                return bool(block.get("inWindow"))
    return False


def sep09_near_peak_after_extended_rip(
    evidence: Mapping[str, Any],
    *,
    premium: float,
    symbol: str,
    strike: float,
    side: Any,
    alert: Mapping[str, Any],
    settings: Any = None,
) -> tuple[bool, str]:
    """True when premium is still near session peak after an extended rip (chase)."""
    settings = settings or get_settings()
    min_pull = float(getattr(settings, "sep09_intent_min_pullback_from_peak_pct", 8.0) or 8.0)
    max_spike = float(getattr(settings, "sep09_intent_max_spike_run_pct", 18.0) or 18.0)
    spike = _spike_run_pct(evidence, symbol=symbol, strike=strike, side=side)
    pull = _pullback_from_session_peak_pct(
        premium, symbol=symbol, strike=strike, side=side, alert=alert,
    )
    if spike + 1e-6 >= max_spike and pull + 1e-6 < min_pull:
        return True, (
            f"sep09_near_peak_chase_spike_{spike:.1f}pct_pullback_{pull:.1f}pct"
        )
    return False, ""


def sep09_early_near_base_window_ok(
    evidence: Mapping[str, Any],
    alert: Mapping[str, Any],
    *,
    settings: Any = None,
    now: Optional[datetime] = None,
    strict: bool = False,
) -> tuple[bool, str]:
    settings = settings or get_settings()
    from app.engines.best_trade_policy import symmetric_structural_base_evidence

    max_local = float(getattr(settings, "sep09_intent_max_local_base_pct", 20.0) or 20.0)
    if not symmetric_structural_base_evidence(evidence, settings=settings):
        if strict:
            return False, "sep09_rank_one_requires_structural_near_base"
        return True, "sep09_not_structural_near_base_skip"
    local = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("ictBaseRelativeMovePct") or 0),
    )
    if local > max_local + 1e-6:
        return False, f"sep09_local_base_{local:.1f}pct_over_{max_local:.0f}"

    max_arm = float(getattr(settings, "sep09_intent_max_minutes_after_armed_base", 12.0) or 12.0)
    max_det = float(
        getattr(settings, "sep09_intent_max_minutes_after_detect_fallback", 15.0) or 15.0
    )
    elapsed, ref = _minutes_since_reference(alert, now=now)
    if elapsed is None:
        if strict:
            return False, "sep09_rank_one_missing_armed_or_detect_clock"
        # Historical replays / partial alerts — peak-chase + one-rip still apply.
        return True, "sep09_no_armed_or_detect_timestamp_skip_clock"
    limit = max_arm if ref == "armed" else max_det
    if elapsed > limit + 1e-6:
        return False, f"sep09_late_entry_{elapsed:.1f}min_after_{ref}_max_{limit:.0f}"
    return True, f"sep09_early_window_{elapsed:.1f}min"


def _open_premium_move_pct(
    evidence: Mapping[str, Any],
    *,
    symbol: str,
    strike: float,
    side: Any,
    premium: float,
) -> float:
    open_move = float(evidence.get("openPremiumMove") or evidence.get("dailyMovePct") or 0)
    session_move = float(evidence.get("sessionMovePct") or 0)
    off_low = float(evidence.get("offLowMovePct") or 0)
    if off_low <= 0:
        from app.engines.explosion_detector import get_session_low_premium

        low = float(get_session_low_premium(symbol, strike, side) or 0)
        if low > 0 and premium > low:
            off_low = (float(premium) - low) / low * 100.0
    return max(open_move, session_move, off_low)


def open_premium_first_side_rip_ok(
    state: AutoTraderState | None,
    *,
    symbol: str,
    side: Any,
    strike: float,
    premium: float,
    evidence: Mapping[str, Any],
    settings: Any = None,
) -> tuple[bool, str]:
    """
    Sep 9–17 open capture: one vertical off the session open pad (9:15–9:45 IST).

    Waives afternoon-style near-peak / index-rally gates — not a second rip on the same side.
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "sep09_intent_open_premium_first_rip_waive_enabled", True)):
        return False, ""
    from app.engines.session_timing import in_open_premium_window

    if not in_open_premium_window():
        return False, ""
    sym = str(symbol or "").upper()
    if bool(getattr(settings, "sep09_intent_one_rip_per_side_enabled", True)):
        if session_has_sep09_side_rip(state, symbol=sym, side=side):
            return False, "open_premium_side_rip_already_used"

    move = _open_premium_move_pct(
        evidence, symbol=sym, strike=strike, side=side, premium=premium,
    )
    relax = float(getattr(settings, "expiry_open_premium_relax_move_pct", 15.0) or 15.0)
    full = float(getattr(settings, "open_premium_min_move_pct", 25.0) or 25.0)
    cheap_cap = float(getattr(settings, "best_trade_cheap_entry_max_premium_inr", 85.0) or 85.0)
    from app.engines.explosion_detector import get_session_low_premium

    sess_low = float(get_session_low_premium(sym, strike, side) or 0)
    threshold = relax if (sess_low > 0 and sess_low <= cheap_cap) or premium <= cheap_cap else full
    if move + 1e-6 < threshold:
        return False, f"open_premium_move_{move:.1f}pct_below_{threshold:.0f}"

    local = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("ictBaseRelativeMovePct") or 0),
    )
    max_local = float(
        getattr(settings, "sep09_intent_open_premium_max_local_base_pct", 28.0) or 28.0
    )
    if local > max_local + 1e-6:
        return False, f"open_premium_local_base_{local:.1f}pct_over_{max_local:.0f}"

    return True, f"open_premium_first_rip_move_{move:.1f}pct"


def sep09_opposite_flip_waive(
    state: AutoTraderState | None,
    *,
    symbol: str,
    side: Any,
    snap: Any,
    settings: Any = None,
) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "sep09_intent_opposite_flip_waive_enabled", True)):
        return False
    from app.engines.session_mode_feedback import opposite_side_index_flip_waive_active

    ok, _, _ = opposite_side_index_flip_waive_active(
        state, symbol=symbol, side=side, snap=snap,
    )
    return bool(ok)


def sep09_intent_explosion_entry_blocked(
    state: AutoTraderState | None,
    candidate: Any,
    snap: Any = None,
    *,
    settings: Any = None,
    now: Optional[datetime] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Hard Sep 9 intent gate for explosion entries (CALL + PUT).

    Returns (blocked, reason, meta).
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"sep09Intent": True}
    if not bool(getattr(settings, "sep09_intent_enforcement_enabled", True)):
        meta["sep09Intent"] = False
        return False, "", meta

    symbol = str(getattr(candidate, "symbol", "") or "").upper()
    side = getattr(candidate, "side", None)
    strike = float(getattr(candidate, "strike", 0) or 0)
    premium = float(getattr(candidate, "premium", 0) or 0)
    alert = _alert_dict(candidate)
    evidence = _evidence_from_candidate(candidate, alert)
    rank_one = candidate_is_rank_one(candidate, alert, evidence)
    meta["rankOne"] = rank_one
    strict_rank_one = rank_one and bool(
        getattr(settings, "sep09_intent_rank_one_strict_enabled", True)
    )
    meta["rankOneStrict"] = strict_rank_one

    if sep09_opposite_flip_waive(state, symbol=symbol, side=side, snap=snap, settings=settings):
        meta["oppositeFlipWaive"] = True
        return False, "", meta

    if strict_rank_one and bool(
        getattr(settings, "sep09_intent_rank_one_requires_entry_window", True)
    ):
        if not rank_one_timing_in_window(evidence, candidate):
            return True, "sep09_rank_one_outside_entry_window", meta

    two_lane = bool(getattr(settings, "sep09_intent_two_lane_per_side_enabled", True))
    side_has_rip = session_has_sep09_side_rip(state, symbol=symbol, side=side)
    lanes_used = (
        session_sep09_rip_lanes_used(state, symbol=symbol, side=side) if two_lane else set()
    )

    afternoon_ok, afternoon_detail = afternoon_structural_side_rip_ok(
        state,
        symbol=symbol,
        side=side,
        strike=strike,
        premium=premium,
        evidence=evidence,
        alert=alert,
        settings=settings,
        now=now,
    )
    meta["afternoonStructuralCandidate"] = afternoon_ok
    if afternoon_detail:
        meta["afternoonStructuralDetail"] = afternoon_detail

    open_ok, open_detail = open_premium_first_side_rip_ok(
        state,
        symbol=symbol,
        side=side,
        strike=strike,
        premium=premium,
        evidence=evidence,
        settings=settings,
    )

    if two_lane and side_has_rip:
        if afternoon_ok:
            meta["afternoonStructuralRip"] = afternoon_detail
            return False, "", meta
        if bool(getattr(settings, "sep09_intent_one_rip_per_side_enabled", True)):
            if SEP09_LANE_AFTERNOON in lanes_used:
                return True, "sep09_afternoon_structural_lane_already_used", meta
            return True, "sep09_second_leg_requires_afternoon_structural", meta

    if bool(getattr(settings, "sep09_intent_one_rip_per_side_enabled", True)):
        if side_has_rip and not two_lane:
            return True, "sep09_one_early_rip_per_side_already_used", meta

    if open_ok:
        meta["openPremiumFirstRip"] = open_detail
        max_open_arm = float(
            getattr(settings, "sep09_intent_open_premium_max_minutes_after_armed", 25.0) or 25.0
        )
        early_ok, early_detail = sep09_early_near_base_window_ok(
            evidence,
            alert,
            settings=settings,
            now=now,
            strict=False,
        )
        if not early_ok and "late_entry" in early_detail:
            elapsed, ref = _minutes_since_reference(alert, now=now)
            if elapsed is not None and elapsed <= max_open_arm + 1e-6:
                meta["earlyWindowDetail"] = f"open_premium_arm_waive_{elapsed:.1f}min"
                return False, "", meta
        meta["earlyWindowDetail"] = early_detail if early_ok else f"open_premium_waive:{open_detail}"
        return False, "", meta

    chase, chase_reason = sep09_near_peak_after_extended_rip(
        evidence,
        premium=premium,
        symbol=symbol,
        strike=strike,
        side=side,
        alert=alert,
        settings=settings,
    )
    if chase:
        meta["nearPeakChase"] = True
        return True, chase_reason, meta

    early_ok, early_detail = sep09_early_near_base_window_ok(
        evidence, alert, settings=settings, now=now, strict=strict_rank_one,
    )
    meta["earlyWindowDetail"] = early_detail
    if not early_ok:
        return True, early_detail, meta

    return False, "", meta


def sep09_intent_suppresses_rank_one_lot_bypass(
    state: AutoTraderState | None,
    candidate: Any,
    snap: Any = None,
    *,
    settings: Any = None,
    now: Optional[datetime] = None,
) -> bool:
    """Rank-#1 must not unlock full-budget / always-max when Sep 9 intent fails."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "sep09_intent_blocks_rank_one_full_budget", True)):
        return False
    alert = _alert_dict(candidate)
    evidence = _evidence_from_candidate(candidate, alert)
    if not candidate_is_rank_one(candidate, alert, evidence):
        return False
    blocked, _, _ = sep09_intent_explosion_entry_blocked(
        state, candidate, snap, settings=settings, now=now,
    )
    return blocked


def sep09_intent_blocks_must_take_bypass(settings: Any = None) -> bool:
    settings = settings or get_settings()
    return bool(getattr(settings, "sep09_intent_blocks_must_take_bypass", True))


def sep09_intent_evidence_blocked(
    symbol: str,
    side: str,
    evidence: Mapping[str, Any],
    *,
    state: AutoTraderState | None = None,
    snap: Any = None,
    settings: Any = None,
    now: Optional[datetime] = None,
) -> tuple[bool, str]:
    """Checklist / rank audit — same rules without a full EntryCandidate."""

    class _Stub:
        pass

    stub = _Stub()
    stub.symbol = symbol
    stub.side = side
    stub.strike = float(evidence.get("strike") or 0)
    stub.premium = float(evidence.get("premium") or evidence.get("lastPremium") or 0)
    stub.alert = dict(evidence)
    stub.mode = "explosion"
    blocked, reason, _ = sep09_intent_explosion_entry_blocked(
        state, stub, snap, settings=settings, now=now,
    )
    return blocked, reason
