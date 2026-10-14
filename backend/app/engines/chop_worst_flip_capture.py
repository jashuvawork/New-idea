"""Chop / WORST day flip capture — new bases, V-rips, and FTVs after intraday CE↔PE turns.

On two-sided chop sessions the book must not stay stuck on the morning leg while the
other side rips (Oct 14: NIFTY CE morning, SENSEX PUT ~11:32 missed). This module:

- Surfaces ELITE structural moments to the selector outside the open window when the
  index leg flips (or is confirming a flip).
- Boosts rank for flip-aligned V / FTV / armed-base candidates.
- Bypasses sticky directional lock on the *flipped-to* side when structure is fresh.
- Tightens chop-live near-base waivers so extended-session re-tags (high session move,
  weak velocity) cannot skip extended-chase guards — while genuine flip bases still pass.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot

_FLIP_STRUCTURAL_MOMENTS = frozenset(
    {
        "armed_base_launch",
        "first_lift_local_base",
        "v_rip_session_low",
        "v_rip_session_high",
        "flat_then_vertical",
        "volume_awaken",
        "ict_base_armed",
        "ELITE_BASE_READY",
    }
)


def _side_str(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def chop_worst_flip_capture_enabled(settings: Any = None) -> bool:
    settings = settings or get_settings()
    return bool(getattr(settings, "chop_worst_flip_capture_enabled", True))


def chop_worst_context_active(
    state: AutoTraderState | None,
    snapshots: dict[str, SymbolSnapshot] | None,
    snap: SymbolSnapshot | None,
    *,
    settings: Any = None,
) -> bool:
    """True on chop / WORST session labels (same scope as chop-live guards)."""
    from app.engines.chop_live_guards import chop_live_guard_day_active

    settings = settings or get_settings()
    if snap is None:
        return False
    return chop_live_guard_day_active(state or AutoTraderState(), snap, snapshots)


def _evidence_blob(
    alert: Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    alert = dict(alert if isinstance(alert, Mapping) else {})
    evidence = dict(evidence if isinstance(evidence, Mapping) else {})
    nested = evidence.get("evidence")
    if isinstance(nested, Mapping):
        evidence = {**evidence, **nested}
    return {**alert, **evidence}


def flip_structural_evidence(
    alert: Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | None = None,
    *,
    readiness_reason: str = "",
) -> bool:
    """V / FTV / armed-base / first-lift pad — symmetric CE + PE."""
    blob = _evidence_blob(alert, evidence)
    moment = str(blob.get("momentType") or "").lower()
    if moment in {m.lower() for m in _FLIP_STRUCTURAL_MOMENTS}:
        return True
    rr = str(
        readiness_reason
        or blob.get("firstLiftReadinessReason")
        or blob.get("ictBaseReadinessReason")
        or ""
    ).lower()
    if any(tok in rr for tok in ("v_rip", "armed_base", "first_lift", "flat_vertical")):
        return True
    from app.engines.top_moment_gate import classify_top_moment_type

    top = classify_top_moment_type(blob)
    if top in ("V", "FTV"):
        return True
    return any(
        bool(blob.get(k))
        for k in (
            "vRipReady",
            "ictVRipReady",
            "armedBaseLaunch",
            "ictArmedBaseLaunch",
            "ictBaseArmed",
            "ictFirstLift",
            "firstLift",
            "ictFlatThenVertical",
            "flatThenVertical",
            "indexConfirmedLocalBase",
        )
    )


def _candidate_session_move(candidate: Any, alert: Mapping[str, Any] | None) -> float:
    event = getattr(candidate, "explosion_event", None)
    move = 0.0
    if event is not None:
        move = max(
            _num(getattr(event, "daily_move_pct", 0)),
            _num(getattr(event, "peak_move_pct", 0)),
        )
    if isinstance(alert, Mapping):
        move = max(
            move,
            _num(alert.get("dailyMovePct")),
            _num(alert.get("peakMovePct")),
            _num(alert.get("sessionMovePct")),
        )
    pre = getattr(candidate, "pretrade_meta", None) or {}
    if isinstance(pre, dict):
        move = max(move, _num(pre.get("sessionMovePct")))
    return move


def _candidate_velocity3s(candidate: Any, alert: Mapping[str, Any] | None) -> float:
    event = getattr(candidate, "explosion_event", None)
    v3 = _num(getattr(event, "velocity_3s", 0)) if event is not None else 0.0
    if isinstance(alert, Mapping):
        v3 = max(v3, _num(alert.get("velocity3s")))
    pre = getattr(candidate, "pretrade_meta", None) or {}
    if isinstance(pre, dict):
        ta = pre.get("timingAssessment")
        if isinstance(ta, dict):
            v3 = max(v3, _num(ta.get("liveVelocity3s")))
        v3 = max(v3, _num(pre.get("velocity3s")))
    return v3


def session_flip_supports_side(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    state: AutoTraderState | None,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    True when index trend or side-regime confirms (or is flipping toward) this side.
    """
    settings = settings or get_settings()
    side_v = _side_str(side)
    sym = str(symbol or snap.symbol or "").upper()
    meta: dict[str, Any] = {"symbol": sym, "side": side_v}

    from app.engines.index_session_dominant_trend import (
        index_session_dominant_trend,
        side_aligns_with_dominant_trend,
    )

    dominant, trend_meta = index_session_dominant_trend(
        sym, snap, state, settings=settings, track_flip=True,
    )
    meta["dominantTrend"] = dominant
    meta.update({k: trend_meta.get(k) for k in ("indexTrendFlip", "dominantTrendFlipped")})

    aligned = side_aligns_with_dominant_trend(side_v, dominant)
    if aligned and trend_meta.get("dominantTrendFlipped"):
        return True, "dominant_trend_flipped", meta
    flip_tag = str(trend_meta.get("indexTrendFlip") or "")
    if side_v == "PUT" and flip_tag in ("slide_dominant", "mom5_slide") and aligned:
        return True, flip_tag, meta
    if side_v == "CALL" and flip_tag in ("rally_dominant", "mom5_rally") and aligned:
        return True, flip_tag, meta

    from app.engines.side_regime import side_regime_state

    reg = side_regime_state(sym)
    meta["sideRegime"] = reg
    if reg.get("side") == side_v:
        return True, "side_regime_confirmed", meta
    flip_target = str(reg.get("flipTarget") or "")
    pending = int(reg.get("pendingCount") or 0)
    min_pending = int(getattr(settings, "chop_worst_flip_min_regime_pending", 2) or 2)
    if flip_target == side_v and pending >= min_pending:
        return True, "side_regime_flip_pending", meta

    if aligned and dominant != "NEUTRAL":
        return True, "dominant_trend_aligned", meta

    return False, "no_flip_support", meta


