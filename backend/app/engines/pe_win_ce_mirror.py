"""PE-win CE mirror — unlock CALL rally leg after a confirmed session PUT win.

When PE capture succeeds (v-rip / trail-proved win), the index rally off session low
is the symmetric CE leg. Uses the same near-base bar as PE-parity, with relaxed
building-rip grace and execution fade bypass (Sep 9–17 missed CE pattern).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from app.config import get_settings
from app.engines.best_trade_policy import (
    VALID_BEST_BASE_SETUPS,
    _GOOD_TIMING,
    _number,
)
from app.engines.rally_capture import _grade_meets_min
from app.models.schemas import Side, SymbolSnapshot

_TRAIL_EXIT_TOKENS = ("trail", "runner", "target", "peak_keep", "peak_velocity", "tp")
_BUILDING_RIP_REASONS = (
    "building_rip_bullish",
    "building_rip_bullish_ready",
)


def _collect_session_trades(state: Any = None) -> list[Any]:
    if state is not None:
        try:
            from app.engines.pretrade_validator import collect_session_trades

            return list(collect_session_trades(state) or [])
        except Exception:
            pass
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app.services import trade_store

        today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
        detail = trade_store.get_day_detail(today) or {}
        return list(detail.get("trades") or [])
    except Exception:
        return []


def _side_val(side: Any) -> str:
    if isinstance(side, Side):
        return side.value
    return str(side or "").upper()


def session_put_win_meta(
    state: Any = None,
    *,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """True when the session has a trail-proved PUT win (PE capture succeeded)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "pe_win_ce_mirror_enabled", True)):
        return False, {}

    min_pnl = float(
        getattr(settings, "pe_win_ce_mirror_min_put_win_inr", 1000.0) or 1000.0
    )
    trades = _collect_session_trades(state)
    put_wins: list[Any] = []
    for trade in trades:
        if str(getattr(trade, "status", trade.get("status") if isinstance(trade, dict) else "") or "").upper() != "CLOSED":
            continue
        side = _side_val(getattr(trade, "side", None) or (trade.get("side") if isinstance(trade, dict) else ""))
        if side != "PUT":
            continue
        pnl = float(getattr(trade, "pnl_inr", None) or (trade.get("pnlInr") if isinstance(trade, dict) else 0) or 0)
        if pnl < min_pnl - 1e-6:
            continue
        reason = str(
            getattr(trade, "exit_reason", None)
            or (trade.get("exitReason") if isinstance(trade, dict) else "")
            or ""
        ).lower()
        if not any(tok in reason for tok in _TRAIL_EXIT_TOKENS):
            continue
        put_wins.append(trade)

    if not put_wins:
        return False, {}

    def _pnl(t: Any) -> float:
        return float(getattr(t, "pnl_inr", None) or (t.get("pnlInr") if isinstance(t, dict) else 0) or 0)

    best = max(put_wins, key=_pnl)
    sym = str(
        getattr(best, "symbol", None) or (best.get("symbol") if isinstance(best, dict) else "") or ""
    ).upper()
    return True, {
        "putWinPnlInr": round(_pnl(best), 2),
        "putWinSymbol": sym,
        "putWinCount": len(put_wins),
    }


