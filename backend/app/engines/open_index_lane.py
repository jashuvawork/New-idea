"""09:15–09:45 IST index-specific open lanes (then normal book after open caution ends).

Weekly expiry priority (Tue NIFTY / Thu SENSEX): nearest index gets the always-on **CE**
lane (like legacy SENSEX CALL); same-week next index gets the **PE** lane (like opt-in
NIFTY PUT). Roles flip through the week — NIFTY CE + SENSEX PE when NIFTY is #1.

Legacy flags still apply when expiry lanes are off or snapshots are missing.

Open-caution **gates** use ``open_setup_guard_when`` (decision clock). ``resolve_lane_when``
keeps snap timestamps for replay helpers that pass explicit ``when=``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import SymbolSnapshot

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

    earliest = _clock_minutes("open_setup_start_hour", "open_setup_start_minute", 9, 15)
    end = _clock_minutes("open_caution_until_hour", "open_caution_until_minute", 9, 45)
    return earliest <= current < end


def in_post_open_setup_window_at(when: datetime) -> bool:
    """09:45–post_open_setup_until: continuation fills after open caution (not full-day waive)."""
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

    start = _clock_minutes("open_caution_until_hour", "open_caution_until_minute", 9, 45)
    end = _clock_minutes(
        "post_open_setup_until_hour",
        "post_open_setup_until_minute",
        10,
        30,
    )
    return start <= current < end


def _index_open_side_aligned(
    index: str,
    side: str,
    *,
    symbol: str = "",
    snap: Any = None,
    settings: Any = None,
) -> bool:
    """CALL on bullish open / PUT on bearish open — mirrors open_caution_side_align (CE/PE)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "open_index_lane_align_to_session_enabled", True)):
        return False
    from app.engines.index_tick_helpers import resolve_index_session

    sym = symbol or index
    ext = resolve_index_session(sym, snap)
    session_open = float(ext.get("open") or 0)
    spot = float(ext.get("last") or 0) or float(getattr(snap, "spot", 0) or 0)
    if session_open <= 0 or spot <= 0:
        return False
    min_move = float(getattr(settings, "open_side_confirmation_min_index_move_pct", 0.10) or 0.10)
    move_pct = (spot - session_open) / session_open * 100.0
    side_u = _side_value(side)
    if side_u == "CALL":
        return move_pct >= min_move
    if side_u == "PUT":
        return move_pct <= -min_move
    return False


def _index_from_symbol_list(symbols: list[str]) -> str | None:
    for raw in symbols:
        bucket = _index_bucket(str(raw or ""))
        if bucket:
            return bucket
    return None


