"""Top FTV/V bypass on NIFTY/SENSEX expiry worst days.

Lifts session halts, lowers score/rank floors, and bypasses chart alignment for any
classified top moment (FTV, V, ELITE, EXPLODING) on index expiry worst days — broader
than grade-A first-lift only (Aug27 SENSEX 77300 PUT +146%: detected winner, blocked
by expiry_worst_day_declining_halt + score 33 < 45).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.engines.top_moment_gate import TOP_MOMENT_TYPES, classify_top_moment_type
from app.models.schemas import SymbolSnapshot


def top_ftv_v_symbols(settings: Any | None = None) -> set[str]:
    s = settings or get_settings()
    raw = str(
        getattr(s, "top_ftv_v_expiry_bypass_symbols_csv", "NIFTY,SENSEX")
        or "NIFTY,SENSEX"
    )
    return {part.strip().upper() for part in raw.split(",") if part.strip()}


def alert_evidence(alert: Mapping[str, Any]) -> dict[str, Any]:
    """Build top-moment evidence from a live explosion alert."""
    return {
        "tier": str(alert.get("tier") or "").upper(),
        "vRipReady": bool(alert.get("ictVRipReady") or alert.get("vRipReady")),
        "slowGrindSuddenLift": bool(
            alert.get("slowGrindSuddenLiftReady")
            or alert.get("ictSlowGrindSuddenLift")
            or alert.get("slowGrindSuddenLift")
        ),
        "slowGrindConsolidationBase": bool(
            alert.get("slowGrindConsolidationBaseReady")
            or alert.get("ictSlowGrindConsolidationBase")
            or alert.get("slowGrindConsolidationBase")
        ),
        "fastBullishLocalBase": bool(
            alert.get("fastBullishLocalBaseReady")
            or alert.get("bullishLocalBaseActive")
        ),
        "squeezeRelease": bool(
            alert.get("squeezeReleaseReady") or alert.get("ictSqueezeRelease")
        ),
        "indexLedOptionLag": bool(
            alert.get("indexLedOptionLagReady") or alert.get("ictIndexLedOptionLag")
        ),
        "stealthCvdCoil": bool(
            alert.get("stealthCvdCoilReady") or alert.get("ictStealthCvdCoil")
        ),
        "microPullbackRetest": bool(
            alert.get("microPullbackRetestReady") or alert.get("ictMicroPullbackRetest")
        ),
        "premiumFvgPad": bool(
            alert.get("premiumFvgPadReady") or alert.get("ictPremiumFvgPad")
        ),
        "doubleDipVbase": bool(
            alert.get("doubleDipVbaseReady") or alert.get("ictDoubleDipVbase")
        ),
        "earlyRadarPadCapture": bool(
            alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")
        ),
        "buildingRipReady": bool(alert.get("ictBuildingRipReady")),
        "buildingRipHelpersOk": bool(
            alert.get("buildingRipHelpersOk") or alert.get("buildingLiftHelping")
        ),
        "buildingLiftHelping": bool(alert.get("buildingLiftHelping")),
        "flatThenVertical": bool(alert.get("ictFlatThenVertical")),
        "activeBreakout": bool(alert.get("ictBreakout")),
        "armedBaseLaunch": bool(
            alert.get("ictArmedBaseLaunch") or alert.get("ictBaseArmed")
        ),
        "eliteBaseReady": bool(alert.get("ictEliteBaseReady")),
        "firstLift": bool(alert.get("ictFirstLift")),
        "armedBaseSustainedLift": bool(alert.get("ictArmedBaseSustainedLift")),
        "indexHelpersConfirm": bool(alert.get("indexHelpersConfirm")),
        "indexTickSpike": bool(alert.get("indexTickSpike")),
        "midRipCoil": bool(alert.get("ictMidRipCoil") or alert.get("midRipCoil")),
        "expiryFastVerticalBurst": bool(
            alert.get("expiryFastVerticalBurst")
            or "fastVerticalBurst" in str(alert.get("reason") or "")
        ),
    }


def alert_top_moment_type(alert: Mapping[str, Any]) -> Optional[str]:
    return classify_top_moment_type(alert_evidence(alert))


def top_ftv_v_expiry_floors(settings: Any | None = None) -> dict[str, float]:
    s = settings or get_settings()
    return {
        "minScore": float(
            getattr(s, "top_ftv_v_expiry_bypass_min_explosion_score", 12.0) or 12.0
        ),
        "minRank": float(
            getattr(s, "top_ftv_v_expiry_bypass_min_rank", 0.0) or 0.0
        ),
        "minBaseMove": float(
            getattr(s, "top_ftv_v_expiry_bypass_min_base_move_pct", 5.0) or 5.0
        ),
        "maxBaseMove": float(
            getattr(s, "top_ftv_v_expiry_bypass_max_base_move_pct", 55.0) or 55.0
        ),
    }


def _session_move(alert: Mapping[str, Any]) -> float:
    return max(
        float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
        float(alert.get("peakMovePct") or 0),
    )


def alert_is_top_ftv_or_v(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "top_ftv_v_expiry_bypass_enabled", True)):
        return False
    if not bool(alert.get("tradeable", True)):
        return False
    sym = str(alert.get("symbol") or "").upper()
    if sym and sym not in top_ftv_v_symbols(settings):
        return False
    moment = alert_top_moment_type(alert)
    if moment not in TOP_MOMENT_TYPES:
        return False
    score = float(alert.get("explosionScore") or alert.get("score") or 0)
    floors = top_ftv_v_expiry_floors(settings)
    if score < floors["minScore"]:
        return False
    if bool(alert.get("faded") or alert.get("exhaustedReentry")):
        return False
    from app.engines.premium_filter import premium_in_band

    move = _session_move(alert)
    if not premium_in_band(alert.get("premium"), mode="explosion", peak_move_pct=move):
        return False
    return True


def _side_value(side: Any) -> str:
    raw = getattr(side, "value", side)
    return str(raw or "").upper()


def _expiry_worst_flat_vertical_at_base(evidence: Mapping[str, Any]) -> bool:
    """True when ELITE flat→vertical at base qualifies for expiry-worst waivers."""
    settings = get_settings()
    tier = str(evidence.get("tier") or "").upper()
    if tier != "ELITE":
        return False
    if not bool(evidence.get("flatThenVertical") or evidence.get("ictFlatThenVertical")):
        return False
    if bool(evidence.get("activeBreakout") or evidence.get("ictBreakout")):
        return False
    local = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("ictBaseRelativeMovePct") or 0),
        float(evidence.get("offLowMovePct") or 0),
    )
    max_local = float(
        getattr(settings, "expiry_worst_pe_structure_bypass_max_local_pct", 22.0) or 22.0
    )
    if local > max_local + 1e-6:
        return False
    quality = float(
        evidence.get("flatVerticalQuality")
        or evidence.get("ictFlatVerticalQuality")
        or 0
    )
    min_quality = float(
        getattr(settings, "expiry_worst_pe_structure_bypass_min_flat_quality", 65.0) or 65.0
    )
    volume = bool(
        evidence.get("volumeAwaken")
        or evidence.get("volumeAwakening")
        or evidence.get("ictVolumeAwakening")
    )
    if not volume and quality + 1e-9 < min_quality:
        return False
    min_score = float(
        getattr(settings, "expiry_worst_pe_structure_bypass_min_score", 55.0) or 55.0
    )
    score = float(evidence.get("explosionScore") or evidence.get("score") or 0)
    return score + 1e-9 >= min_score


def chop_rally_structure_bypass_symbols(settings: Any | None = None) -> set[str]:
    s = settings or get_settings()
    raw = str(
        getattr(s, "chop_rally_structure_bypass_symbols_csv", "NIFTY,SENSEX,BANKNIFTY")
        or "NIFTY,SENSEX,BANKNIFTY"
    )
    return {part.strip().upper() for part in raw.split(",") if part.strip()}


def _chop_rally_day_mode(day_mode: str = "") -> bool:
    dm = str(day_mode or "").strip().upper()
    return "CHOP" in dm and "RALLY" in dm


def chop_rally_aligned_structure_bypass_allowed(
    *,
    tier: str,
    score: float,
    base_move_pct: float,
    volume_awakening: bool,
    side: str,
    day_mode: str = "",
    snap: Optional[SymbolSnapshot] = None,
    row: Optional[Mapping[str, Any]] = None,
    symbol: str = "",
) -> bool:
    """CHOP + RALLY — ELITE flat→vertical / first-lift at base (SENSEX ₹170 CE, PE mirror)."""
    settings = get_settings()
    if not bool(getattr(settings, "chop_rally_structure_bypass_enabled", True)):
        return False
    if not _chop_rally_day_mode(day_mode):
        return False
    sym = str(symbol or (row or {}).get("symbol") or "").upper()
    if snap is not None and not sym:
        sym = str(getattr(snap, "symbol", "") or "").upper()
    if sym and sym not in chop_rally_structure_bypass_symbols(settings):
        return False
    side_u = _side_value(side)
    if side_u not in ("PUT", "CALL"):
        return False

    allowed = {
        t.strip().upper()
        for t in str(
            getattr(settings, "bullish_day_structure_bypass_tiers_csv", "ELITE,EXPLODING")
            or "ELITE,EXPLODING"
        ).split(",")
        if t.strip()
    }
    tier_u = str(tier or "").upper()
    if tier_u not in allowed:
        return False
    min_score = float(
        getattr(settings, "chop_rally_structure_bypass_min_score", 55.0) or 55.0
    )
    if float(score or 0) + 1e-9 < min_score:
        return False

    alert = row if isinstance(row, Mapping) else {}
    local = max(
        float(base_move_pct or 0),
        float(alert.get("localBaseMovePct") or 0),
        float(alert.get("ictBaseRelativeMovePct") or 0),
        float(alert.get("offLowMovePct") or 0),
        float(alert.get("offHighMovePct") or 0),
    )
    max_local = float(
        getattr(settings, "chop_rally_structure_bypass_max_local_pct", 22.0) or 22.0
    )
    if local > max_local + 1e-6:
        return False

    flat_vertical = bool(
        alert.get("ictFlatThenVertical")
        or alert.get("flatThenVertical")
    )
    launch_lane = bool(
        alert.get("ictFirstLift")
        or alert.get("ictArmedBaseLaunch")
        or alert.get("ictBaseArmed")
        or alert.get("buildingRipReady")
        or alert.get("ictBuildingRipReady")
    )
    if not (flat_vertical or launch_lane):
        return False

    min_quality = float(
        getattr(settings, "chop_rally_structure_bypass_min_flat_quality", 65.0) or 65.0
    )
    quality = float(
        alert.get("flatVerticalQuality")
        or alert.get("ictFlatVerticalQuality")
        or 0
    )
    if not volume_awakening and quality + 1e-9 < min_quality:
        return False

    if snap is not None and snap.spotChart is not None:
        from app.engines.spot_direction import side_aligned_with_chart

        if not side_aligned_with_chart(side_u, snap.spotChart):
            return False
    return True


def _expiry_worst_structure_bypass_allowed(
    *,
    tier: str,
    score: float,
    base_move_pct: float,
    volume_awakening: bool,
    side: str,
    day_mode: str = "",
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    row: Optional[Mapping[str, Any]] = None,
    enabled: bool = True,
) -> bool:
    """EXPIRY WORST morning — ELITE flat→vertical at base before ictBreakout stamps."""
    settings = get_settings()
    if not enabled:
        return False
    from app.engines.ict_breakout_monitor import _expiry_worst_session

    if not _expiry_worst_session(day_mode=day_mode, state=state):
        return False
    side_u = _side_value(side)
    if side_u not in ("PUT", "CALL"):
        return False
    try:
        from app.engines.session_timing import in_midday_chop_window

        if in_midday_chop_window():
            return False
    except Exception:
        pass

    allowed = {
        t.strip().upper()
        for t in str(
            getattr(settings, "bullish_day_structure_bypass_tiers_csv", "ELITE,EXPLODING")
            or "ELITE,EXPLODING"
        ).split(",")
        if t.strip()
    }
    tier_u = str(tier or "").upper()
    if tier_u not in allowed:
        return False
    min_score = float(
        getattr(settings, "expiry_worst_pe_structure_bypass_min_score", 55.0) or 55.0
    )
    if float(score or 0) + 1e-9 < min_score:
        return False

    alert = row if isinstance(row, Mapping) else {}
    local = max(
        float(base_move_pct or 0),
        float(alert.get("localBaseMovePct") or 0),
        float(alert.get("ictBaseRelativeMovePct") or 0),
        float(alert.get("offLowMovePct") or 0),
    )
    max_local = float(
        getattr(settings, "expiry_worst_pe_structure_bypass_max_local_pct", 22.0) or 22.0
    )
    if local > max_local + 1e-6:
        return False

    flat_vertical = bool(
        alert.get("ictFlatThenVertical")
        or alert.get("flatThenVertical")
    )
    launch_lane = bool(
        alert.get("ictFirstLift")
        or alert.get("ictArmedBaseLaunch")
        or alert.get("ictBaseArmed")
        or alert.get("buildingRipReady")
        or alert.get("ictBuildingRipReady")
    )
    if not (flat_vertical or launch_lane):
        return False

    min_quality = float(
        getattr(settings, "expiry_worst_pe_structure_bypass_min_flat_quality", 65.0)
        or 65.0
    )
    quality = float(
        alert.get("flatVerticalQuality")
        or alert.get("ictFlatVerticalQuality")
        or 0
    )
    if not volume_awakening and quality + 1e-9 < min_quality:
        return False

    if snap is not None and snap.spotChart is not None:
        from app.engines.spot_direction import side_aligned_with_chart

        if not side_aligned_with_chart(side_u, snap.spotChart):
            return False
    return True


def expiry_worst_pe_structure_bypass_allowed(
    *,
    tier: str,
    score: float,
    base_move_pct: float,
    volume_awakening: bool,
    side: str = "",
    day_mode: str = "",
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    row: Optional[Mapping[str, Any]] = None,
) -> bool:
    settings = get_settings()
    return _expiry_worst_structure_bypass_allowed(
        tier=tier,
        score=score,
        base_move_pct=base_move_pct,
        volume_awakening=volume_awakening,
        side="PUT",
        day_mode=day_mode,
        state=state,
        snap=snap,
        row=row,
        enabled=bool(getattr(settings, "expiry_worst_pe_structure_bypass_enabled", True)),
    )


def expiry_worst_ce_structure_bypass_allowed(
    *,
    tier: str,
    score: float,
    base_move_pct: float,
    volume_awakening: bool,
    side: str = "",
    day_mode: str = "",
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    row: Optional[Mapping[str, Any]] = None,
) -> bool:
    settings = get_settings()
    return _expiry_worst_structure_bypass_allowed(
        tier=tier,
        score=score,
        base_move_pct=base_move_pct,
        volume_awakening=volume_awakening,
        side="CALL",
        day_mode=day_mode,
        state=state,
        snap=snap,
        row=row,
        enabled=bool(getattr(settings, "expiry_worst_ce_structure_bypass_enabled", True)),
    )


def top_ftv_v_expiry_worst_waive(evidence: Mapping[str, Any]) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "top_ftv_v_expiry_bypass_enabled", True)):
        return False
    sym = str(evidence.get("symbol") or "").upper()
    if sym and sym not in top_ftv_v_symbols(settings):
        return False
    if _expiry_worst_flat_vertical_at_base(evidence):
        floors = top_ftv_v_expiry_floors(settings)
        score = float(evidence.get("explosionScore") or evidence.get("score") or 0)
        return score >= floors["minScore"]
    moment = classify_top_moment_type(evidence)
    if moment in ("FTV", "V"):
        pass
    elif moment in ("ELITE", "EXPLODING"):
        if not bool(
            evidence.get("firstLift")
            or evidence.get("vRipReady")
            or evidence.get("expiryFastVerticalBurst")
        ):
            return False
    else:
        return False
    floors = top_ftv_v_expiry_floors(settings)
    score = float(evidence.get("explosionScore") or evidence.get("score") or 0)
    return score >= floors["minScore"]


def snapshots_have_top_ftv_or_v(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            merged = dict(alert)
            merged.setdefault("symbol", snap.symbol)
            if alert_is_top_ftv_or_v(merged, snap):
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
        merged.setdefault("ictVRipReady", getattr(event, "reason", "") == "v_rip_session_low")
    return merged


def is_top_ftv_or_v_candidate(candidate: Any) -> bool:
    snap = getattr(candidate, "snap", None)
    return alert_is_top_ftv_or_v(_candidate_alert(candidate), snap)


def top_ftv_v_chart_bypass(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "top_ftv_v_expiry_chart_bypass_enabled", True)):
        return False
    return alert_is_top_ftv_or_v(alert, snap)


def candidate_evidence(candidate: Any) -> dict[str, Any]:
    alert = _candidate_alert(candidate)
    evidence = alert_evidence(alert)
    evidence["symbol"] = str(alert.get("symbol") or "").upper()
    evidence["explosionScore"] = float(
        alert.get("explosionScore") or alert.get("score") or 0
    )
    evidence["flatVerticalQuality"] = float(
        alert.get("flatVerticalQuality") or alert.get("ictFlatVerticalQuality") or 0
    )
    evidence["velocity3s"] = float(alert.get("velocity3s") or 0)
    evidence["flatThenVertical"] = bool(
        evidence.get("flatThenVertical") or alert.get("ictFlatThenVertical")
    )
    evidence["firstLift"] = bool(evidence.get("firstLift") or alert.get("ictFirstLift"))
    return evidence
