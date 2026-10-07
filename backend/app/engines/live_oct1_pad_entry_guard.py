"""Oct 1 / Sep917 live pad entry — block session-high chase under paper parity.

Oct 7 NIFTY 22700 CE: local base ~7% but fill at ₹158 with drawdownFromHighPct≈0
(session-high chase). Paper Oct 1 takes the pad (~₹122), not the rip top.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import SymbolSnapshot


def _alert_and_evidence(candidate: Any) -> dict[str, Any]:
    alert = getattr(candidate, "alert", None)
    base = dict(alert) if isinstance(alert, dict) else {}
    pre = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pre.get("causalRanking") if isinstance(pre, dict) else {}
    if not isinstance(ranking, dict):
        ranking = {}
    nested = ranking.get("evidence") if isinstance(ranking.get("evidence"), dict) else {}
    return {**base, **nested, **ranking}


def _session_range_metrics(candidate: Any) -> tuple[float, float]:
    """Return (sessionRangePosition 0–1, drawdownFromHighPct)."""
    meta = getattr(candidate, "liveEntryScoreMeta", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    pos = float(meta.get("sessionRangePosition") or 0)
    dd = float(meta.get("drawdownFromHighPct") or 0)

    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        prem = float(alert.get("premium") or alert.get("lastPremium") or 0)
        peak = float(
            alert.get("sessionPeakPremium")
            or alert.get("peakPremium")
            or alert.get("sessionPeak")
            or 0
        )
        low = float(alert.get("sessionLowPremium") or alert.get("sessionLow") or 0)
        if peak > low > 0 and prem > 0 and pos <= 0:
            pos = (prem - low) / (peak - low)
        if peak > 0 and prem > 0 and dd == 0 and peak > prem:
            dd = (prem - peak) / peak * 100.0

    return pos, dd


def live_oct1_pad_entry_order_gate(
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Order / paper-parity submit boundary — hard pad location under parity stack."""
    from app.engines.live_paper_parity import live_paper_parity_active

    settings = settings or get_settings()
    if not live_paper_parity_active(settings):
        return False, "", {}
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "", {}
    blocked, reason, meta = live_oct1_pad_entry_blocked(
        candidate, snap, settings=settings,
    )
    return blocked, reason, meta


def live_oct1_pad_entry_blocked(
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Under live paper parity: require Sep917 near-base shape AND pad location
    (not session-high chase). CE/PE symmetric.
    """
    from app.engines.live_paper_parity import live_paper_parity_active

    settings = settings or get_settings()
    meta: dict[str, Any] = {"liveOct1PadGuard": True}
    if not live_paper_parity_active(settings):
        return False, "", meta
    if not bool(getattr(settings, "live_paper_parity_pad_entry_guard_enabled", True)):
        return False, "", meta
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "", meta

    evidence = _alert_and_evidence(candidate)
    alert = getattr(candidate, "alert", None)
    alert_map = alert if isinstance(alert, dict) else {}
    pre = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pre.get("causalRanking") if isinstance(pre, dict) else {}

    from app.engines.best_trade_policy import symmetric_best_trade_at_base_capture

    at_base, base_reason = symmetric_best_trade_at_base_capture(
        evidence,
        alert_map,
        ranking=ranking if isinstance(ranking, dict) else None,
        settings=settings,
    )
    meta["nearBaseShape"] = at_base
    meta["nearBaseReason"] = base_reason
    if not at_base:
        return True, "live_oct1_not_near_base_shape", meta

    pos, dd = _session_range_metrics(candidate)
    meta["sessionRangePosition"] = round(pos, 3)
    meta["drawdownFromHighPct"] = round(dd, 2)

    max_pos = float(
        getattr(settings, "live_paper_parity_max_session_range_position", 0.52) or 0.52
    )
    # drawdownFromHighPct: 0 = at session high; more negative = deeper off high.
    min_off_high = float(
        getattr(settings, "live_paper_parity_min_off_session_high_pct", 6.0) or 6.0
    )
    if pos > max_pos + 1e-6:
        return True, "live_oct1_chase_session_range_high", meta
    if dd > -min_off_high + 1e-6:
        return True, "live_oct1_chase_at_session_high", meta

    from app.engines.sep09_intent_guards import sep09_near_peak_after_extended_rip

    side = str(
        getattr(getattr(candidate, "side", None), "value", None)
        or getattr(candidate, "side", "")
        or evidence.get("side")
        or ""
    ).upper()
    near_peak, np_reason = sep09_near_peak_after_extended_rip(
        evidence,
        premium=float(
            getattr(candidate, "premium", 0) or evidence.get("premium") or 0
        ),
        symbol=str(getattr(candidate, "symbol", "") or evidence.get("symbol") or ""),
        strike=float(getattr(candidate, "strike", 0) or evidence.get("strike") or 0),
        side=side,
        alert=evidence,
        settings=settings,
    )
    if near_peak:
        meta["sep09NearPeak"] = np_reason
        return True, np_reason or "live_oct1_sep09_near_peak_chase", meta

    return False, "", meta