def resolve_open_session_expiry_lane_pair(
    snapshots: dict[str, SymbolSnapshot] | None,
    *,
    settings: Any = None,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """
    Map expiry proximity to open lane pair: (primary_ce_index, secondary_pe_index).

    Uses ``expiry_proximity_ranks`` (nearest weekly expiry vs same-week next index).
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"openSessionExpiryLanes": True}
    from app.engines.capital_allocator import expiry_index_priority_suppressed

    if expiry_index_priority_suppressed(settings):
        return None, None, {
            **meta,
            "mode": "legacy",
            "capitalTierSuppressesExpiryPriority": True,
        }
    if not bool(getattr(settings, "open_session_expiry_lane_enabled", True)):
        return None, None, {**meta, "mode": "legacy"}
    if not snapshots:
        return None, None, {**meta, "mode": "no_snapshots"}
    from app.engines.bad_day_routing import expiry_proximity_ranks

    nearest, nxt = expiry_proximity_ranks(snapshots)
    meta["nearestSymbols"] = list(nearest)
    meta["nextSymbols"] = list(nxt)
    primary = _index_from_symbol_list(nearest)
    secondary = _index_from_symbol_list(nxt)
    if not primary:
        return None, None, {**meta, "mode": "legacy"}
    meta["mode"] = "expiry_pair"
    meta["primaryCeIndex"] = primary
    meta["secondaryPeIndex"] = secondary
    return primary, secondary, meta


def allowed_open_lane_sides(
    index: str,
    settings: Any,
    *,
    symbol: str = "",
    snap: Any = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> set[str] | None:
    """Sides allowed in open caution for this index, or None when lane idle."""
    settings = settings or get_settings()
    if snapshots:
        primary, secondary, prof = resolve_open_session_expiry_lane_pair(
            snapshots, settings=settings,
        )
        if prof.get("mode") == "expiry_pair" and primary:
            sides: set[str] = set()
            if index == primary and bool(
                getattr(settings, "open_session_primary_ce_lane_enabled", True)
            ):
                sides.add("CALL")
            if (
                secondary
                and index == secondary
                and bool(getattr(settings, "open_session_secondary_pe_lane_enabled", True))
            ):
                sides.add("PUT")
            return sides or None

    if index == "SENSEX":
        sides: set[str] = set()
        if bool(getattr(settings, "open_sensex_call_lane_enabled", True)):
            sides.add("CALL")
        if bool(getattr(settings, "open_sensex_put_lane_enabled", True)):
            sides.add("PUT")
        return sides or None
    if index == "NIFTY":
        sides = set()
        sym = symbol or "NIFTY"
        if bool(getattr(settings, "open_nifty_put_lane_enabled", False)):
            sides.add("PUT")
        if bool(getattr(settings, "open_nifty_call_lane_enabled", False)):
            sides.add("CALL")
        if bool(getattr(settings, "open_nifty_call_lane_on_aligned_open_enabled", True)):
            if _index_open_side_aligned(index, "CALL", symbol=sym, snap=snap, settings=settings):
                sides.add("CALL")
        if bool(getattr(settings, "open_nifty_put_lane_on_aligned_open_enabled", True)):
            if _index_open_side_aligned(index, "PUT", symbol=sym, snap=snap, settings=settings):
                sides.add("PUT")
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
        "niftyCallLaneOnAlignedOpen": bool(
            getattr(settings, "open_nifty_call_lane_on_aligned_open_enabled", True)
        ),
        "niftyPutLaneOnAlignedOpen": bool(
            getattr(settings, "open_nifty_put_lane_on_aligned_open_enabled", True)
        ),
        "sessionExpiryLanesEnabled": bool(
            getattr(settings, "open_session_expiry_lane_enabled", True)
        ),
        "postOpenSetupUntilIst": (
            f"{getattr(settings, 'post_open_setup_until_hour', 10):02d}:"
            f"{getattr(settings, 'post_open_setup_until_minute', 30):02d}"
        ),
        "requireFirstLift": bool(getattr(settings, "open_index_lane_require_first_lift", True)),
        "minEliteScore": float(getattr(settings, "open_index_lane_min_elite_score", 90.0) or 90.0),
        "maxLocalBasePct": float(
            getattr(settings, "open_index_lane_max_local_base_pct", 15.0) or 15.0
        ),
        "allowedSetups": str(getattr(settings, "open_index_lane_allowed_setups_csv", "FTV,V") or "FTV,V"),
        "windowIst": "open_setup_start through open_caution_until (default 09:15–09:45)",
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
        if not first_lift and bool(
            getattr(settings, "open_index_lane_open_rip_first_lift_waiver_enabled", True)
        ):
            from app.engines.pad_lane_capture import _open_setup_first_lift_evidence

            tier_u = str(
                alert.get("tier") or getattr(candidate, "tier", "") or ""
            ).upper()
            local_pad = float(
                alert.get("ictBaseRelativeMovePct")
                or alert.get("localBaseMovePct")
                or alert.get("offLowMovePct")
                or 0.0
            )
            max_local = float(
                getattr(settings, "open_index_lane_max_local_base_pct", 15.0) or 15.0
            )
            if tier_u in {"ELITE", "EXPLODING"} and (
                _open_setup_first_lift_evidence(alert)
                or 2.0 <= local_pad <= max_local + 1e-6
            ):
                first_lift = True
                meta["firstLiftOpenRipWaiver"] = True
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


def open_setup_guard_when(
    candidate: Any = None,
    when: Optional[datetime] = None,
) -> datetime:
    """Decision clock for 09:15–09:45 open-caution guards (every session day).

    Live pretrade must not treat a stale ``candidate.snap.timestamp`` as still
    inside open caution after 09:45 (#676 never extended open caution past that).
    EOD replay passes explicit ``when=`` or patches ``datetime.now``.
    """
    if when is not None and isinstance(when, datetime):
        ts = when
    else:
        ts = datetime.now(IST)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def resolve_lane_when(
    candidate: Any,
    when: Optional[datetime] = None,
) -> datetime:
    """Replay helper: explicit when, else snap timestamp, else now (not for open gates)."""
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
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """True when open caution window + index lane side + lane quality all pass."""
    ok, reason, meta = validate_open_index_lane(
        candidate,
        settings=settings,
        when=open_setup_guard_when(candidate, when),
        snapshots=snapshots,
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
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Returns (allowed, reason, meta). Idle outside open caution and when master off.
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "open_index_lane_enabled", True)):
        return True, "ok", {}

    when = open_setup_guard_when(candidate, when)
    if not in_open_caution_window_at(when):
        return True, "ok", {}

    sym = str(getattr(candidate, "symbol", "") or "")
    index = _index_bucket(sym)
    if not index:
        return True, "ok", {}

    snap = getattr(candidate, "snap", None)
    if snapshots is None and snap is not None:
        sym_u = sym.upper()
        if sym_u:
            snapshots = {sym_u: snap}
    allowed_sides = allowed_open_lane_sides(
        index, settings, symbol=sym, snap=snap, snapshots=snapshots,
    )
    if not allowed_sides:
        return True, "ok", {}

    side = _side_value(getattr(candidate, "side", ""))
    _, _, expiry_meta = resolve_open_session_expiry_lane_pair(
        snapshots, settings=settings,
    )
    meta: dict[str, Any] = {
        "openIndexLane": True,
        "openIndexLaneIndex": index,
        "openIndexLaneAllowedSides": sorted(allowed_sides),
        **expiry_meta,
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
