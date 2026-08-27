"""Grade-A flat→vertical first-lift capture on NIFTY/SENSEX.

Lifts expiry worst-day declining halts and lowers score/rank/chart floors for
confirmed EXPLODING FTV first-lifts with flatVerticalGrade A/A+ and index alignment
(Aug27 SENSEX 77300 PUT: detected winner, blocked by session halt + score 33 < 45).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import SymbolSnapshot


def grade_a_ftv_symbols(settings: Any | None = None) -> set[str]:
    s = settings or get_settings()
    raw = str(
        getattr(s, "grade_a_ftv_first_lift_symbols_csv", "NIFTY,SENSEX") or "NIFTY,SENSEX"
    )
    return {part.strip().upper() for part in raw.split(",") if part.strip()}


def _grade_ok(alert: Mapping[str, Any]) -> bool:
    return str(alert.get("flatVerticalGrade") or "").upper() in ("A+", "A")


def _session_move(alert: Mapping[str, Any]) -> float:
    return max(
        float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
        float(alert.get("peakMovePct") or 0),
    )


def grade_a_ftv_index_aligned(alert: Mapping[str, Any], snap: Optional[SymbolSnapshot]) -> bool:
    if bool(alert.get("indexMomAlign") or alert.get("indexHelpersConfirm")):
        return True
    if snap is None:
        return False
    side = str(alert.get("side") or "").upper()
    if side in ("CALL", "PUT") and snap.spotChart is not None:
        from app.engines.spot_direction import side_aligned_with_chart

        if side_aligned_with_chart(side, snap.spotChart):
            return True
    breadth = str(snap.breadth.bias if snap.breadth else "NEUTRAL").upper()
    if side == "CALL" and breadth == "BULLISH":
        return True
    if side == "PUT" and breadth == "BEARISH":
        return True
    return False


def alert_is_grade_a_ftv_first_lift(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "grade_a_ftv_first_lift_enabled", True)):
        return False
    if not bool(alert.get("tradeable", True)):
        return False
    sym = str(alert.get("symbol") or "").upper()
    if sym not in grade_a_ftv_symbols(settings):
        return False
    if str(alert.get("tier") or "").upper() != "EXPLODING":
        return False
    if not (bool(alert.get("ictFlatThenVertical")) and bool(alert.get("ictFirstLift"))):
        return False
    if not _grade_ok(alert):
        return False
    quality = float(alert.get("flatVerticalQuality") or 0)
    min_quality = float(
        getattr(settings, "grade_a_ftv_first_lift_min_quality", 65.0) or 65.0
    )
    if quality < min_quality:
        return False
    score = float(alert.get("explosionScore") or 0)
    min_score = float(
        getattr(settings, "grade_a_ftv_first_lift_min_explosion_score", 28.0) or 28.0
    )
    if score < min_score:
        return False
    if bool(alert.get("faded") or alert.get("exhaustedReentry")):
        return False
    if not grade_a_ftv_index_aligned(alert, snap):
        return False
    from app.engines.premium_filter import premium_in_band

    move = _session_move(alert)
    if not premium_in_band(alert.get("premium"), mode="explosion", peak_move_pct=move):
        return False
    if snap is not None:
        from app.engines.moneyness import atm_itm_entry_allows
        from app.models.schemas import Side

        side = str(alert.get("side") or "").upper()
        strike = float(alert.get("strike") or 0)
        if side in ("CALL", "PUT") and strike > 0:
            if not atm_itm_entry_allows(Side(side), strike, snap)[0]:
                return False
    return True


def grade_a_ftv_first_lift_floors(settings: Any | None = None) -> dict[str, float]:
    s = settings or get_settings()
    return {
        "minQuality": float(
            getattr(s, "grade_a_ftv_first_lift_min_quality", 65.0) or 65.0
        ),
        "minScore": float(
            getattr(s, "grade_a_ftv_first_lift_min_explosion_score", 28.0) or 28.0
        ),
        "minRank": float(getattr(s, "grade_a_ftv_first_lift_min_rank", 40.0) or 40.0),
        "minBaseMove": float(
            getattr(s, "grade_a_ftv_first_lift_min_base_move_pct", 8.0) or 8.0
        ),
        "maxBaseMove": float(
            getattr(s, "grade_a_ftv_first_lift_max_base_move_pct", 45.0) or 45.0
        ),
    }


def grade_a_ftv_expiry_worst_waive(evidence: Mapping[str, Any]) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "grade_a_ftv_first_lift_enabled", True)):
        return False
    sym = str(evidence.get("symbol") or "").upper()
    if sym and sym not in grade_a_ftv_symbols(settings):
        return False
    if str(evidence.get("tier") or "").upper() != "EXPLODING":
        return False
    if not (bool(evidence.get("flatThenVertical")) and bool(evidence.get("firstLift"))):
        return False
    grade = str(evidence.get("flatVerticalGrade") or "").upper()
    if grade not in ("A+", "A"):
        return False
    floors = grade_a_ftv_first_lift_floors(settings)
    if float(evidence.get("flatVerticalQuality") or 0) < floors["minQuality"]:
        return False
    score = float(evidence.get("explosionScore") or evidence.get("score") or 0)
    return score >= floors["minScore"]


def snapshots_have_grade_a_ftv_first_lift(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            if alert_is_grade_a_ftv_first_lift(alert, snap):
                return True
    return False


def _candidate_alert(candidate: Any) -> dict[str, Any]:
    alert = getattr(candidate, "alert", None)
    merged: dict[str, Any] = dict(alert) if isinstance(alert, dict) else {}
    event = getattr(candidate, "explosion_event", None)
    merged.setdefault("symbol", getattr(candidate, "symbol", "") or "")
    side = getattr(candidate, "side", None)
    merged.setdefault(
        "side",
        side.value if hasattr(side, "value") else str(side or merged.get("side") or ""),
    )
    merged.setdefault("strike", getattr(candidate, "strike", None) or merged.get("strike"))
    merged.setdefault("tier", getattr(candidate, "tier", None) or merged.get("tier"))
    merged.setdefault(
        "explosionScore",
        getattr(candidate, "confidence", None)
        or merged.get("explosionScore")
        or (getattr(event, "explosion_score", None) if event is not None else None),
    )
    if event is not None:
        merged.setdefault("dailyMovePct", getattr(event, "daily_move_pct", None))
        merged.setdefault("peakMovePct", getattr(event, "peak_move_pct", None))
    return merged


def is_grade_a_ftv_first_lift_candidate(candidate: Any) -> bool:
    snap = getattr(candidate, "snap", None)
    return alert_is_grade_a_ftv_first_lift(_candidate_alert(candidate), snap)


def grade_a_ftv_chart_bypass(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "grade_a_ftv_chart_bypass_enabled", True)):
        return False
    return alert_is_grade_a_ftv_first_lift(alert, snap)
