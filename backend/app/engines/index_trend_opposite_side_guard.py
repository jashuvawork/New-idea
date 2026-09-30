"""Block opposite option side when index rally/slide is armed — re-checked every entry."""

from __future__ import annotations

from typing import Any, Mapping

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _guard_active(settings: Any = None) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_trend_opposite_side_block_enabled", True)):
        return False
    if not bool(getattr(settings, "index_trend_opposite_side_legacy_profile_only", True)):
        return True
    from app.engines.sep917_legacy_profile import sep917_legacy_profile_active

    return sep917_legacy_profile_active(settings) and bool(
        getattr(settings, "symmetric_best_trade_capture_enabled", True)
    )


def _allowed_symbols(sym: str, settings: Any) -> bool:
    raw = str(
        getattr(
            settings,
            "index_trend_opposite_side_symbols_csv",
            getattr(settings, "worst_day_put_block_rally_symbols_csv", "SENSEX,NIFTY"),
        )
        or "SENSEX,NIFTY"
    )
    allowed = {s.strip().upper() for s in raw.split(",") if s.strip()}
    return sym.upper() in allowed


def _resolve_trend_arms(
    sym: str,
    snap: SymbolSnapshot,
    state: Any,
    *,
    settings: Any = None,
) -> tuple[bool, bool, dict[str, Any]]:
    """Apply flip tie-break when both rally and slide soft-unlock are armed."""
    from app.engines.index_rally_side_flip import index_rally_metrics
    from app.engines.pe_win_ce_mirror import call_rally_unlock_armed
    from app.engines.put_slide_ce_mirror import put_slide_unlock_armed

    settings = settings or get_settings()
    meta: dict[str, Any] = {}

    call_armed, call_reason, call_meta = call_rally_unlock_armed(
        state, snap, sym, settings=settings,
    )
    put_armed, put_reason, put_meta = put_slide_unlock_armed(
        state, snap, sym, settings=settings,
    )
    meta["callRallyUnlock"] = {"armed": call_armed, "reason": call_reason, **call_meta}
    meta["putSlideUnlock"] = {"armed": put_armed, "reason": put_reason, **put_meta}

    if not (call_armed and put_armed):
        return call_armed, put_armed, meta

    metrics = index_rally_metrics(sym, snap, settings=settings)
    rally_pts = float(metrics.get("rallyPoints") or 0)
    slide_pts = float(metrics.get("slidePoints") or 0)
    margin = float(
        getattr(settings, "index_trend_opposite_side_flip_margin_pts", 20.0) or 20.0
    )
    meta["indexTrendMetrics"] = metrics

    chart = snap.spotChart
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0) if chart else 0.0

    if rally_pts > slide_pts + margin:
        meta["indexTrendFlip"] = "rally_dominant"
        return True, False, meta
    if slide_pts > rally_pts + margin:
        meta["indexTrendFlip"] = "slide_dominant"
        return False, True, meta
    if mom5 > 0.02:
        meta["indexTrendFlip"] = "mom5_rally"
        return True, False, meta
    if mom5 < -0.02:
        meta["indexTrendFlip"] = "mom5_slide"
        return False, True, meta
    meta["indexTrendFlip"] = "both_neutral"
    return False, False, meta


def _candidate_evidence(candidate: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    alert = getattr(candidate, "alert", None)
    if not isinstance(alert, dict):
        alert = {}
    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}
    if not isinstance(ranking, dict):
        ranking = {}
    readiness = str(
        pretrade.get("readinessReason") or pretrade.get("liftReason") or ""
    )
    return {**alert, **ranking}, ranking, readiness


def _put_rally_bypass(
    candidate: Any,
    state: Any,
    snap: SymbolSnapshot,
    sym: str,
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    readiness: str,
    *,
    settings: Any = None,
) -> bool:
    from app.engines.best_trade_policy import put_at_base_best_trade_fingerprint
    from app.engines.put_slide_ce_mirror import put_slide_entry_unlock_fingerprint

    settings = settings or get_settings()
    if put_slide_entry_unlock_fingerprint(
        evidence,
        ranking,
        state=state,
        snap=snap,
        symbol=sym,
        readiness_reason=readiness,
        settings=settings,
    ):
        return True
    if put_at_base_best_trade_fingerprint(
        evidence,
        ranking,
        state=state,
        snap=snap,
        symbol=sym,
        readiness_reason=readiness,
        settings=settings,
    ):
        return True
    off_high = float(evidence.get("offHighMovePct") or 0)
    local = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("ictBaseRelativeMovePct") or 0),
    )
    max_local = float(getattr(settings, "best_trade_near_base_max_local_pct", 20.0) or 20.0)
    return off_high > 0 and local <= max_local


