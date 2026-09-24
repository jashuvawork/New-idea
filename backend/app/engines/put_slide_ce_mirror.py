"""CE-win PE mirror + index slide unlock — symmetric to pe_win_ce_mirror for PUT (Sep 9–17)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from app.config import get_settings
from app.engines.best_trade_policy import (
    VALID_BEST_BASE_SETUPS,
    _GOOD_TIMING,
    _number,
    symmetric_best_trade_capture_active,
    symmetric_structural_base_evidence,
)
from app.engines.pe_win_ce_mirror import (
    _building_rip_launch_ok,
    _ce_rally_fingerprint_bar,
    _collect_session_trades,
    _evidence_has_premium_local_base,
    _side_val,
)
from app.engines.rally_capture import _grade_meets_min
from app.models.schemas import Side, SymbolSnapshot

_TRAIL_EXIT_TOKENS = ("trail", "runner", "target", "peak_keep", "peak_velocity", "tp")


def session_call_win_meta(
    state: Any = None,
    *,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """True when the session has a trail-proved CALL win (CE capture succeeded)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "ce_win_pe_mirror_enabled", True)):
        return False, {}

    min_pnl = float(
        getattr(settings, "ce_win_pe_mirror_min_call_win_inr", 1000.0) or 1000.0
    )
    trades = _collect_session_trades(state)
    call_wins: list[Any] = []
    for trade in trades:
        status = str(
            getattr(trade, "status", trade.get("status") if isinstance(trade, dict) else "")
            or ""
        ).upper()
        if status != "CLOSED":
            continue
        side = _side_val(
            getattr(trade, "side", None) or (trade.get("side") if isinstance(trade, dict) else "")
        )
        if side != "CALL":
            continue
        pnl = float(
            getattr(trade, "pnl_inr", None)
            or (trade.get("pnlInr") if isinstance(trade, dict) else 0)
            or 0
        )
        if pnl < min_pnl - 1e-6:
            continue
        reason = str(
            getattr(trade, "exit_reason", None)
            or (trade.get("exitReason") if isinstance(trade, dict) else "")
            or ""
        ).lower()
        if not any(tok in reason for tok in _TRAIL_EXIT_TOKENS):
            continue
        call_wins.append(trade)

    if not call_wins:
        return False, {}

    def _pnl(t: Any) -> float:
        return float(
            getattr(t, "pnl_inr", None) or (t.get("pnlInr") if isinstance(t, dict) else 0) or 0
        )

    best = max(call_wins, key=_pnl)
    sym = str(
        getattr(best, "symbol", None) or (best.get("symbol") if isinstance(best, dict) else "")
        or ""
    ).upper()
    return True, {
        "callWinPnlInr": round(_pnl(best), 2),
        "callWinSymbol": sym,
        "callWinCount": len(call_wins),
    }


