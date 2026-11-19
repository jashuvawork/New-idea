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
    return rr.startswith(
        (
            "first_lift_velocity",
            "first_lift_quality",
            "first_lift_score",
            "first_lift_live_velocity_negative",
        )
    )


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
    allow_otm = bool(
        getattr(settings, "index_continuation_rally_allow_otm", False)
    )
    if money == "OTM" and not allow_otm:
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

    if side_u == "CALL":
        from app.engines.ce_rally_lift_timing import ce_rally_lift_ready

        ready, _, _ = ce_rally_lift_ready(bucket, snap, settings=settings)
        if not ready:
            return False
    else:
        from app.engines.pe_slide_breakdown_timing import pe_slide_breakdown_ready

        ready, _, _ = pe_slide_breakdown_ready(bucket, snap, settings=settings)
        if not ready:
            return False

    if isinstance(alert, dict):
        alert["indexContinuationRallyNearMissWaive"] = True
    return True