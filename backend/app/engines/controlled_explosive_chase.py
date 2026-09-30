"""Tier A/B/C read model — base, controlled rip chase, late chase (CE + PE)."""

from __future__ import annotations

from typing import Any, Literal, Mapping, Optional

from app.config import get_settings
from app.models.schemas import SymbolSnapshot

ChaseTier = Literal["A", "B", "C", ""]


def _alert_dict(candidate: Any) -> dict[str, Any]:
    alert = getattr(candidate, "alert", None)
    return alert if isinstance(alert, dict) else {}


def _merged_evidence(candidate: Any) -> dict[str, Any]:
    alert = _alert_dict(candidate)
    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}
    if not isinstance(ranking, dict):
        ranking = {}
    evidence = ranking.get("evidence") if isinstance(ranking.get("evidence"), dict) else {}
    return {**alert, **evidence, **ranking}


def _local_move_pct(evidence: Mapping[str, Any]) -> float:
    from app.engines.best_trade_policy import _evidence_local_move_pct

    return _evidence_local_move_pct(evidence)


def controlled_chase_policy_active(settings: Any = None) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "best_trade_controlled_chase_enabled", True)):
        return False
    from app.engines.sep917_legacy_profile import legacy_best_trade_base_first_active

    return legacy_best_trade_base_first_active(settings)


def _controlled_chase_ceiling(
    candidate: Any,
    snap: Optional[SymbolSnapshot],
    *,
    settings: Any,
) -> float:
    alert = _alert_dict(candidate)
    tier = str(getattr(candidate, "tier", "") or alert.get("tier") or "")
    vol = float(alert.get("volumeSurge") or alert.get("volume_surge") or 0)
    sym = str(getattr(candidate, "symbol", "") or alert.get("symbol") or "")
    from app.engines.local_base_chart_bypass import local_base_entry_window

    _entry_min, chase_max = local_base_entry_window(
        tier, vol, snap=snap, symbol=sym,
    )
    cap = float(
        getattr(settings, "best_trade_controlled_chase_max_local_pct", 32.0) or 32.0
    )
    return min(chase_max, cap)


def _top_explosive_rip_evidence(
    evidence: Mapping[str, Any],
    assessment: Mapping[str, Any] | None,
    *,
    candidate: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    settings: Any,
) -> tuple[bool, str]:
    assessment = assessment if isinstance(assessment, Mapping) else {}
    if evidence.get("fastVerticalBurst") or evidence.get("buildingRipReady"):
        return True, "building_rip_ready"
    if evidence.get("ictBuildingRip") or evidence.get("ictFlatThenVertical"):
        return True, "ict_building_or_ftv"
    if evidence.get("buildingRip") or evidence.get("expiryFastVerticalBurst"):
        return True, "vertical_burst"

    from app.engines.elite_score_engine import elite_mega_vertical_bypass

    mega_ok, mega_reason = elite_mega_vertical_bypass(
        evidence, assessment, settings=settings,
    )
    if mega_ok:
        return True, mega_reason or "elite_mega_vertical"

    if snap is not None and candidate is not None:
        sym = str(getattr(candidate, "symbol", "") or evidence.get("symbol") or "").upper()
        side = str(
            getattr(getattr(candidate, "side", None), "value", None)
            or getattr(candidate, "side", "")
            or evidence.get("side")
            or ""
        ).upper()
        if sym and side in ("CALL", "PUT"):
            from app.engines.index_session_dominant_trend import (
                index_session_dominant_trend,
                side_aligns_with_dominant_trend,
            )

            dominant, _ = index_session_dominant_trend(
                sym, snap, getattr(candidate, "state", None), settings=settings, track_flip=False,
            )
            if side_aligns_with_dominant_trend(side, dominant):
                return True, f"index_dominant_{dominant.lower()}"

    tier_u = str(evidence.get("tier") or getattr(candidate, "tier", "") or "").upper()
    score = float(assessment.get("eliteScore") or evidence.get("explosionScore") or 0)
    min_score = float(
        getattr(settings, "best_trade_controlled_chase_min_elite_score", 90.0) or 90.0
    )
    if tier_u in ("ELITE", "EXPLODING") and score >= min_score:
        v3 = float(evidence.get("velocity3s") or evidence.get("liveVelocity3s") or 0)
        if v3 > 0:
            return True, "elite_hot_velocity"
    return False, ""


def classify_best_trade_chase_tier(
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
    *,
    assessment: Mapping[str, Any] | None = None,
    settings: Any = None,
) -> tuple[ChaseTier, dict[str, Any]]:
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not controlled_chase_policy_active(settings):
        return "", meta

    alert = _alert_dict(candidate)
    merged = _merged_evidence(candidate)
    local = _local_move_pct(merged)
    meta["localMovePct"] = round(local, 2)

    from app.engines.best_trade_policy import effective_near_base_max_local_pct

    base_floor = effective_near_base_max_local_pct(settings)
    ceiling = _controlled_chase_ceiling(candidate, snap, settings=settings)
    meta["controlledChaseCeilingPct"] = round(ceiling, 2)

    from app.engines.best_trade_policy import symmetric_best_trade_at_base_capture

    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}
    if not isinstance(ranking, dict):
        ranking = assessment if isinstance(assessment, Mapping) else {}
    at_base, base_reason = symmetric_best_trade_at_base_capture(
        merged, alert, ranking=ranking, settings=settings,
    )
    if at_base and local <= base_floor + 1e-6:
        meta["tierReason"] = base_reason
        return "A", meta

    if local > ceiling + 1e-6:
        meta["tierReason"] = "local_beyond_controlled_chase"
        return "C", meta

    if local > base_floor + 1e-6:
        rip_ok, rip_reason = _top_explosive_rip_evidence(
            merged, assessment, candidate=candidate, snap=snap, settings=settings,
        )
        meta["ripReason"] = rip_reason
        if rip_ok:
            meta["tierReason"] = "controlled_rip_chase"
            return "B", meta
        meta["tierReason"] = "off_base_no_rip_quality"
        return "C", meta

    if at_base:
        meta["tierReason"] = base_reason
        return "A", meta

    meta["tierReason"] = "below_base_floor_no_signal"
    return "C", meta


def controlled_explosive_chase_allowed(
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
    *,
    assessment: Mapping[str, Any] | None = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Tier B — top explosive slightly off base (symmetric CE/PE)."""
    settings = settings or get_settings()
    tier, meta = classify_best_trade_chase_tier(
        candidate, snap, assessment=assessment, settings=settings,
    )
    meta["controlledChaseTier"] = tier
    if tier == "B":
        return True, "controlled_explosive_chase", meta
    return False, meta.get("tierReason") or "not_controlled_chase", meta
