"""Open-session rip: keep ELITE/EXPLODING visible to selector (Oct 8–9 zero-trade RCA)."""

from __future__ import annotations

from typing import Any, Mapping

from app.models.schemas import AutoTraderState, SymbolSnapshot

_OPEN_RIP_MOMENTS = frozenset(
    {
        "armed_base_launch",
        "ELITE_BASE_READY",
        "v_rip_session_low",
        "v_rip_session_high",
        "building_rip_bullish",
        "ict_base_armed",
        "first_lift_local_base",
        "flat_then_vertical",
        "volume_awaken",
    }
)


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def open_rip_elite_structural_evidence(alert: Mapping[str, Any]) -> bool:
    """True when alert carries open first-lift / v-rip / armed-base evidence."""
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    moment = str(alert.get("momentType") or "")
    if moment in _OPEN_RIP_MOMENTS:
        return True
    if any(
        bool(alert.get(k))
        for k in (
            "vRipReady",
            "ictVRipReady",
            "armedBaseLaunch",
            "ictArmedBaseLaunch",
            "firstLift",
            "ictFirstLift",
            "ictEliteBaseReady",
            "ictBuildingRipReady",
            "buildingRipHelpersOk",
            "bullishLocalBaseActive",
            "localBaseReversalActive",
        )
    ):
        return True
    pad = max(
        _num(alert.get("localBaseMovePct")),
        _num(alert.get("ictBaseRelativeMovePct")),
        _num(alert.get("offLowMovePct")),
    )
    return pad >= 12.0


def open_rip_elite_tradeable_preserve(
    alert: Mapping[str, Any],
    *,
    settings: Any = None,
) -> bool:
    """
    Sep917 clears OTM tradeable at stamp time — preserve open rip ELITE for selector feed.

    Execution may still reject OTM under strict ATM/ITM; ITM siblings should also appear
    in explosionAlerts when scan is healthy (cap force-include handles competition).
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not open_rip_elite_structural_evidence(alert):
        return False
    score = _num(alert.get("explosionScore") or alert.get("score"))
    min_score = float(
        getattr(s, "explosion_alerts_force_include_min_score", 90.0) or 90.0
    )
    if score < min_score - 1e-6:
        return False
    try:
        from app.engines.session_timing import in_open_premium_window

        if not in_open_premium_window():
            return False
    except Exception:
        return False
    return True


def open_rip_selector_lift_waiver(
    alert: Mapping[str, Any],
    snap: SymbolSnapshot | None,
    state: AutoTraderState | None,
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> bool:
    """Treat as lift_ready in selector when tradeable was cleared but open rip ELITE is hot."""
    from app.config import get_settings
    from app.engines.live_paper_parity import (
        oct_paper_first_lift_small_lift_context,
        trading_rules_match_paper,
    )

    s = settings or get_settings()
    if not isinstance(alert, dict):
        return False
    if open_rip_elite_tradeable_preserve(alert, settings=s):
        return True
    if trading_rules_match_paper(s) and oct_paper_first_lift_small_lift_context(
        alert,
        settings=s,
        readiness_reason=readiness_reason,
    ):
        return True
    return False
