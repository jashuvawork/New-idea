"""Block opposite option side when index rally/slide is armed — re-checked every entry."""

from __future__ import annotations

from typing import Any, Mapping

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _guard_active(settings: Any = None) -> bool:
    from app.engines.index_session_dominant_trend import index_trend_features_active

    settings = settings or get_settings()
    if not bool(getattr(settings, "index_trend_opposite_side_block_enabled", True)):
        return False
    return index_trend_features_active(settings)


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
    nested = ranking.get("evidence") if isinstance(ranking.get("evidence"), dict) else {}
    merged = {**alert, **nested, **ranking}
    tier = getattr(candidate, "tier", None)
    if tier and not merged.get("tier"):
        merged["tier"] = tier
    side = getattr(candidate, "side", None)
    if side is not None and not merged.get("side"):
        merged["side"] = _side_val(side)
    sym = getattr(candidate, "symbol", None)
    if sym and not merged.get("symbol"):
        merged["symbol"] = sym
    return merged, ranking, readiness


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
    if bool(getattr(settings, "best_trade_sep917_base_shape_align_enabled", True)):
        from app.engines.best_trade_policy import sep917_near_base_capture_ok

        ok, _ = sep917_near_base_capture_ok(
            evidence, ranking, evidence, settings=settings,
        )
        return ok
    from app.engines.best_trade_policy import effective_near_base_max_local_pct

    off_high = float(evidence.get("offHighMovePct") or 0)
    local = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("ictBaseRelativeMovePct") or 0),
    )
    max_local = effective_near_base_max_local_pct(settings)
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
    if bool(getattr(settings, "best_trade_sep917_base_shape_align_enabled", True)):
        from app.engines.best_trade_policy import sep917_near_base_capture_ok

        ok, _ = sep917_near_base_capture_ok(
            evidence, ranking, evidence, settings=settings,
        )
        return ok
    from app.engines.best_trade_policy import effective_near_base_max_local_pct

    off_low = float(evidence.get("offLowMovePct") or 0)
    local = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("ictBaseRelativeMovePct") or 0),
    )
    max_local = effective_near_base_max_local_pct(settings)
    return off_low > 0 and local <= max_local


def index_trend_opposite_side_blocks_entry(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """
    CALL rally leg → block blind PUT. PUT slide leg → block blind CALL.
    Uses index_session_dominant_trend() each candidate.
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

    from app.engines.index_session_dominant_trend import index_session_dominant_trend
    from app.engines.index_tick_helpers import index_trend_breakout

    if side == "PUT":
        slide_bo = index_trend_breakout(sym, "PUT", snap)
        if slide_bo.get("breakout"):
            return False, "ok", meta

    if side == "CALL":
        rally_bo = index_trend_breakout(sym, "CALL", snap)
        if rally_bo.get("breakout"):
            return False, "ok", meta

    dominant, trend_meta = index_session_dominant_trend(sym, snap, state, settings=settings)
    meta.update(trend_meta)

    from app.engines.worst_day_guard import _put_rally_bullish_context

    bullish_ctx, bull_meta = _put_rally_bullish_context(sym, snap)
    if bullish_ctx:
        meta["putRallyBullishContext"] = bull_meta

    evidence, ranking, readiness = _candidate_evidence(candidate)

    block_put = side == "PUT" and (
        dominant == "RALLY" or (dominant == "NEUTRAL" and bullish_ctx)
    )
    if block_put:
        if _put_rally_bypass(
            candidate, state, snap, sym, evidence, ranking, readiness, settings=settings,
        ):
            return False, "ok", meta
        return True, "index_trend_put_blocked_call_rally", meta

    if side == "CALL" and dominant == "SLIDE":
        if _call_slide_bypass(
            candidate, state, snap, sym, evidence, ranking, readiness, settings=settings,
        ):
            return False, "ok", meta
        return True, "index_trend_call_blocked_put_slide", meta

    return False, "ok", meta