def _soft_index_slide_ok(
    symbol: str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Index slide off session high — reduced pts bar when flip not full (PE mirror)."""
    from app.engines.index_rally_side_flip import (
        index_rally_metrics,
        index_rally_side_flip_bypass,
    )

    settings = settings or get_settings()
    full_ok, full_reason, full_meta = index_rally_side_flip_bypass(
        symbol, Side.PUT, snap, settings=settings,
    )
    if full_ok:
        return True, full_reason, {**full_meta, "slideMode": "full_flip"}

    fraction = float(
        getattr(
            settings,
            "ce_win_pe_mirror_slide_pts_fraction",
            getattr(settings, "pe_win_ce_mirror_rally_pts_fraction", 0.5),
        )
        or 0.5
    )
    metrics = index_rally_metrics(symbol, snap, settings=settings)
    slide_pts = float(metrics.get("slidePoints") or 0)
    min_pts = float(metrics.get("minMovePoints") or 0)
    soft_min = min_pts * max(0.1, min(1.0, fraction))
    if slide_pts >= soft_min - 1e-6:
        return True, "ce_win_pe_mirror_soft_slide", {
            **metrics,
            "slideMode": "soft",
            "softMinPts": round(soft_min, 1),
        }
    return False, f"slide_{slide_pts:.0f}<{soft_min:.0f}pts", metrics


def ce_win_pe_mirror_armed(
    state: Any,
    snap: SymbolSnapshot,
    symbol: str,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Mirror leg armed: session CALL win + index slide off session high."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "ce_win_pe_mirror_enabled", True)):
        return False, "disabled", {}

    call_win, call_meta = session_call_win_meta(state, settings=settings)
    if not call_win:
        return False, "no_call_win", call_meta

    if bool(getattr(settings, "ce_win_pe_mirror_require_index_slide", True)):
        slide_ok, slide_reason, slide_meta = _soft_index_slide_ok(
            symbol, snap, settings=settings,
        )
        if not slide_ok:
            return False, slide_reason, {**call_meta, **slide_meta}
        return True, "ce_win_pe_mirror", {**call_meta, **slide_meta, "mirrorReason": slide_reason}

    return True, "ce_win_pe_mirror", call_meta


def put_slide_unlock_armed(
    state: Any,
    snap: SymbolSnapshot,
    symbol: str,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Index slide off session high — PUT unlock without requiring CALL win first."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "put_slide_unlock_enabled", True)):
        return False, "disabled", {}
    slide_ok, slide_reason, slide_meta = _soft_index_slide_ok(
        symbol, snap, settings=settings,
    )
    if not slide_ok:
        return False, slide_reason, slide_meta
    return True, "put_slide_unlock", slide_meta


def _put_premium_launch_ok(
    evidence: Mapping[str, Any],
    *,
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    evidence = evidence if isinstance(evidence, Mapping) else {}
    if bool(
        evidence.get("armedBaseLaunch")
        and (
            evidence.get("firstLift")
            or evidence.get("activeBreakout")
            or evidence.get("displacement")
        )
    ):
        return True
    return _building_rip_launch_ok(
        evidence, readiness_reason=readiness_reason, settings=settings,
    )


def premium_local_base_put_armed(
    evidence: Mapping[str, Any],
    snap: SymbolSnapshot,
    *,
    state: Any = None,
    readiness_reason: str = "",
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """PUT premium V-base at session peak — index slide pts not required (CE-session symmetric)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "put_premium_local_base_unlock_enabled", True)):
        return False, "disabled", {}
    evidence = evidence if isinstance(evidence, Mapping) else {}
    if not _evidence_has_premium_local_base(evidence):
        return False, "no_premium_local_base", {}
    if not _put_premium_launch_ok(
        evidence, readiness_reason=readiness_reason, settings=settings,
    ):
        return False, "no_launch", {}

    local = _number(evidence.get("localBaseMovePct") or evidence.get("localBasePct"))
    max_local = float(
        getattr(settings, "put_premium_local_base_max_local_pct", 18.0) or 18.0
    )
    if local > max_local + 1e-6:
        return False, f"local_{local:.0f}>{max_local:.0f}", {"localBasePct": local}

    meta: dict[str, Any] = {
        "localBasePct": round(local, 2),
        "mode": "premium_local_base",
    }
    call_win, call_meta = session_call_win_meta(state, settings=settings)
    if call_win:
        return True, "put_premium_local_base_ce_session", {**meta, **call_meta}

    if not bool(getattr(settings, "put_premium_local_base_require_index_peak", True)):
        return True, "put_premium_local_base", meta

    if evidence.get("ictIndexPeakSlowV") or evidence.get("indexPeakSlowV"):
        return True, "put_premium_local_base_peak_flag", meta

    from app.engines.spot_direction import index_trough_momentum_turn

    if snap is not None and snap.spotChart is not None:
        if index_trough_momentum_turn(Side.PUT, snap.spotChart, settings=settings):
            return True, "put_premium_local_base_peak_turn", meta

    off_high = _number(evidence.get("offHighMovePct"))
    min_off = float(
        getattr(settings, "put_premium_local_base_min_off_high_pct", 2.0) or 2.0
    )
    if off_high >= min_off - 1e-6:
        return True, "put_premium_local_base_off_high", {**meta, "offHighMovePct": off_high}

    return False, "no_peak_context", meta