def chop_worst_flip_chop_live_waive_ok(
    candidate: Any,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    *,
    snapshots: dict[str, SymbolSnapshot] | None = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """
    Near-base chop-live waiver with flip discipline on chop/worst days.

    Extended session move without active flip + velocity → do not waive (blocks late chase).
    """
    from app.engines.best_trade_policy import symmetric_best_trade_at_base_capture

    settings = settings or get_settings()
    alert = getattr(candidate, "alert", None)
    alert_map = alert if isinstance(alert, dict) else {}
    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}

    near_ok, near_reason = symmetric_best_trade_at_base_capture(
        alert_map,
        alert_map,
        ranking=ranking if isinstance(ranking, dict) else None,
        settings=settings,
    )
    if not near_ok:
        return False, ""

    if not chop_worst_flip_capture_enabled(settings):
        return True, near_reason
    if not chop_worst_context_active(state, snapshots, snap, settings=settings):
        return True, near_reason

    evidence = ranking.get("evidence") if isinstance(ranking, dict) else {}
    if not isinstance(evidence, dict):
        evidence = {}
    structural = flip_structural_evidence(alert_map, evidence)
    session_move = _candidate_session_move(candidate, alert_map)
    v3 = _candidate_velocity3s(candidate, alert_map)
    extended_floor = float(
        getattr(settings, "chop_worst_flip_extended_session_move_pct", 24.0) or 24.0
    )
    min_v3 = float(getattr(settings, "chop_worst_flip_min_velocity_3s", 1.2) or 1.2)

    sym = str(getattr(candidate, "symbol", "") or snap.symbol or "").upper()
    side = getattr(candidate, "side", Side.CALL)
    flip_ok, flip_tag, _ = session_flip_supports_side(
        sym, side, snap, state, settings=settings,
    )

    if session_move >= extended_floor:
        if not (structural and flip_ok and v3 >= min_v3):
            return False, "chop_worst_extended_need_active_flip"

    if structural and flip_ok:
        return True, f"chop_worst_flip_{flip_tag}"
    if structural and v3 >= min_v3:
        return True, "chop_worst_flip_velocity"
    return True, near_reason


