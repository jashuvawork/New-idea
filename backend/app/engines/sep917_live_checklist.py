"""
Sep 9–17 live trade checklist — four steps + lane labels for HUD / funnel context.

EOD replay confirms; live session uses the same lane vocabulary as production gates.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot

CHECKLIST_VERSION = "sep917-v1"

_LANES = frozenset({
    "NEAR_BASE_SEP917",
    "RALLY_UNLOCK",
    "SLIDE_UNLOCK",
    "BUILDING_RIP",
    "CHASE_BLOCK",
    "NONE",
})

_STEP_GUIDE = (
    {
        "id": 1,
        "key": "indexStructure",
        "title": "Index structure",
        "question": "CE: rally off session low / PE: slide off session high (or unlock armed)?",
    },
    {
        "id": 2,
        "key": "optionShape",
        "title": "Option shape",
        "question": "Near-base FTV/V/elite (≤~20% off base) or helper building rip — not naked +40% chase?",
    },
    {
        "id": 3,
        "key": "sessionContext",
        "title": "Session context",
        "question": "Day mode, chop post-win FOMO, and side blocks allow this lane?",
    },
    {
        "id": 4,
        "key": "funnelAuthorize",
        "title": "Funnel authorize",
        "question": "Top-moment / elite path clears rank and timing gates?",
    },
)


def _step(ok: bool, detail: str) -> dict[str, Any]:
    return {"ok": bool(ok), "detail": str(detail or "")}


def _local_move_pct(evidence: Mapping[str, Any]) -> float:
    from app.engines.best_trade_policy import _number

    return max(
        _number(evidence.get("localBaseMovePct")),
        _number(evidence.get("ictBaseRelativeMovePct")),
        _number(evidence.get("offLowMovePct")),
        _number(evidence.get("offHighMovePct")),
        _number(evidence.get("local_move_pct")),
        _number(evidence.get("localMovePct")),
    )


def resolve_sep917_lane(
    side: str,
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    symbol: str = "",
    readiness_reason: str = "",
    settings: Any = None,
) -> str:
    """Pick the primary Sep 9–17 capture lane for this candidate."""
    settings = settings or get_settings()
    side_u = str(side or evidence.get("side") or "").upper()
    sym = str(symbol or evidence.get("symbol") or getattr(snap, "symbol", "") or "").upper()

    from app.engines.building_ftv_gates import helper_building_rip_top_moment_ok

    if helper_building_rip_top_moment_ok(
        evidence, ranking, readiness_reason=readiness_reason
    ):
        return "BUILDING_RIP"

    if side_u == "CALL":
        from app.engines.pe_win_ce_mirror import call_rally_entry_unlock_fingerprint

        if call_rally_entry_unlock_fingerprint(
            evidence,
            ranking,
            state=state,
            snap=snap,
            symbol=sym,
            readiness_reason=readiness_reason,
            settings=settings,
        ):
            return "RALLY_UNLOCK"
    elif side_u == "PUT":
        from app.engines.put_slide_ce_mirror import put_slide_entry_unlock_fingerprint

        if put_slide_entry_unlock_fingerprint(
            evidence,
            ranking,
            state=state,
            snap=snap,
            symbol=sym,
            readiness_reason=readiness_reason,
            settings=settings,
        ):
            return "SLIDE_UNLOCK"

    from app.engines.best_trade_policy import symmetric_structural_base_evidence
    from app.engines.top_moment_gate import classify_top_moment_type

    max_local = float(
        getattr(settings, "best_trade_near_base_max_local_pct", 20.0) or 20.0
    )
    local = _local_move_pct(evidence)
    moment = classify_top_moment_type(evidence)
    from app.engines.sep09_intent_guards import sep09_near_peak_after_extended_rip

    chase, _ = sep09_near_peak_after_extended_rip(
        evidence,
        premium=float(evidence.get("premium") or evidence.get("lastPremium") or 0),
        symbol=str(symbol or evidence.get("symbol") or ""),
        strike=float(evidence.get("strike") or 0),
        side=side_u,
        alert=evidence,
        settings=settings,
    )
    if chase:
        return "CHASE_BLOCK"
    if symmetric_structural_base_evidence(evidence, settings=settings) and moment:
        return "NEAR_BASE_SEP917"
    if local > max_local + 1e-6 and moment is None:
        return "CHASE_BLOCK"
    return "NONE"


def _index_structure_ok(
    side: str,
    *,
    snap: Optional[SymbolSnapshot],
    symbol: str,
    evidence: Mapping[str, Any],
    state: Any,
    settings: Any,
    lane: str,
) -> tuple[bool, str]:
    side_u = str(side or "").upper()
    sym = str(symbol or "").upper()
    if snap is None or not sym:
        return False, "no_index_snapshot"

    if lane in ("NEAR_BASE_SEP917", "BUILDING_RIP", "RALLY_UNLOCK", "SLIDE_UNLOCK"):
        from app.engines.best_trade_policy import symmetric_structural_base_evidence

        if symmetric_structural_base_evidence(evidence, settings=settings):
            return True, f"{lane.lower()}_structural_base_index_ok"
        if lane in ("RALLY_UNLOCK", "SLIDE_UNLOCK"):
            pass  # fall through to fingerprint checks below
        elif lane == "BUILDING_RIP":
            from app.engines.building_ftv_gates import helper_building_rip_top_moment_ok

            if helper_building_rip_top_moment_ok(evidence, {}, readiness_reason=""):
                return True, "building_rip_helper_index_ok"

    try:
        from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

        if side_u == "CALL":
            ok, _, meta = index_rally_side_flip_bypass(
                sym, Side.CALL, snap, settings=settings,
            )
            if ok:
                return True, "index_rally_off_session_low"
            from app.engines.pe_win_ce_mirror import call_ce_base_context_armed

            armed, reason, _ = call_ce_base_context_armed(
                state, snap, sym, dict(evidence), settings=settings,
            )
            if armed:
                return True, reason or "call_rally_context_armed"
            return False, meta.get("reason") or reason or "call_index_not_rallying"
        if side_u == "PUT":
            ok, _, meta = index_rally_side_flip_bypass(
                sym, Side.PUT, snap, settings=settings,
            )
            if ok:
                return True, "index_slide_off_session_high"
            from app.engines.put_slide_ce_mirror import put_pe_base_context_armed

            armed, reason, _ = put_pe_base_context_armed(
                state, snap, sym, dict(evidence), settings=settings,
            )
            if armed:
                return True, reason or "put_slide_context_armed"
            return False, meta.get("reason") or reason or "put_index_not_sliding"
    except Exception as exc:
        return False, f"index_check_error:{exc.__class__.__name__}"
    return False, "unknown_side"


def _option_shape_ok(
    side: str,
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    settings: Any,
    lane: str,
    readiness_reason: str = "",
) -> tuple[bool, str]:
    from app.engines.best_trade_policy import symmetric_structural_base_evidence
    from app.engines.building_ftv_gates import helper_building_rip_top_moment_ok
    from app.engines.top_moment_gate import classify_top_moment_type

    if lane == "BUILDING_RIP":
        if helper_building_rip_top_moment_ok(
            evidence, ranking, readiness_reason=readiness_reason
        ):
            return True, "helper_building_rip"
        return False, "building_rip_lane_not_confirmed"

    max_local = float(
        getattr(settings, "best_trade_near_base_max_local_pct", 20.0) or 20.0
    )
    local = _local_move_pct(evidence)
    moment = classify_top_moment_type(evidence)

    if lane == "CHASE_BLOCK":
        return False, f"naked_chase_local_{local:.1f}pct"

    from app.engines.sep09_intent_guards import sep09_near_peak_after_extended_rip

    near_peak, np_reason = sep09_near_peak_after_extended_rip(
        evidence,
        premium=float(evidence.get("premium") or evidence.get("lastPremium") or 0),
        symbol=str(evidence.get("symbol") or ""),
        strike=float(evidence.get("strike") or 0),
        side=side,
        alert=evidence,
        settings=settings,
    )
    if near_peak:
        return False, np_reason

    if symmetric_structural_base_evidence(evidence, settings=settings) and moment:
        return True, f"near_base_{moment.lower()}"

    if moment and local <= max_local + 1e-6:
        return True, f"top_moment_{moment.lower()}"

    if moment and lane in ("RALLY_UNLOCK", "SLIDE_UNLOCK"):
        return True, f"unlock_lane_{moment.lower()}"

    if local > max_local + 1e-6:
        return False, f"extended_move_{local:.1f}pct_without_lane"
    if not moment:
        return False, "no_ftv_v_elite_shape"
    return True, f"shape_{moment.lower()}"


def _session_context_ok(
    side: str,
    *,
    day_mode: str,
    state: Any,
    settings: Any,
    lane: str,
) -> tuple[bool, str]:
    from app.engines.chop_day_guards import chop_post_win_afternoon_fomo_risk
    from app.engines.elite_score_engine import elite_side_day_mode_blocked

    blocked, reason = elite_side_day_mode_blocked(
        side,
        day_mode,
        settings=settings,
        state=state,
    )
    fomo, fomo_reasons = chop_post_win_afternoon_fomo_risk(
        state, day_mode=day_mode, settings=settings,
    )
    if fomo and lane in ("CHASE_BLOCK", "NONE"):
        return False, "chop_post_win_afternoon_fomo"

    sym_cap = bool(getattr(settings, "symmetric_best_trade_capture_enabled", True))
    detail = f"symmetric_capture={sym_cap}"
    if fomo:
        detail += ";post_win_fomo_watch"
    if blocked:
        return False, f"day_mode_block:{reason}"
    return True, detail


def _funnel_authorize_ok(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    side: str,
    day_mode: str,
    state: Any,
    snapshots: Any,
    readiness_reason: str,
    settings: Any,
    lane: str,
) -> tuple[bool, str]:
    from app.engines.sep09_intent_guards import sep09_intent_evidence_blocked
    from app.engines.top_moment_gate import top_moment_entry_allowed

    side_u = str(side or "").upper()
    sym = str(evidence.get("symbol") or "").upper()
    sep_blocked, sep_reason = sep09_intent_evidence_blocked(
        sym or "NIFTY",
        side_u,
        evidence,
        state=state,
        snap=snapshots.get(sym) if isinstance(snapshots, dict) else None,
        settings=settings,
    )
    if sep_blocked:
        return False, sep_reason

    ok, reason, moment = top_moment_entry_allowed(
        evidence,
        ranking,
        day_mode=day_mode,
        readiness_reason=readiness_reason,
        state=state,
        snapshots=snapshots,
        side=side_u,
    )
    if ok:
        return True, moment or reason or "top_moment_ok"
    return False, reason or "funnel_blocked"


def evaluate_sep917_live_checklist(
    symbol: str,
    side: str,
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    snap: Optional[SymbolSnapshot] = None,
    state: Any = None,
    day_mode: str = "",
    snapshots: Any = None,
    readiness_reason: str = "",
    settings: Any = None,
) -> dict[str, Any]:
    """Four-step checklist for one candidate (live radar / building board row)."""
    settings = settings or get_settings()
    lane = resolve_sep917_lane(
        side,
        evidence,
        ranking,
        state=state,
        snap=snap,
        symbol=symbol,
        readiness_reason=readiness_reason,
        settings=settings,
    )
    if lane not in _LANES:
        lane = "NONE"

    i_ok, i_det = _index_structure_ok(
        side,
        snap=snap,
        symbol=symbol,
        evidence=evidence,
        state=state,
        settings=settings,
        lane=lane,
    )
    o_ok, o_det = _option_shape_ok(
        side,
        evidence,
        ranking,
        settings=settings,
        lane=lane,
        readiness_reason=readiness_reason,
    )
    s_ok, s_det = _session_context_ok(
        side,
        day_mode=day_mode,
        state=state,
        settings=settings,
        lane=lane,
    )
    f_ok, f_det = _funnel_authorize_ok(
        evidence,
        ranking,
        side=side,
        day_mode=day_mode,
        state=state,
        snapshots=snapshots,
        readiness_reason=readiness_reason,
        settings=settings,
        lane=lane,
    )

    steps = {
        "indexStructure": _step(i_ok, i_det),
        "optionShape": _step(o_ok, o_det),
        "sessionContext": _step(s_ok, s_det),
        "funnelAuthorize": _step(f_ok, f_det),
    }
    ready = all(steps[k]["ok"] for k in steps)

    return {
        "version": CHECKLIST_VERSION,
        "symbol": str(symbol or "").upper(),
        "side": str(side or "").upper(),
        "lane": lane,
        "ready": ready,
        "steps": steps,
    }


def _evidence_from_building_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "tier": row.get("tier") or "BUILDING",
        "explosionScore": row.get("explosion_score") or row.get("score"),
        "localBaseMovePct": row.get("local_move_pct"),
        "offLowMovePct": row.get("off_low_move_pct"),
        "buildingRipReady": bool(row.get("buildingRipReady")),
        "buildingRipHelpersOk": bool(row.get("helping") or (row.get("helper_count") or 0) > 0),
        "volumeAwaken": bool(row.get("volume_awaken")),
        "velocity3s": row.get("velocity_3s"),
    }


def _ranking_from_building_row(row: Mapping[str, Any]) -> dict[str, Any]:
    score = float(row.get("score") or row.get("explosion_score") or 0)
    grade = "A" if score >= 90 else "B" if score >= 75 else "C"
    return {"grade": grade, "score": score, "rankScore": score}


def sep917_live_checklist_entry_blocked(
    state: AutoTraderState | None,
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
    *,
    snapshots: Any = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Hard gate: explosion entries must pass the Sep 9–17 four-step checklist."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {"sep917Enforcement": True}
    if not bool(getattr(settings, "sep917_live_checklist_enforcement_enabled", True)):
        meta["sep917Enforcement"] = False
        return False, "", meta

    symbol = str(getattr(candidate, "symbol", "") or "").upper()
    side = getattr(candidate, "side", None)
    side_u = side.value if hasattr(side, "value") else str(side or "").upper()
    if snap is None and snapshots:
        snap = snapshots.get(symbol)
    if snap is None or not bool(getattr(snap, "dataAvailable", False)):
        meta["sep917Skipped"] = "no_index_snapshot"
        return False, "", meta
    alert = getattr(candidate, "alert", None) if isinstance(getattr(candidate, "alert", None), dict) else {}
    evidence: dict[str, Any] = dict(alert)
    for key in (
        "localBaseMovePct",
        "ictBaseRelativeMovePct",
        "flatThenVertical",
        "firstLift",
        "vRipReady",
        "spikeRunPct",
        "premium",
        "tier",
        "explosionScore",
    ):
        val = getattr(candidate, key, None)
        if val is not None and key not in evidence:
            evidence[key] = val

    from app.engines.trade_ranking import rank_entry_candidate, resolve_policy_day_mode

    ranking = rank_entry_candidate(candidate) or {}
    day_mode = resolve_policy_day_mode(state)
    readiness = str(getattr(candidate, "readinessReason", "") or evidence.get("readinessReason") or "")

    checklist = evaluate_sep917_live_checklist(
        symbol,
        side_u,
        evidence,
        ranking,
        snap=snap,
        state=state,
        day_mode=day_mode,
        snapshots=snapshots,
        readiness_reason=readiness,
        settings=settings,
    )
    meta["sep917Checklist"] = checklist
    lane = str(checklist.get("lane") or "NONE")
    moment = str(evidence.get("momentType") or "").lower()
    if lane == "CHASE_BLOCK":
        return True, f"sep917_lane_{lane}", meta
    if not bool(checklist.get("ready")):
        if evidence.get("ictEliteBaseReady") or moment in (
            "elite_base_ready",
            "armed_base_launch",
            "v_rip_session_low",
            "first_lift_local_base",
        ):
            meta["sep917Waive"] = moment or "elite_base_ready"
            return False, "", meta
        failed = [
            name
            for name, step in (checklist.get("steps") or {}).items()
            if isinstance(step, dict) and not step.get("ok")
        ]
        detail = ",".join(failed) if failed else "not_ready"
        return True, f"sep917_checklist_not_ready:{detail}", meta
    return False, "", meta


def attach_sep917_checklist_to_chop_guards(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    day_mode: str = "",
) -> None:
    """Ensure chopGuards.sep917LiveChecklist is populated for HUD / status API."""
    cg = dict(getattr(state, "chopGuards", None) or {})
    if cg.get("sep917LiveChecklist"):
        return
    dm = str(
        day_mode
        or cg.get("dayMode")
        or (
            (state.dailyStrategy or {}).get("dayMode")
            if isinstance(state.dailyStrategy, dict)
            else getattr(state.dailyStrategy, "dayMode", "")
        )
        or ""
    )
    cg["sep917LiveChecklist"] = sep917_live_checklist_session_summary(
        state, snapshots, day_mode=dm,
    )
    state.chopGuards = cg


def sep917_live_checklist_session_summary(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    day_mode: str = "",
) -> dict[str, Any]:
    """Session HUD: unlock flags per index + optional best BUILDING row checklist."""
    settings = get_settings()
    from app.engines.chop_day_guards import chop_post_win_afternoon_fomo_risk
    from app.engines.directional_lock import directional_lock_summary

    dlock = directional_lock_summary(snapshots)
    per_sym: dict[str, Any] = {}
    for sym, meta in (dlock.get("symbols") or {}).items():
        per_sym[sym] = {
            "call": {
                "indexRallyUnlock": bool(meta.get("indexRallySideFlip")),
                "laneHint": "RALLY_UNLOCK" if meta.get("indexRallySideFlip") else None,
            },
            "put": {
                "indexSlideUnlock": bool(meta.get("indexSlideSideFlip")),
                "laneHint": "SLIDE_UNLOCK" if meta.get("indexSlideSideFlip") else None,
            },
            "lockedSide": meta.get("lockedSide"),
            "direction": meta.get("direction"),
        }

    fomo, fomo_reasons = chop_post_win_afternoon_fomo_risk(
        state, day_mode=day_mode, settings=settings,
    )

    top_candidate: Optional[dict[str, Any]] = None
    board = getattr(state, "buildingLtpMonitor", None) or {}
    best = board.get("best") if isinstance(board, dict) else None
    if isinstance(best, dict) and best.get("symbol"):
        sym = str(best.get("symbol") or "").upper()
        snap = snapshots.get(sym)
        evidence = _evidence_from_building_row(best)
        ranking = _ranking_from_building_row(best)
        rr = str(best.get("ready_reason") or "")
        top_candidate = evaluate_sep917_live_checklist(
            sym,
            str(best.get("side") or "CALL"),
            evidence,
            ranking,
            snap=snap,
            state=state,
            day_mode=day_mode,
            snapshots=snapshots,
            readiness_reason=rr,
            settings=settings,
        )
        top_candidate["strike"] = best.get("strike")
        top_candidate["source"] = "buildingLtpMonitor"

    return {
        "version": CHECKLIST_VERSION,
        "enabled": True,
        "symmetricBestTradeCapture": bool(
            getattr(settings, "symmetric_best_trade_capture_enabled", True)
        ),
        "callRallyUnlockEnabled": bool(getattr(settings, "call_rally_unlock_enabled", True)),
        "putSlideUnlockEnabled": bool(getattr(settings, "put_slide_unlock_enabled", True)),
        "buildingRipHelperEnabled": bool(
            getattr(settings, "building_rip_helper_top_moment_enabled", True)
        ),
        "sep09IntentEnforcement": bool(
            getattr(settings, "sep09_intent_enforcement_enabled", True)
        ),
        "stepsGuide": list(_STEP_GUIDE),
        "symbols": per_sym,
        "postWinChopFomo": fomo,
        "postWinChopFomoReasons": fomo_reasons,
        "topCandidate": top_candidate,
    }