def _call_slide_bypass(
    candidate: Any,
    state: Any,
    snap: SymbolSnapshot,
    sym: str,
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    readiness: str,
    *,
    settings: Any = None,
) -> bool:
    from app.engines.best_trade_policy import call_at_base_best_trade_fingerprint
    from app.engines.elite_score_engine import build_elite_assessment
    from app.engines.pe_win_ce_mirror import (
        call_rally_entry_unlock_fingerprint,
        legacy_chop_rally_call_capture_armed,
    )

    settings = settings or get_settings()
    assessment = build_elite_assessment(dict(evidence), dict(ranking))
    if call_at_base_best_trade_fingerprint(
        evidence,
        ranking,
        assessment,
        state=state,
        snap=snap,
        symbol=sym,
        readiness_reason=readiness,
        settings=settings,
    ):
        return True
    if call_rally_entry_unlock_fingerprint(
        evidence,
        ranking,
        assessment,
        state=state,
        snap=snap,
        symbol=sym,
        readiness_reason=readiness,
        settings=settings,
    ):
        return True
    if legacy_chop_rally_call_capture_armed(
        evidence,
        ranking,
        assessment,
        state=state,
        snap=snap,
        symbol=sym,
        readiness_reason=readiness,
        settings=settings,
    ):
        return True
    off_low = float(evidence.get("offLowMovePct") or 0)
    local = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("ictBaseRelativeMovePct") or 0),
    )
    max_local = float(getattr(settings, "best_trade_near_base_max_local_pct", 20.0) or 20.0)
    return off_low > 0 and local <= max_local


def index_trend_opposite_side_blocks_entry(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """
    CALL rally off session low → block blind PUT (unless put slide / at-base).
    PUT slide off session high → block blind CALL (unless call rally / at-base).
    Re-evaluated on every candidate; flip tie-break when both unlocks are armed.
    """
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not _guard_active(settings):
        return False, "ok", meta

    side = _side_val(getattr(candidate, "side", None))
    if side not in ("CALL", "PUT"):
        return False, "ok", meta

    sym = str(getattr(candidate, "symbol", "") or "").upper()
    if not _allowed_symbols(sym, settings):
        return False, "ok", meta

    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None:
        return False, "ok", meta

    from app.engines.index_tick_helpers import index_trend_breakout

    if side == "PUT":
        slide_bo = index_trend_breakout(sym, "PUT", snap)
        if slide_bo.get("breakout"):
            return False, "ok", meta

    if side == "CALL":
        rally_bo = index_trend_breakout(sym, "CALL", snap)
        if rally_bo.get("breakout"):
            return False, "ok", meta

    call_armed, put_armed, arm_meta = _resolve_trend_arms(sym, snap, state, settings=settings)
    meta.update(arm_meta)

    from app.engines.worst_day_guard import _put_rally_bullish_context

    bullish_ctx, bull_meta = _put_rally_bullish_context(sym, snap)
    if bullish_ctx:
        meta["putRallyBullishContext"] = bull_meta

    evidence, ranking, readiness = _candidate_evidence(candidate)

    if side == "PUT" and (call_armed or bullish_ctx):
        if _put_rally_bypass(
            candidate, state, snap, sym, evidence, ranking, readiness, settings=settings,
        ):
            return False, "ok", meta
        return True, "index_trend_put_blocked_call_rally", meta

    if side == "CALL" and put_armed:
        if _call_slide_bypass(
            candidate, state, snap, sym, evidence, ranking, readiness, settings=settings,
        ):
            return False, "ok", meta
        return True, "index_trend_call_blocked_put_slide", meta

    return False, "ok", meta
