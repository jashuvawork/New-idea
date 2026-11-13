"""Session-low V-rip capture when index flip participation leads before MTF leg flips."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.engines.elite_score_engine import _v_rip_moment_evidence
from app.engines.explosion_detector import session_low_relative_move_pct
from app.engines.index_flip_participation import index_flip_participation_assessment
from app.models.schemas import Side, SymbolSnapshot


def _side_u(raw: Any) -> str:
    val = str(getattr(raw, "value", raw) or "").upper()
    if val in {"CALL", "CE", "C"}:
        return "CALL"
    if val in {"PUT", "PE", "P"}:
        return "PUT"
    return val


def _off_session_low_pct(evidence: Mapping[str, Any]) -> float:
    for key in (
        "sessionLowMovePct",
        "offLowMovePct",
        "offSessionLowMovePct",
        "troughOffLowMovePct",
    ):
        val = evidence.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    symbol = str(evidence.get("symbol") or "").upper()
    strike = float(evidence.get("strike") or 0)
    side = evidence.get("side")
    prem = float(evidence.get("premium") or evidence.get("lastPremium") or 0)
    if symbol and strike > 0 and prem > 0 and side is not None:
        return session_low_relative_move_pct(symbol, strike, side, prem)
    return 0.0


def _heat_ok(evidence: Mapping[str, Any], settings: Any) -> bool:
    v3 = float(evidence.get("velocity3s") or evidence.get("velocity_3s") or 0)
    v9 = float(evidence.get("velocity9s") or evidence.get("velocity_9s") or 0)
    min_v3 = float(
        getattr(settings, "index_flip_session_low_min_velocity_3s", 1.2) or 1.2
    )
    if v3 >= min_v3:
        return True
    min_v9 = float(
        getattr(settings, "index_flip_session_low_min_velocity_9s", 2.0) or 2.0
    )
    if v9 >= min_v9:
        return True
    vol = float(evidence.get("volumeSurge") or evidence.get("volume_surge") or 0)
    min_vol = float(
        getattr(settings, "index_flip_session_low_min_volume_surge", 1.8) or 1.8
    )
    return vol >= min_vol


def index_flip_session_low_capture_active(
    evidence: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
    side: str,
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> tuple[bool, dict[str, Any]]:
    """Early capture off session low when participation leads the flip (CE/PE symmetric)."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {"active": False, "reasons": []}
    if not bool(getattr(settings, "index_flip_session_low_capture_enabled", True)):
        meta["reasons"].append("disabled")
        return False, meta
    if snap is None or not getattr(snap, "dataAvailable", False):
        meta["reasons"].append("no_snap")
        return False, meta
    if not _v_rip_moment_evidence(evidence, readiness_reason=readiness_reason):
        meta["reasons"].append("not_v_rip_session_low")
        return False, meta
    tier = str(evidence.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        meta["reasons"].append("tier_low")
        return False, meta
    side_u = _side_u(side)
    if side_u not in ("CALL", "PUT"):
        return False, meta

    participation = index_flip_participation_assessment(snap, settings=settings)
    meta["participation"] = participation
    lead = _side_u(participation.get("leadingOptionSide"))
    conf = float(participation.get("confidence") or 0)
    min_conf = float(
        getattr(settings, "index_flip_session_low_min_participation_confidence", 0.5)
        or 0.5
    )
    if lead != side_u or conf < min_conf - 1e-6:
        meta["reasons"].append("participation_not_aligned")
        return False, meta

    off_low = _off_session_low_pct(evidence)
    meta["offSessionLowPct"] = round(off_low, 2)
    lo = float(getattr(settings, "index_flip_session_low_min_off_low_pct", 4.0) or 4.0)
    hi = float(getattr(settings, "index_flip_session_low_max_off_low_pct", 22.0) or 22.0)
    if off_low < lo - 1e-6 or off_low > hi + 1e-6:
        meta["reasons"].append("off_low_out_of_band")
        return False, meta

    if not _heat_ok(evidence, settings):
        meta["reasons"].append("insufficient_velocity_or_volume")
        return False, meta

    meta["active"] = True
    meta["reasons"].append("index_flip_session_low_capture")
    return True, meta


def index_flip_session_low_elite_floor(
    evidence: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
    side: str,
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> tuple[Optional[float], dict[str, Any]]:
    """Lower elite min_score when participation confirms session-low V rip."""
    active, meta = index_flip_session_low_capture_active(
        evidence,
        snap,
        side,
        settings=settings,
        readiness_reason=readiness_reason,
    )
    if not active:
        return None, meta
    floor = float(
        getattr(settings, "index_flip_session_low_elite_score_floor", 82.0) or 82.0
    )
    return floor, meta


def index_flip_opposing_side_rank_penalty(
    side: str,
    snap: Optional[SymbolSnapshot],
    *,
    settings: Any = None,
) -> float:
    """Penalize rank on side opposite to participation-led flip."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_flip_opposing_side_rank_penalty_enabled", True)):
        return 0.0
    if snap is None:
        return 0.0
    participation = index_flip_participation_assessment(snap, settings=settings)
    lead = _side_u(participation.get("leadingOptionSide"))
    conf = float(participation.get("confidence") or 0)
    imm = float(
        getattr(settings, "index_flip_participation_imminent_confidence", 0.65) or 0.65
    )
    side_u = _side_u(side)
    if lead not in ("CALL", "PUT") or side_u not in ("CALL", "PUT"):
        return 0.0
    if lead == side_u or conf < imm - 1e-6:
        return 0.0
    return float(
        getattr(settings, "index_flip_opposing_side_rank_penalty", 18.0) or 18.0
    )


def tier_explosion_score_floor(tier: str, *, settings: Any = None) -> float:
    """Minimum explosion score when tier is held sticky — avoids ELITE @ 48 display."""
    settings = settings or get_settings()
    tier_u = str(tier or "").upper()
    if tier_u == "ELITE":
        return float(
            getattr(settings, "explosion_tier_elite_score_floor", 58.0) or 58.0
        )
    if tier_u == "EXPLODING":
        return float(
            getattr(settings, "explosion_tier_exploding_score_floor", 50.0) or 50.0
        )
    if tier_u == "BUILDING":
        return float(
            getattr(settings, "explosion_tier_building_score_floor", 42.0) or 42.0
        )
    return 0.0
