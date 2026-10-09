"""Oct 1 / Sep917 live pad entry — block session-high chase under paper parity.

Oct 7 NIFTY 22700 CE: local base ~7% but fill at ₹158 with drawdownFromHighPct≈0
(session-high chase). Paper Oct 1 takes the pad (~₹122), not the rip top.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import SymbolSnapshot
from app.engines.live_paper_parity import entry_gates_match_paper

_OCT1_PAD_CHASE_BLOCK_REASONS = frozenset({
    "live_oct1_chase_at_session_high",
    "live_oct1_chase_session_range_high",
    "live_oct1_put_chase_at_session_low",
})


def oct1_pad_entry_guard_active(settings: Any = None) -> bool:
    """
    Oct 1 pad location guard — paper parity and/or live under Frozen October.

    Oct 7 live had parity flags off while still on the Oct book; guard must run
    whenever frozen Oct + live execution, not only when live_paper_parity is set.
    """
    settings = settings or get_settings()
    pad_on = getattr(settings, "live_paper_parity_pad_entry_guard_enabled", True)
    if not (pad_on if isinstance(pad_on, bool) else True):
        return False
    return entry_gates_match_paper(settings)


def apply_oct1_pad_timing_block(
    timing: dict[str, Any],
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """
    When timing says GOOD/OK but premium is at session high on a near-base shape,
    hard-block as CHASE (Oct 7 NIFTY CE @ ₹158).
    """
    settings = settings or get_settings()
    if not oct1_pad_entry_guard_active(settings):
        return timing
    if str(timing.get("action") or "") == "block":
        return timing
    blocked, reason, _meta = live_oct1_pad_entry_blocked(
        candidate, snap, settings=settings,
    )
    if not blocked:
        return timing
    if reason in _OCT1_PAD_CHASE_BLOCK_REASONS or (
        reason and str(reason).startswith("live_oct1_sep09")
    ):
        reasons = list(timing.get("reasons") or [])
        reasons.append(reason)
        return {
            **timing,
            "assessment": "CHASE",
            "action": "block",
            "oct1PadTimingBlock": True,
            "reasons": reasons,
        }
    return timing


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
    """Order boundary — Oct 1 pad location (paper parity or live Frozen October)."""
    settings = settings or get_settings()
    if not oct1_pad_entry_guard_active(settings):
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
    Require Sep917 near-base shape AND pad location (not session-high chase).
    CE/PE symmetric. Active under paper parity or live + Frozen October profile.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"liveOct1PadGuard": True}
    if not oct1_pad_entry_guard_active(settings):
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

    side_u = str(
        getattr(getattr(candidate, "side", None), "value", None)
        or getattr(candidate, "side", "")
        or evidence.get("side")
        or ""
    ).upper()
    rr = ""
    if isinstance(pre, dict):
        rr = str(pre.get("firstLiftReadinessReason") or "")

    pos, dd = _session_range_metrics(candidate)
    evidence_pos = {
        **evidence,
        "sessionRangePosition": pos,
        "drawdownFromHighPct": dd,
        "side": side_u or evidence.get("side"),
    }
    meta["sessionRangePosition"] = round(pos, 3)
    meta["drawdownFromHighPct"] = round(dd, 2)

    from app.engines.live_paper_parity import oct_paper_first_lift_small_lift_context
    from app.engines.oct1_pad_location import (
        oct1_pad_location_waived,
        oct1_premium_location_chase_blocked,
    )

    if oct_paper_first_lift_small_lift_context(
        evidence_pos,
        settings=settings,
        readiness_reason=rr,
    ):
        meta["octFirstLiftPadWaive"] = True
        return False, "", meta

    waived, waive_tag = oct1_pad_location_waived(
        side_u,
        evidence_pos,
        settings=settings,
        readiness_reason=rr,
    )
    if waived:
        meta_key = {
            "oct_first_lift_pad_waive": "octFirstLiftPadWaive",
            "oct_open_call_rip_pad_waive": "octOpenCallRipPadWaive",
            "oct_open_put_slide_pad_waive": "octOpenPutSlidePadWaive",
        }.get(waive_tag, "octPadLocationWaive")
        meta[meta_key] = True
        return False, "", meta

    blocked, chase_reason = oct1_premium_location_chase_blocked(
        side_u,
        pos,
        dd,
        evidence_pos,
        settings=settings,
        readiness_reason=rr,
    )
    if blocked:
        return True, chase_reason, meta

    from app.engines.sep09_intent_guards import sep09_near_peak_after_extended_rip

    near_peak, np_reason = sep09_near_peak_after_extended_rip(
        evidence,
        premium=float(
            getattr(candidate, "premium", 0) or evidence.get("premium") or 0
        ),
        symbol=str(getattr(candidate, "symbol", "") or evidence.get("symbol") or ""),
        strike=float(getattr(candidate, "strike", 0) or evidence.get("strike") or 0),
        side=side_u,
        alert=evidence,
        settings=settings,
    )
    if near_peak:
        meta["sep09NearPeak"] = np_reason
        return True, np_reason or "live_oct1_sep09_near_peak_chase", meta

    return False, "", meta