def _soft_index_rally_ok(
    symbol: str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """PE-win mirror: rally off session low at reduced pts bar when flip not full."""
    from app.engines.index_rally_side_flip import (
        index_rally_metrics,
        index_rally_side_flip_bypass,
    )

    settings = settings or get_settings()
    full_ok, full_reason, full_meta = index_rally_side_flip_bypass(
        symbol, Side.CALL, snap, settings=settings,
    )
    if full_ok:
        return True, full_reason, {**full_meta, "rallyMode": "full_flip"}

    fraction = float(
        getattr(settings, "pe_win_ce_mirror_rally_pts_fraction", 0.5) or 0.5
    )
    metrics = index_rally_metrics(symbol, snap, settings=settings)
    rally_pts = float(metrics.get("rallyPoints") or 0)
    min_pts = float(metrics.get("minMovePoints") or 0)
    soft_min = min_pts * max(0.1, min(1.0, fraction))
    if rally_pts >= soft_min - 1e-6:
        return True, "pe_win_ce_mirror_soft_rally", {
            **metrics,
            "rallyMode": "soft",
            "softMinPts": round(soft_min, 1),
        }
    return False, f"rally_{rally_pts:.0f}<{soft_min:.0f}pts", metrics


def pe_win_ce_mirror_armed(
    state: Any,
    snap: SymbolSnapshot,
    symbol: str,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Mirror leg armed: session PUT win + index rally off session low."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "pe_win_ce_mirror_enabled", True)):
        return False, "disabled", {}

    pe_win, pe_meta = session_put_win_meta(state, settings=settings)
    if not pe_win:
        return False, "no_put_win", pe_meta

    if bool(getattr(settings, "pe_win_ce_mirror_require_index_rally", True)):
        rally_ok, rally_reason, rally_meta = _soft_index_rally_ok(
            symbol, snap, settings=settings,
        )
        if not rally_ok:
            return False, rally_reason, {**pe_meta, **rally_meta}
        return True, "pe_win_ce_mirror", {**pe_meta, **rally_meta, "mirrorReason": rally_reason}

    return True, "pe_win_ce_mirror", pe_meta


def _building_rip_launch_ok(
    evidence: Mapping[str, Any],
    *,
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    settings = settings or get_settings()
    grace = int(getattr(settings, "pe_win_ce_mirror_building_rip_grace_seconds", 300) or 300)
    rr = str(readiness_reason or evidence.get("readinessReason") or "").lower()
    if any(tok in rr for tok in _BUILDING_RIP_REASONS):
        return True
    for key in ("buildingRip", "buildingRipBullish", "building_rip_bullish"):
        if evidence.get(key):
            return True
    detected = evidence.get("firstSeenAt") or evidence.get("detectedAt")
    if detected and grace > 0:
        try:
            ts = datetime.fromisoformat(str(detected).replace("Z", "+00:00"))
            age = (datetime.now(ts.tzinfo) - ts).total_seconds()
            if age <= grace and evidence.get("tier") == "ELITE":
                return True
        except (TypeError, ValueError):
            pass
    return False


def _ce_rally_fingerprint_bar(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any] | None,
    elite_assessment: Mapping[str, Any] | None,
    *,
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    """Shared ELITE near-base bar for PE-win mirror and rally-only CE unlock."""
    settings = settings or get_settings()
    evidence = evidence if isinstance(evidence, Mapping) else {}
    ranking = ranking if isinstance(ranking, Mapping) else {}
    assessment = elite_assessment if isinstance(elite_assessment, Mapping) else {}

    tier = str(evidence.get("tier") or "").upper()
    if tier != "ELITE":
        return False

    setup = str(assessment.get("setup") or "").upper()
    if setup not in VALID_BEST_BASE_SETUPS:
        return False

    grade = str(ranking.get("grade") or assessment.get("grade") or "").upper()
    min_grade = str(
        getattr(settings, "pe_win_ce_mirror_min_grade", "A") or "A"
    ).upper()
    if not _grade_meets_min(grade, min_grade):
        return False

    score = _number(assessment.get("eliteScore"))
    min_score = float(
        getattr(settings, "pe_win_ce_mirror_min_elite_score", 85.0) or 85.0
    )
    if score < min_score - 1e-6:
        return False

    local = _number(assessment.get("localBasePct") or evidence.get("localBaseMovePct"))
    max_local = float(
        getattr(settings, "pe_win_ce_mirror_max_local_pct", 15.0) or 15.0
    )
    if local > max_local + 1e-6:
        return False

    launch_ok = bool(
        evidence.get("armedBaseLaunch")
        and (
            evidence.get("firstLift")
            or evidence.get("activeBreakout")
            or evidence.get("displacement")
        )
    ) or _building_rip_launch_ok(
        evidence, readiness_reason=readiness_reason, settings=settings,
    )
    if not launch_ok:
        return False

    v3 = _number(evidence.get("velocity3s") or evidence.get("liveVelocity3s"))
    min_v3 = float(
        getattr(settings, "pe_win_ce_mirror_min_velocity_3s", 1.0) or 1.0
    )
    if v3 < min_v3 - 1e-6:
        return False

    timing = str(evidence.get("timingAssessment") or assessment.get("timing") or "").upper()
    timing_action = str(evidence.get("timingAction") or "").lower()
    if timing_action in {"block", "reject"}:
        return False
    return timing in _GOOD_TIMING


def call_rally_unlock_armed(
    state: Any,
    snap: SymbolSnapshot,
    symbol: str,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Index rally off session low — CE unlock without requiring PUT win first."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "call_rally_unlock_enabled", True)):
        return False, "disabled", {}
    rally_ok, rally_reason, rally_meta = _soft_index_rally_ok(
        symbol, snap, settings=settings,
    )
    if not rally_ok:
        return False, rally_reason, rally_meta
    return True, "call_rally_unlock", rally_meta


def call_rally_unlock_fingerprint(
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
    """CALL entry bar when index rally unlock is armed (no PUT win required)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "call_rally_unlock_enabled", True)):
        return False
    if state is None or snap is None:
        return False

    sym = str(symbol or evidence.get("symbol") or "").upper()
    if not sym:
        sym = str(getattr(snap, "symbol", "") or "").upper()
    armed, _, _ = call_rally_unlock_armed(state, snap, sym, settings=settings)
    if not armed:
        return False
    return _ce_rally_fingerprint_bar(
        evidence,
        ranking,
        elite_assessment,
        readiness_reason=readiness_reason,
        settings=settings,
    )


def pe_win_ce_mirror_fingerprint(
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
    """CALL entry bar mirrored from a session PUT win — relaxed vs strict PE-parity."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "pe_win_ce_mirror_enabled", True)):
        return False
    if state is None or snap is None:
        return False

    sym = str(symbol or evidence.get("symbol") or "").upper()
    if not sym:
        sym = str(getattr(snap, "symbol", "") or "").upper()
    armed, _, _ = pe_win_ce_mirror_armed(state, snap, sym, settings=settings)
    if not armed:
        return False
    return _ce_rally_fingerprint_bar(
        evidence,
        ranking,
        elite_assessment,
        readiness_reason=readiness_reason,
        settings=settings,
    )


def call_rally_entry_unlock_armed(
    state: Any,
    snap: SymbolSnapshot,
    symbol: str,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """PE-win mirror OR index-rally-only CE unlock armed."""
    settings = settings or get_settings()
    mirror_ok, mirror_reason, mirror_meta = pe_win_ce_mirror_armed(
        state, snap, symbol, settings=settings,
    )
    if mirror_ok:
        return True, mirror_reason, mirror_meta
    rally_ok, rally_reason, rally_meta = call_rally_unlock_armed(
        state, snap, symbol, settings=settings,
    )
    if rally_ok:
        return True, rally_reason, rally_meta
    return False, rally_reason or mirror_reason, {**mirror_meta, **rally_meta}


def call_rally_entry_unlock_fingerprint(
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
    """True when mirror or rally-only CE unlock fingerprint matches."""
    if pe_win_ce_mirror_fingerprint(
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
    return call_rally_unlock_fingerprint(
        evidence,
        ranking,
        elite_assessment,
        state=state,
        snap=snap,
        symbol=symbol,
        readiness_reason=readiness_reason,
        settings=settings,
    )


def pe_win_ce_mirror_near_miss_waive(
    alert: Optional[dict[str, Any]],
    *,
    snap: Optional[SymbolSnapshot] = None,
    state: Any = None,
    ranking: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    """Waive explosion_near_miss for building-rip CE when rally unlock is armed."""
    settings = settings or get_settings()
    near_miss_enabled = (
        bool(getattr(settings, "pe_win_ce_mirror_near_miss_enabled", True))
        or bool(getattr(settings, "call_rally_unlock_near_miss_enabled", True))
    )
    if not near_miss_enabled:
        return False
    if not isinstance(alert, dict) or str(alert.get("side") or "").upper() != "CALL":
        return False
    if snap is None or state is None:
        return False
    sym = str(alert.get("symbol") or getattr(snap, "symbol", "") or "").upper()
    if not call_rally_entry_unlock_armed(state, snap, sym, settings=settings)[0]:
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False
    rr = str(readiness_reason or "").lower()
    if any(tok in rr for tok in _BUILDING_RIP_REASONS):
        return True
    if alert.get("armedBaseLaunch") or alert.get("firstLift"):
        return True
    return _building_rip_launch_ok(alert, readiness_reason=readiness_reason, settings=settings)


def pe_win_ce_mirror_premium_fade_bypass(
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
    """Allow shallow premium fade fill on rally-unlocked CE first lift."""
    settings = settings or get_settings()
    fade_waive = (
        bool(getattr(settings, "pe_win_ce_mirror_waive_premium_fade", True))
        or bool(getattr(settings, "call_rally_unlock_waive_mtf_premium_fade", True))
    )
    if not fade_waive:
        return False
    if _side_val(side) != "CALL" or snap is None or state is None:
        return False
    sym = str(symbol or (evidence or {}).get("symbol") or getattr(snap, "symbol", "") or "").upper()
    return call_rally_entry_unlock_fingerprint(
        evidence or {},
        ranking,
        assessment,
        state=state,
        snap=snap,
        symbol=sym,
        settings=settings,
    )


def call_rally_entry_unlock_expiry_otm_bypass(
    candidate: Any,
    snap: Any,
    alert: Mapping[str, Any] | None = None,
    *,
    state: Any = None,
    settings: Any = None,
) -> bool:
    """Waive expiry OTM block for rally-unlocked ELITE CE (Sep 17 SENSEX 74600 pattern)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "call_rally_unlock_waive_expiry_otm", True)):
        return False
    side = _side_val(getattr(candidate, "side", None))
    if side != "CALL" or state is None or snap is None:
        return False
    from app.engines.best_trade_policy import (
        call_pe_parity_from_candidate,
        mid_rip_best_trade_candidate,
    )
    from app.engines.elite_score_engine import build_elite_assessment
    from app.engines.trade_ranking import rank_entry_candidate

    if call_pe_parity_from_candidate(candidate, snap, settings=settings, state=state):
        return True
    alert_map = alert if isinstance(alert, Mapping) else {}
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
    if call_rally_entry_unlock_fingerprint(
        {**alert_map, **dict(ranking.get("evidence") or {})},
        ranking,
        assessment,
        state=state,
        snap=snap,
        symbol=symbol,
        settings=settings,
    ):
        return True
    if call_rally_entry_unlock_armed(state, snap, symbol, settings=settings)[0]:
        return mid_rip_best_trade_candidate(
            candidate, alert_map, assessment, settings=settings,
        )
    return False


def pe_win_ce_mirror_summary(
    state: Any,
    snapshots: dict[str, SymbolSnapshot],
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """HUD observability — PE-win CE mirror state per symbol."""
    settings = settings or get_settings()
    pe_win, pe_meta = session_put_win_meta(state, settings=settings)
    out: dict[str, Any] = {
        "enabled": bool(getattr(settings, "pe_win_ce_mirror_enabled", True)),
        "putWinActive": pe_win,
        **pe_meta,
        "symbols": {},
    }
    for sym, snap in (snapshots or {}).items():
        if not snap or not getattr(snap, "dataAvailable", True):
            continue
        armed, reason, meta = call_rally_entry_unlock_armed(
            state, snap, sym, settings=settings,
        )
        out["symbols"][sym] = {"armed": armed, "reason": reason, **meta}
    return out
