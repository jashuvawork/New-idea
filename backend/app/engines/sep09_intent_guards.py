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

    def _is_explosion_trade(trade: Any) -> bool:
        ctx = getattr(trade, "entryContext", None) or {}
        mode = str(ctx.get("selectionMode") or "").lower()
        st = getattr(trade, "strategyType", None)
        st_u = st.value if hasattr(st, "value") else str(st or "").upper()
        if mode == "explosion" or st_u == "EXPLOSIVE":
            return True
        return False

    for t in list(state.openPaperTrades or []) + list(state.closedPaperTrades or []):
        ts = str(getattr(t, "symbol", "") or "").upper()
        if ts != sym:
            continue
        if _side_str(getattr(t, "side", "")) != side_u:
            continue
        if _is_explosion_trade(t):
            return True
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
) -> tuple[bool, str]:
    settings = settings or get_settings()
    from app.engines.best_trade_policy import symmetric_structural_base_evidence

    max_local = float(getattr(settings, "sep09_intent_max_local_base_pct", 20.0) or 20.0)
    if not symmetric_structural_base_evidence(evidence, settings=settings):
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
        # Historical replays / partial alerts — peak-chase + one-rip still apply.
        return True, "sep09_no_armed_or_detect_timestamp_skip_clock"
    limit = max_arm if ref == "armed" else max_det
    if elapsed > limit + 1e-6:
        return False, f"sep09_late_entry_{elapsed:.1f}min_after_{ref}_max_{limit:.0f}"
    return True, f"sep09_early_window_{elapsed:.1f}min"


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

    if sep09_opposite_flip_waive(state, symbol=symbol, side=side, snap=snap, settings=settings):
        meta["oppositeFlipWaive"] = True
        return False, "", meta

    if bool(getattr(settings, "sep09_intent_one_rip_per_side_enabled", True)):
        if session_has_sep09_side_rip(state, symbol=symbol, side=side):
            return True, "sep09_one_early_rip_per_side_already_used", meta

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
        evidence, alert, settings=settings, now=now,
    )
    meta["earlyWindowDetail"] = early_detail
    if not early_ok:
        return True, early_detail, meta

    return False, "", meta


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
