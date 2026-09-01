"""Index-confirmed local-base capture — index trough/peak turn + option at pad.

Sep01: afternoon ELITE PUTs (23950/24000) and morning slow-V CALLs were detected but
gated by explosion_near_miss, timing blocks, chart lag, and premium fade while the
index had already turned at session peak/trough before option structure matured.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def alert_has_local_base_structure(alert: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(alert, dict):
        return False
    from app.engines.early_radar_pad_capture import watch_local_base_pad_structure
    from app.engines.local_base_chart_bypass import _alert_has_local_base

    row = dict(alert)
    if _alert_has_local_base(row) or watch_local_base_pad_structure(row):
        return True
    base_rel = float(
        alert.get("localBaseMovePct")
        or alert.get("ictBaseRelativeMovePct")
        or alert.get("offLowMovePct")
        or 0
    )
    if base_rel <= 0:
        return False
    settings = get_settings()
    max_off = float(
        getattr(settings, "index_confirmed_local_base_max_off_low_pct", 22.0) or 22.0
    )
    if float(alert.get("offLowMovePct") or 0) > max_off + 1e-6:
        return False
    return bool(
        alert.get("ictBaseArmed")
        or alert.get("baseArmed")
        or alert.get("ictArmedBaseLaunch")
        or alert.get("armedBaseLaunch")
        or alert.get("ictFlatThenVertical")
        or alert.get("ictFirstLift")
        or alert.get("ictVRipReady")
        or alert.get("slowGrindArmedTrough")
        or alert.get("ictSlowGrindArmedTrough")
    )


def _alert_index_confirmed_stamped(alert: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(alert, dict):
        return False
    return bool(
        alert.get("ictIndexConfirmedLocalBase")
        or alert.get("indexConfirmedLocalBase")
        or alert.get("ictIndexTroughSlowV")
        or alert.get("indexTroughSlowV")
        or alert.get("ictIndexPeakSlowV")
        or alert.get("indexPeakSlowV")
    )


def _armed_pad_breadth_aligned(
    side_u: str,
    alert: Mapping[str, Any],
    snap: SymbolSnapshot,
    *,
    settings: Any,
) -> bool:
    """Armed first-lift at pad with breadth agreeing — index turn may lag mom15."""
    if not bool(
        getattr(settings, "index_confirmed_local_base_armed_pad_bypass", True)
    ):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False
    if not (
        alert.get("ictArmedBaseLaunch")
        or alert.get("armedBaseLaunch")
        or alert.get("ictBaseArmed")
        or alert.get("baseArmed")
    ):
        return False
    if not (
        alert.get("ictFirstLift")
        or alert.get("firstLift")
        or alert.get("ictVRipReady")
        or alert.get("vRipReady")
    ):
        return False
    if not alert_has_local_base_structure(alert):
        return False
    breadth = (
        (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"
    ).upper()
    if side_u == "CALL" and breadth not in ("BULLISH", "NEUTRAL"):
        return False
    if side_u == "PUT" and breadth not in ("BEARISH", "NEUTRAL"):
        return False
    return True


def index_confirmed_local_base(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    alert: Optional[Mapping[str, Any]] = None,
    *,
    settings: Any = None,
) -> bool:
    s = settings or get_settings()
    if not bool(getattr(s, "index_confirmed_local_base_enabled", True)):
        return False
    if snap is None or snap.spotChart is None:
        return False
    side_u = side.value if isinstance(side, Side) else str(side).upper()
    if side_u not in ("CALL", "PUT"):
        return False
    if _alert_index_confirmed_stamped(alert):
        return True
    from app.engines.spot_direction import index_trough_momentum_turn

    if index_trough_momentum_turn(side_u, snap.spotChart, settings=s):
        return alert_has_local_base_structure(alert)
    if isinstance(alert, dict) and _armed_pad_breadth_aligned(
        side_u, alert, snap, settings=s,
    ):
        return True
    return False


def stamp_index_confirmed_local_base(
    alert: dict[str, Any],
    snap: SymbolSnapshot,
    *,
    side: Side | str | None = None,
) -> bool:
    side_val = side or alert.get("side") or ""
    if not index_confirmed_local_base(side_val, snap, alert):
        return False
    side_u = (
        side_val.value if isinstance(side_val, Side) else str(side_val).upper()
    )
    alert["indexConfirmedLocalBase"] = True
    alert["ictIndexConfirmedLocalBase"] = True
    if side_u == "CALL":
        alert["ictIndexTroughSlowV"] = True
        alert["indexTroughSlowV"] = True
    else:
        alert["ictIndexPeakSlowV"] = True
        alert["indexPeakSlowV"] = True
    return True


def index_confirmed_near_miss_waive(
    alert: Optional[Mapping[str, Any]],
    snap: Optional[SymbolSnapshot],
    *,
    readiness_reason: str = "",
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "index_confirmed_local_base_waives_near_miss", True)):
        return False
    if not isinstance(alert, dict) or snap is None:
        return False
    side = str(alert.get("side") or "").upper()
    if not index_confirmed_local_base(side, snap, alert):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING", "WATCH"):
        return False
    score = float(alert.get("explosionScore") or 0)
    floor = float(
        getattr(settings, "index_confirmed_local_base_min_explosion_score_floor", 5.0)
        or 5.0
    )
    return score >= floor


def index_confirmed_premium_fade_bypass(
    alert: Optional[Mapping[str, Any]],
    snap: Optional[SymbolSnapshot],
    explosion_event: Any = None,
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "index_confirmed_local_base_premium_fade", True)):
        return False
    if not isinstance(alert, dict) or snap is None:
        return False
    side = str(alert.get("side") or "").upper()
    if not index_confirmed_local_base(side, snap, alert):
        return False
    tier = str(
        alert.get("tier") or getattr(explosion_event, "tier", "") or ""
    ).upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False
    min_lb = float(getattr(settings, "shallow_otm_local_base_min_move_pct", 2.0) or 2.0)
    max_lb = float(getattr(settings, "shallow_otm_local_base_max_move_pct", 25.0) or 25.0)
    lb = float(
        alert.get("localBaseMovePct")
        or alert.get("ictBaseRelativeMovePct")
        or alert.get("offLowMovePct")
        or 0
    )
    return min_lb <= lb <= max_lb


def enrich_evidence_index_confirmed(
    evidence: dict[str, Any],
    snap: Optional[SymbolSnapshot],
    alert: Optional[Mapping[str, Any]],
    side: Side | str,
) -> None:
    active = index_confirmed_local_base(side, snap, alert)
    evidence["indexConfirmedLocalBase"] = active
    if active:
        evidence["indexHelpersConfirm"] = True


def index_confirmed_waives_timing_block(evidence: Mapping[str, Any]) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "index_confirmed_local_base_waives_timing", True)):
        return False
    if not evidence.get("indexConfirmedLocalBase"):
        return False
    tier = str(evidence.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False
    local_move = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("offLowMovePct") or 0),
    )
    return 2.0 <= local_move <= float(
        getattr(settings, "index_confirmed_local_base_max_off_low_pct", 22.0) or 22.0
    )