def chop_worst_flip_selector_preserve(
    alert: Mapping[str, Any],
    snap: SymbolSnapshot | None,
    state: AutoTraderState | None,
    snapshots: dict[str, SymbolSnapshot] | None,
    *,
    settings: Any = None,
) -> bool:
    """Keep ELITE structural alerts in the selector feed after the open window on flip days."""
    from app.engines.open_rip_selector import open_rip_elite_structural_evidence

    settings = settings or get_settings()
    if not chop_worst_flip_capture_enabled(settings):
        return False
    if not isinstance(alert, dict) or snap is None:
        return False
    if not bool(getattr(settings, "chop_worst_flip_selector_preserve_enabled", True)):
        return False
    if not chop_worst_context_active(state, snapshots, snap, settings=settings):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    if not open_rip_elite_structural_evidence(alert):
        return False
    score = _num(alert.get("explosionScore") or alert.get("score"))
    if score < float(getattr(settings, "explosion_alerts_force_include_min_score", 90.0) or 90.0) - 1e-6:
        return False

    side_raw = str(alert.get("side") or "").upper()
    side = Side.CALL if side_raw == "CALL" else Side.PUT if side_raw == "PUT" else None
    if side is None:
        return False
    sym = str(alert.get("symbol") or snap.symbol or "").upper()
    flip_ok, _, _ = session_flip_supports_side(sym, side, snap, state, settings=settings)
    if flip_ok:
        return True
    v3 = _num(alert.get("velocity3s"))
    min_v3 = float(getattr(settings, "chop_worst_flip_min_velocity_3s", 1.2) or 1.2)
    return v3 >= min_v3 and flip_structural_evidence(alert, alert)


def chop_worst_flip_rank_bonus(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    settings: Any = None,
) -> float:
    settings = settings or get_settings()
    if not chop_worst_flip_capture_enabled(settings):
        return 0.0
    snap = snapshots.get(str(getattr(candidate, "symbol", "") or "").upper()) or getattr(
        candidate, "snap", None,
    )
    if snap is None or not chop_worst_context_active(state, snapshots, snap, settings=settings):
        return 0.0
    alert = getattr(candidate, "alert", None)
    alert_map = alert if isinstance(alert, dict) else {}
    pre = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pre.get("causalRanking") if isinstance(pre, dict) else {}
    evidence = ranking.get("evidence") if isinstance(ranking, dict) else {}
    if not isinstance(evidence, dict):
        evidence = {}
    if not flip_structural_evidence(alert_map, evidence):
        return 0.0

    sym = str(getattr(candidate, "symbol", "") or "").upper()
    side = getattr(candidate, "side", Side.CALL)
    flip_ok, flip_tag, meta = session_flip_supports_side(
        sym, side, snap, state, settings=settings,
    )
    if not flip_ok:
        return 0.0

    base = float(getattr(settings, "chop_worst_flip_rank_bonus", 18.0) or 18.0)
    extra = float(getattr(settings, "chop_worst_flip_rank_flip_bonus", 8.0) or 8.0)
    bonus = base
    if meta.get("dominantTrendFlipped") or "flip" in flip_tag:
        bonus += extra

    v3 = _candidate_velocity3s(candidate, alert_map)
    if v3 >= float(getattr(settings, "chop_worst_flip_min_velocity_3s", 1.2) or 1.2):
        bonus += min(6.0, v3 * 2.0)
    return bonus


def chop_worst_flip_directional_bypass(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    state: AutoTraderState | None = None,
    candidate: Any = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    settings = settings or get_settings()
    if not chop_worst_flip_capture_enabled(settings):
        return False, "disabled", {}
    if not bool(getattr(settings, "chop_worst_flip_directional_bypass_enabled", True)):
        return False, "directional_bypass_off", {}
    if state is None:
        return False, "no_state", {}

    snapshots = {str(symbol or snap.symbol or "").upper(): snap}
    if not chop_worst_context_active(state, snapshots, snap, settings=settings):
        return False, "not_chop_worst", {}

    alert = getattr(candidate, "alert", None) if candidate is not None else None
    alert_map = alert if isinstance(alert, dict) else {}
    if not flip_structural_evidence(alert_map, alert_map):
        return False, "not_structural", {}

    flip_ok, flip_tag, meta = session_flip_supports_side(
        str(symbol or snap.symbol or "").upper(),
        side,
        snap,
        state,
        settings=settings,
    )
    if not flip_ok:
        return False, "no_flip_support", meta

    v3 = _candidate_velocity3s(candidate, alert_map) if candidate is not None else _num(
        alert_map.get("velocity3s"),
    )
    min_v3 = float(getattr(settings, "chop_worst_flip_min_velocity_3s", 1.2) or 1.2)
    session_move = _candidate_session_move(candidate, alert_map) if candidate is not None else max(
        _num(alert_map.get("dailyMovePct")),
        _num(alert_map.get("peakMovePct")),
    )
    extended_floor = float(
        getattr(settings, "chop_worst_flip_extended_session_move_pct", 24.0) or 24.0
    )
    if session_move >= extended_floor and v3 < min_v3:
        return False, "extended_without_velocity", meta

    return True, f"chop_worst_flip_{flip_tag}", meta
