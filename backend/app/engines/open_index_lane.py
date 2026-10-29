"""09:20–09:45 IST index-specific open lanes (then normal book after open caution ends).

Research-backed defaults on main: SENSEX CALL + first lift ON; NIFTY PUT opt-in via
``open_nifty_put_lane_enabled``. Does not waive cash-candle hold, open macro, or premium band.
Replay uses ``resolve_lane_when`` (snap timestamp, not wall clock).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings

IST = ZoneInfo("Asia/Kolkata")


def _index_bucket(symbol: str) -> str | None:
    sym = str(symbol or "").upper()
    if "SENSEX" in sym:
        return "SENSEX"
    if "NIFTY" in sym and "BANK" not in sym:
        return "NIFTY"
    return None


def _side_value(side: Any) -> str:
    raw = str(getattr(side, "value", side) or "").upper()
    if raw in {"CALL", "CE", "C"}:
        return "CALL"
    if raw in {"PUT", "PE", "P"}:
        return "PUT"
    return raw


def in_open_caution_window_at(when: datetime) -> bool:
    """Same window as session_timing.in_open_caution_window, for replay/tests."""
    settings = get_settings()
    if not isinstance(when, datetime):
        return False
    local = when.astimezone(IST)
    try:
        current = int(local.hour) * 60 + int(local.minute)
    except (TypeError, ValueError):
        return False

    def _clock_minutes(hour_attr: str, min_attr: str, default_h: int, default_m: int) -> int:
        try:
            h = int(getattr(settings, hour_attr, default_h))
            m = int(getattr(settings, min_attr, default_m))
            return h * 60 + m
        except (TypeError, ValueError):
            return default_h * 60 + default_m

    earliest = _clock_minutes("entry_earliest_hour", "entry_earliest_minute", 9, 20)
    end = _clock_minutes("open_caution_until_hour", "open_caution_until_minute", 9, 45)
    return earliest <= current < end


def allowed_open_lane_sides(index: str, settings: Any) -> set[str] | None:
    """Sides allowed in open caution for this index, or None when lane idle."""
    if index == "SENSEX":
        sides: set[str] = set()
        if bool(getattr(settings, "open_sensex_call_lane_enabled", True)):
            sides.add("CALL")
        if bool(getattr(settings, "open_sensex_put_lane_enabled", True)):
            sides.add("PUT")
        return sides or None
    if index == "NIFTY":
        sides = set()
        if bool(getattr(settings, "open_nifty_put_lane_enabled", False)):
            sides.add("PUT")
        if bool(getattr(settings, "open_nifty_call_lane_enabled", False)):
            sides.add("CALL")
        return sides or None
    return None


def _lane_active_for_index(index: str, settings: Any) -> tuple[bool, str | None]:
    """Legacy: first allowed side when exactly one lane side is active."""
    sides = allowed_open_lane_sides(index, settings)
    if not sides:
        return False, None
    if len(sides) == 1:
        return True, next(iter(sides))
    return True, None


def open_index_lane_summary(settings: Any = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "enabled": bool(getattr(settings, "open_index_lane_enabled", True)),
        "sensexCallLane": bool(getattr(settings, "open_sensex_call_lane_enabled", True)),
        "sensexPutLane": bool(getattr(settings, "open_sensex_put_lane_enabled", True)),
        "niftyPutLane": bool(getattr(settings, "open_nifty_put_lane_enabled", False)),
        "requireFirstLift": bool(getattr(settings, "open_index_lane_require_first_lift", True)),
        "minEliteScore": float(getattr(settings, "open_index_lane_min_elite_score", 90.0) or 90.0),
        "maxLocalBasePct": float(
            getattr(settings, "open_index_lane_max_local_base_pct", 15.0) or 15.0
        ),
        "allowedSetups": str(getattr(settings, "open_index_lane_allowed_setups_csv", "FTV,V") or "FTV,V"),
        "windowIst": "entry_earliest through open_caution_until (default 09:20–09:45)",
    }


def _alert_dict(candidate: Any) -> dict[str, Any]:
    alert = getattr(candidate, "alert", None)
    return alert if isinstance(alert, dict) else {}


def _lane_quality_ok(candidate: Any, settings: Any) -> tuple[bool, str, dict[str, Any]]:
    from app.engines.elite_score_engine import infer_setup_type
    from app.engines.trade_ranking import rank_entry_candidate

    alert = _alert_dict(candidate)
    meta: dict[str, Any] = {"openIndexLane": True}

    if bool(getattr(settings, "open_index_lane_require_first_lift", True)):
        first_lift = bool(
            alert.get("ictFirstLift")
            or alert.get("firstLift")
            or alert.get("firstLiftCapture")
        )
        meta["firstLift"] = first_lift
        if not first_lift:
            return False, "open_index_lane_no_first_lift", meta

    ranking = rank_entry_candidate(candidate)
    evidence = dict(ranking.get("evidence") or {})
    setup = infer_setup_type(evidence)
    allowed = {
        s.strip().upper()
        for s in str(getattr(settings, "open_index_lane_allowed_setups_csv", "FTV,V") or "FTV,V").split(",")
        if s.strip()
    }
    meta["setup"] = setup
    if allowed and setup.upper() not in allowed:
        return False, "open_index_lane_setup_not_allowed", meta

    from app.engines.elite_score_engine import compute_elite_score, infer_stage

    stage = infer_stage(evidence)
    score, band, _ = compute_elite_score(evidence, ranking, setup=setup)
    meta["eliteScore"] = score
    meta["eliteBand"] = band
    meta["stage"] = stage
    min_score = float(getattr(settings, "open_index_lane_min_elite_score", 90.0) or 90.0)
    if score < min_score:
        return False, f"open_index_lane_elite_below_{min_score:g}", meta

    local = float(
        alert.get("ictBaseRelativeMovePct")
        or alert.get("localBaseMovePct")
        or evidence.get("localBaseMovePct")
        or 999.0
    )
    meta["localBasePct"] = local
    max_local = float(getattr(settings, "open_index_lane_max_local_base_pct", 15.0) or 15.0)
    if local > max_local + 1e-6:
        return False, "open_index_lane_local_base_chase", meta

    meta["openIndexLanePassed"] = True
    return True, "ok", meta


def resolve_lane_when(
    candidate: Any,
    when: Optional[datetime] = None,
) -> datetime:
    """Replay/live clock: prefer explicit when, then candidate.snap.timestamp, then now."""
    if when is not None and isinstance(when, datetime):
        ts = when
    else:
        snap = getattr(candidate, "snap", None)
        raw = getattr(snap, "timestamp", None) if snap is not None else None
        ts = raw if isinstance(raw, datetime) else None
    if ts is None:
        return datetime.now(IST)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def open_index_lane_qualified(
    candidate: Any,
    *,
    settings: Any = None,
    when: Optional[datetime] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """True when open caution window + index lane side + lane quality all pass."""
    ok, reason, meta = validate_open_index_lane(
        candidate, settings=settings, when=resolve_lane_when(candidate, when),
    )
    if not ok:
        return False, reason, meta
    if meta.get("openIndexLanePassed"):
        return True, "ok", meta
    return False, "lane_idle", meta


def validate_open_index_lane(
    candidate: Any,
    *,
    settings: Any = None,
    when: Optional[datetime] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Returns (allowed, reason, meta). Idle outside open caution and when master off.
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "open_index_lane_enabled", True)):
        return True, "ok", {}

    when = resolve_lane_when(candidate, when)
    if not in_open_caution_window_at(when):
        return True, "ok", {}

    sym = str(getattr(candidate, "symbol", "") or "")
    index = _index_bucket(sym)
    if not index:
        return True, "ok", {}

    allowed_sides = allowed_open_lane_sides(index, settings)
    if not allowed_sides:
        return True, "ok", {}

    side = _side_value(getattr(candidate, "side", ""))
    meta: dict[str, Any] = {
        "openIndexLane": True,
        "openIndexLaneIndex": index,
        "openIndexLaneAllowedSides": sorted(allowed_sides),
    }
    if side not in allowed_sides:
        if len(allowed_sides) == 1:
            only = next(iter(allowed_sides))
            meta["openIndexLaneRequiredSide"] = only
            return False, f"open_index_lane_{index.lower()}_{only.lower()}_only", meta
        return False, "open_index_lane_side_not_allowed", meta

    ok, reason, qmeta = _lane_quality_ok(candidate, settings)
    meta.update(qmeta)
    if not ok:
        return False, reason, meta
    meta["openIndexLaneLane"] = f"{index}_{side}"
    return True, "ok", meta
