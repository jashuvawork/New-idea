"""Index continuation rally/slide — waive explosion_near_miss for ATM/ITM when index leg confirms.

Captures mid-morning rip/slide legs (e.g. SENSEX CE ₹55→₹205) that radar marks ELITE but
selector drops on premium band / chart lag while index rally off session low is already live.
CE/PE symmetric. Does not relax exec fade or pad ranking (#676).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def _index_bucket(symbol: str) -> str:
    sym = str(symbol or "").upper()
    if "SENSEX" in sym:
        return "SENSEX"
    if "NIFTY" in sym and "BANK" not in sym:
        return "NIFTY"
    return ""


def index_continuation_rally_premium_ok(
    premium: float | None,
    *,
    settings: Any = None,
) -> bool:
    settings = settings or get_settings()
    try:
        prem = float(premium or 0)
    except (TypeError, ValueError):
        return False
    if prem <= 0:
        return False
    lo = float(
        getattr(settings, "index_continuation_rally_min_premium_inr", 18.0) or 18.0
    )
    hi = float(
        getattr(settings, "index_continuation_rally_max_premium_inr", 600.0) or 600.0
    )
    return lo <= prem <= hi + 1e-6


def _readiness_blocks_waive(readiness_reason: str) -> bool:
    rr = str(readiness_reason or "").lower()
    if not rr:
        return False
    if rr == "first_lift_live_velocity_negative":
        return False
    return rr.startswith(
        (
            "first_lift_velocity",
            "first_lift_quality",
            "first_lift_score",
        )
    )


def index_continuation_momentum_ignition_ok(
    alert: Optional[Mapping[str, Any]],
    snap: Optional[SymbolSnapshot],
    *,
    settings: Any = None,
) -> bool:
    """Volume/index ignition with briefly negative live v3 (chop-rally lift start)."""
    settings = settings or get_settings()
    if not bool(
        getattr(settings, "index_continuation_momentum_ignition_enabled", True)
    ):
        return False
    if not isinstance(alert, dict) or snap is None:
        return False
    vol_awake = bool(
        alert.get("volumeAwaken") or alert.get("ictVolumeAwakening")
    )
    try:
        v9 = float(alert.get("velocity9s") or alert.get("velocity_9s") or 0)
    except (TypeError, ValueError):
        v9 = 0.0
    if not vol_awake and v9 <= 0:
        return False
    chart = getattr(snap, "spotChart", None)
    if chart is None:
        return False
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
    min_mom = float(
        getattr(settings, "index_continuation_momentum_ignition_min_mom5_pct", 0.02)
        or 0.02
    )
    if mom5 < min_mom - 1e-6:
        return False
    if bool(
        getattr(
            settings,
            "index_continuation_momentum_ignition_requires_rally_window",
            True,
        )
    ):
        from app.engines.chop_day_guards import in_momentum_rally_window

        if not in_momentum_rally_window():
            return False
    return True


def index_continuation_rally_premium_bypass_active(
    alert: Optional[Mapping[str, Any]],
    snap: Optional[SymbolSnapshot],
    *,
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    """Whether explosion premium_in_band may use the ₹18–₹600 continuation sleeve (stamps alert)."""
    settings = settings or get_settings()
    if not isinstance(alert, dict):
        return False
    if alert.get("indexContinuationRallyNearMissWaive"):
        return index_continuation_rally_premium_ok(
            alert.get("premium"), settings=settings,
        )
    return index_continuation_rally_near_miss_waive(
        alert,
        snap=snap,
        readiness_reason=readiness_reason,
        settings=settings,
    )


def index_continuation_rally_elite_chase_waive_active(
    evidence: Optional[Mapping[str, Any]],
    *,
    day_mode: str = "",
    settings: Any = None,
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """
    After index continuation clears explosion_near_miss, waive elite local-base / FVQ chase
    gates on CHOP+RALLY ATM legs (82100 CE class). CE/PE symmetric; does not touch #676 pad.
    """
    settings = settings or get_settings()
    if not bool(
        getattr(settings, "index_continuation_rally_elite_chase_waive_enabled", True)
    ):
        return False
    if not isinstance(evidence, dict):
        return False
    if not evidence.get("indexContinuationRallyNearMissWaive"):
        return False
    if not index_continuation_rally_premium_ok(evidence.get("premium"), settings=settings):
        return False
    from app.engines.chop_day_guards import _chop_rally_day_modes

    mode = str(day_mode or evidence.get("dayMode") or "").strip().upper()
    allowed = {str(m).strip().upper() for m in _chop_rally_day_modes(settings)}
    if mode not in allowed:
        return False
    if not bool(getattr(settings, "index_continuation_rally_elite_chase_atm_only", True)):
        return True
    if snap is None:
        return False
    side_u = str(evidence.get("side") or "").upper()
    if side_u not in ("CALL", "PUT"):
        return False
    try:
        strike = float(evidence.get("strike") or 0)
    except (TypeError, ValueError):
        return False
    spot = float(getattr(snap, "spot", 0) or 0)
    if strike <= 0 or spot <= 0:
        return False
    bucket = _index_bucket(str(evidence.get("symbol") or getattr(snap, "symbol", "") or ""))
    if bucket not in ("SENSEX", "NIFTY"):
        return False
    from app.engines.moneyness import classify_moneyness

    money = classify_moneyness(
        Side(side_u),
        strike,
        spot,
        symbol=bucket,
        atm=float(getattr(snap, "atmStrike", 0) or 0) or None,
    )
    return money == "ATM"


def index_continuation_rally_near_miss_waive(
    alert: Optional[Mapping[str, Any]],
    *,
    snap: Optional[SymbolSnapshot] = None,
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    """
    Waive explosion_near_miss when index continuation is live and premium is in capture band.

    CALL: ce_rally_lift_ready. PUT: pe_slide_breakdown_ready (mirror).
    """
    settings = settings or get_settings()
    if not bool(
        getattr(settings, "index_continuation_rally_near_miss_enabled", True)
    ):
        return False
    if _readiness_blocks_waive(readiness_reason):
        return False
    rr = str(readiness_reason or "").lower()
    if rr == "first_lift_live_velocity_negative" and not index_continuation_momentum_ignition_ok(
        alert, snap, settings=settings,
    ):
        return False
    if not isinstance(alert, dict) or snap is None:
        return False

    side_u = str(alert.get("side") or "").upper()
    if side_u not in ("CALL", "PUT"):
        return False

    symbol = str(alert.get("symbol") or getattr(snap, "symbol", "") or "").upper()
    bucket = _index_bucket(symbol)
    if bucket not in ("SENSEX", "NIFTY"):
        return False

    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False

    if not index_continuation_rally_premium_ok(alert.get("premium"), settings=settings):
        return False

    try:
        strike = float(alert.get("strike") or 0)
    except (TypeError, ValueError):
        strike = 0.0
    spot = float(getattr(snap, "spot", 0) or 0)
    if strike <= 0 or spot <= 0:
        return False

    from app.engines.moneyness import classify_moneyness

    money = classify_moneyness(
        Side(side_u),
        strike,
        spot,
        symbol=bucket,
        atm=float(getattr(snap, "atmStrike", 0) or 0) or None,
    )
    # Expiry book: ATM+ITM only for CE and PE — never OTM (`allow_otm` stays off).
    allow_otm = bool(getattr(settings, "index_continuation_rally_allow_otm", False))
    if money == "OTM" and not allow_otm:
        return False
    if money not in ("ITM", "ATM") and not (money == "OTM" and allow_otm):
        return False

    score_floor = float(
        getattr(settings, "index_continuation_rally_min_explosion_score", 5.0) or 5.0
    )
    try:
        score = float(alert.get("explosionScore") or alert.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    if score < score_floor - 1e-6:
        return False

    from datetime import datetime
    from zoneinfo import ZoneInfo

    _when = datetime.now(ZoneInfo("Asia/Kolkata"))
    index_leg_ready = False
    chart_structure = False
    if side_u == "CALL":
        from app.engines.ce_rally_lift_timing import ce_rally_lift_ready

        index_leg_ready, _, _ = ce_rally_lift_ready(bucket, snap, settings=settings)
    else:
        from app.engines.pe_slide_breakdown_timing import pe_slide_breakdown_ready

        index_leg_ready, _, _ = pe_slide_breakdown_ready(bucket, snap, settings=settings)

    if not index_leg_ready:
        from app.engines.chart_structure_entry import index_continuation_chart_structure_ok

        chart_structure, cmeta = index_continuation_chart_structure_ok(
            side_u, snap, settings=settings, when=_when,
        )
        if isinstance(alert, dict) and chart_structure:
            alert["indexContinuationChartStructureWaive"] = cmeta
        if not chart_structure:
            return False

    if isinstance(alert, dict):
        alert["indexContinuationRallyNearMissWaive"] = True
    return True