def put_pe_base_context_armed(
    state: Any,
    snap: SymbolSnapshot,
    symbol: str,
    evidence: Mapping[str, Any] | None = None,
    *,
    readiness_reason: str = "",
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """PUT base context: index slide, CE-win mirror, or premium local-base V-lift."""
    settings = settings or get_settings()

    if symmetric_best_trade_capture_active(settings) and evidence is not None:
        if symmetric_structural_base_evidence(evidence, settings=settings):
            local = max(
                _number(evidence.get("localBaseMovePct")),
                _number(evidence.get("ictBaseRelativeMovePct")),
                _number(evidence.get("offHighMovePct")),
            )
            return True, "symmetric_pe_raw_base", {"localBasePct": round(local, 2)}

    slide_ok, slide_reason, slide_meta = put_slide_entry_unlock_armed(
        state, snap, symbol, settings=settings,
    )
    if slide_ok:
        return True, slide_reason, slide_meta
    if evidence is not None:
        return premium_local_base_put_armed(
            evidence,
            snap,
            state=state,
            readiness_reason=readiness_reason,
            settings=settings,
        )
    return False, slide_reason, slide_meta


def put_slide_entry_unlock_armed(
    state: Any,
    snap: SymbolSnapshot,
    symbol: str,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """CE-win mirror OR index-slide-only PUT unlock armed."""
    settings = settings or get_settings()
    mirror_ok, mirror_reason, mirror_meta = ce_win_pe_mirror_armed(
        state, snap, symbol, settings=settings,
    )
    if mirror_ok:
        return True, mirror_reason, mirror_meta
    slide_ok, slide_reason, slide_meta = put_slide_unlock_armed(
        state, snap, symbol, settings=settings,
    )
    if slide_ok:
        return True, slide_reason, slide_meta
    return False, slide_reason or mirror_reason, {**mirror_meta, **slide_meta}


def put_slide_unlock_fingerprint(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any] | None,
    elite_assessment: Mapping[str, Any] | None = None,
    *,
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    symbol: str = "",
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    """PUT entry bar when index slide unlock is armed (no CALL win required)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "put_slide_unlock_enabled", True)):
        return False
    if state is None or snap is None:
        return False

    sym = str(symbol or evidence.get("symbol") or "").upper()
    if not sym:
        sym = str(getattr(snap, "symbol", "") or "").upper()
    armed, _, _ = put_pe_base_context_armed(
        state,
        snap,
        sym,
        evidence,
        readiness_reason=readiness_reason,
        settings=settings,
    )
    if not armed:
        return False
    return _ce_rally_fingerprint_bar(
        evidence,
        ranking,
        elite_assessment,
        readiness_reason=readiness_reason,
        settings=settings,
    )


def ce_win_pe_mirror_fingerprint(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any] | None,
    elite_assessment: Mapping[str, Any] | None = None,
    *,
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    symbol: str = "",
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    """PUT entry bar mirrored from a session CALL win."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "ce_win_pe_mirror_enabled", True)):
        return False
    if state is None or snap is None:
        return False

    sym = str(symbol or evidence.get("symbol") or "").upper()
    if not sym:
        sym = str(getattr(snap, "symbol", "") or "").upper()
    armed, _, _ = ce_win_pe_mirror_armed(state, snap, sym, settings=settings)
    if not armed:
        return False
    return _ce_rally_fingerprint_bar(
        evidence,
        ranking,
        elite_assessment,
        readiness_reason=readiness_reason,
        settings=settings,
    )


def put_slide_entry_unlock_fingerprint(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any] | None,
    elite_assessment: Mapping[str, Any] | None = None,
    *,
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    symbol: str = "",
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    """True when mirror or slide-only PUT unlock fingerprint matches."""
    if ce_win_pe_mirror_fingerprint(
        evidence,
        ranking,
        elite_assessment,
        state=state,
        snap=snap,
        symbol=symbol,
        readiness_reason=readiness_reason,
        settings=settings,
    ):
        return True
    return put_slide_unlock_fingerprint(
        evidence,
        ranking,
        elite_assessment,
        state=state,
        snap=snap,
        symbol=symbol,
        readiness_reason=readiness_reason,
        settings=settings,
    )


def _symmetric_expiry_otm_put_waive(
    alert: Mapping[str, Any],
    *,
    settings: Any = None,
) -> bool:
    """Sep 9–17 shallow OTM PUT at structural base on expiry (73900 PE pattern)."""
    settings = settings or get_settings()
    if not symmetric_best_trade_capture_active(settings):
        return False
    evidence = alert if isinstance(alert, Mapping) else {}
    if not symmetric_structural_base_evidence(evidence, settings=settings):
        return False
    tier = str(evidence.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False
    if evidence.get("shallowOtmLocalBaseTradeable"):
        return True
    if bool(
        evidence.get("armedBaseLaunch")
        and (
            evidence.get("firstLift")
            or evidence.get("activeBreakout")
            or evidence.get("displacement")
        )
    ):
        return True
    return False


def put_slide_entry_unlock_expiry_otm_bypass(
    candidate: Any,
    snap: Any,
    alert: Mapping[str, Any] | None = None,
    *,
    state: Any = None,
    settings: Any = None,
) -> bool:
    """Waive expiry OTM block for slide-unlocked ELITE/EXPLODING PE (Sep 9 SENSEX 73900 PE)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "put_slide_unlock_waive_expiry_otm", True)):
        return False
    if _side_val(getattr(candidate, "side", None)) != "PUT" or state is None or snap is None:
        return False

    from app.engines.best_trade_policy import (
        mid_rip_best_trade_candidate,
        put_pe_parity_from_candidate,
    )
    from app.engines.elite_score_engine import build_elite_assessment
    from app.engines.trade_ranking import rank_entry_candidate

    alert_map = alert if isinstance(alert, Mapping) else {}
    if put_pe_parity_from_candidate(candidate, snap, settings=settings, state=state):
        return True
    if _symmetric_expiry_otm_put_waive(alert_map, settings=settings):
        return True

    ranking = rank_entry_candidate(candidate, snapshot=snap)
    assessment = build_elite_assessment(
        {**alert_map, **dict(ranking.get("evidence") or {})},
        ranking,
    )
    symbol = str(
        getattr(candidate, "symbol", None)
        or alert_map.get("symbol")
        or getattr(snap, "symbol", "")
        or ""
    ).upper()
    merged = {**alert_map, **dict(ranking.get("evidence") or {})}
    if put_slide_entry_unlock_fingerprint(
        merged,
        ranking,
        assessment,
        state=state,
        snap=snap,
        symbol=symbol,
        settings=settings,
    ):
        return True
    if put_pe_base_context_armed(
        state, snap, symbol, merged, settings=settings,
    )[0]:
        return mid_rip_best_trade_candidate(
            candidate, alert_map, assessment, settings=settings,
        )
    return False


def put_slide_near_miss_waive(
    alert: Optional[dict[str, Any]],
    *,
    snap: Optional[SymbolSnapshot] = None,
    state: Any = None,
    ranking: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    """Waive explosion_near_miss for building PUT when slide unlock is armed."""
    settings = settings or get_settings()
    near_miss_enabled = (
        bool(getattr(settings, "ce_win_pe_mirror_near_miss_enabled", True))
        or bool(getattr(settings, "put_slide_unlock_near_miss_enabled", True))
    )
    if not near_miss_enabled:
        return False
    if not isinstance(alert, dict) or str(alert.get("side") or "").upper() != "PUT":
        return False
    if snap is None or state is None:
        return False
    sym = str(alert.get("symbol") or getattr(snap, "symbol", "") or "").upper()
    if not put_pe_base_context_armed(
        state,
        snap,
        sym,
        alert,
        readiness_reason=readiness_reason,
        settings=settings,
    )[0]:
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False
    rr = str(readiness_reason or "").lower()
    if "building" in rr or "rip" in rr:
        return True
    if alert.get("armedBaseLaunch") or alert.get("firstLift"):
        return True
    return _building_rip_launch_ok(alert, readiness_reason=readiness_reason, settings=settings)


def put_slide_premium_fade_bypass(
    *,
    side: Side | str,
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    symbol: str = "",
    evidence: Optional[Mapping[str, Any]] = None,
    ranking: Optional[Mapping[str, Any]] = None,
    assessment: Optional[Mapping[str, Any]] = None,
    settings: Any = None,
) -> bool:
    """Allow shallow premium fade fill on slide-unlocked PUT first lift."""
    settings = settings or get_settings()
    fade_waive = (
        bool(getattr(settings, "ce_win_pe_mirror_waive_premium_fade", True))
        or bool(getattr(settings, "put_slide_unlock_waive_mtf_premium_fade", True))
    )
    if not fade_waive:
        return False
    if _side_val(side) != "PUT" or snap is None or state is None:
        return False
    sym = str(symbol or (evidence or {}).get("symbol") or getattr(snap, "symbol", "") or "").upper()
    return put_slide_entry_unlock_fingerprint(
        evidence or {},
        ranking,
        assessment,
        state=state,
        snap=snap,
        symbol=sym,
        settings=settings,
    )
