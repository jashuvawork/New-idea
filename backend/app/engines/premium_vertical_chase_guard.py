"""Hard block: buying option premium at session high during a vertical 5m rip (chase).

Sep 30 SENSEX PUT 72500 entered @ ₹282 with drawdownFromHighPct=0 and mom5≈+92%
while true base was ~₹200 earlier — soft live-entry penalties did not block (min live 46).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import PremiumChart, SymbolSnapshot


def premium_vertical_chase_guard_active(settings: Any = None) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "premium_vertical_chase_block_enabled", True)):
        return False
    if not bool(getattr(settings, "premium_vertical_chase_legacy_profile_only", True)):
        return True
    from app.engines.sep917_legacy_profile import sep917_legacy_profile_active

    if not sep917_legacy_profile_active(settings):
        return False
    return bool(getattr(settings, "symmetric_best_trade_capture_enabled", True))


def _candidate_evidence(candidate: Any) -> dict[str, Any]:
    alert = getattr(candidate, "alert", None)
    if not isinstance(alert, dict):
        alert = {}
    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}
    if not isinstance(ranking, dict):
        ranking = {}
    nested = ranking.get("evidence") if isinstance(ranking.get("evidence"), dict) else {}
    merged = {**alert, **nested, **ranking}
    tier = getattr(candidate, "tier", None)
    if tier and not merged.get("tier"):
        merged["tier"] = tier
    side = getattr(candidate, "side", None)
    if side is not None and not merged.get("side"):
        merged["side"] = getattr(side, "value", side)
    sym = getattr(candidate, "symbol", None)
    if sym and not merged.get("symbol"):
        merged["symbol"] = sym
    strike = getattr(candidate, "strike", None)
    if strike and not merged.get("strike"):
        merged["strike"] = strike
    return merged


def _read_premium_chase_metrics(
    candidate: Any,
    *,
    premium_chart: Optional[PremiumChart] = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    live_meta = getattr(candidate, "liveEntryScoreMeta", None) or {}
    if isinstance(live_meta, dict):
        meta.update(
            {
                k: live_meta.get(k)
                for k in (
                    "premiumMomentum5Pct",
                    "drawdownFromHighPct",
                    "premiumDirection",
                    "sessionRangePosition",
                )
                if k in live_meta
            }
        )

    if premium_chart is not None:
        meta["premiumMomentum5Pct"] = float(premium_chart.momentum5Pct or 0)
        meta["drawdownFromHighPct"] = float(
            getattr(premium_chart, "drawdownFromHighPct", 0) or 0
        )
        meta["premiumDirection"] = str(premium_chart.direction or "")

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
        if peak > low > 0 and prem > 0 and "sessionRangePosition" not in meta:
            meta["sessionRangePosition"] = round((prem - low) / (peak - low), 3)

    return meta


def _at_structural_base_bypass(
    candidate: Any,
    snap: Optional[SymbolSnapshot],
    *,
    settings: Any = None,
) -> tuple[bool, str]:
    settings = settings or get_settings()
    evidence = _candidate_evidence(candidate)
    alert = getattr(candidate, "alert", None) if isinstance(getattr(candidate, "alert", None), dict) else {}
    from app.engines.best_trade_policy import symmetric_best_trade_at_base_capture

    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}
    at_base, base_reason = symmetric_best_trade_at_base_capture(
        evidence, alert, ranking=ranking if isinstance(ranking, dict) else None, settings=settings,
    )
    if at_base:
        return True, base_reason

    if snap is not None and getattr(candidate, "mode", "") == "explosion":
        from app.engines.ict_breakout_monitor import (
            analyze_explosion_event_ict,
            first_lift_entry_ready,
            merge_alert_ict_stamps,
        )

        event = getattr(candidate, "explosion_event", None)
        alert = getattr(candidate, "alert", None) if isinstance(getattr(candidate, "alert", None), dict) else None
        ict = analyze_explosion_event_ict(event, snap) if event is not None else None
        ict = merge_alert_ict_stamps(ict, alert)
        if first_lift_entry_ready(snap=snap, event=event, ict=ict, alert=alert):
            return True, "first_lift_entry_ready"

    return False, ""


def premium_vertical_chase_blocks_entry(
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
    *,
    premium_chart: Optional[PremiumChart] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Block chase fills: premium at/near session high + hot 5m rip, not at structural base.
    Symmetric for CALL and PUT.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not premium_vertical_chase_guard_active(settings):
        return False, "ok", meta

    metrics = _read_premium_chase_metrics(candidate, premium_chart=premium_chart)
    meta["premiumChaseMetrics"] = metrics

    dd = float(metrics.get("drawdownFromHighPct") or 0)
    mom5 = float(metrics.get("premiumMomentum5Pct") or 0)
    range_pos = float(metrics.get("sessionRangePosition") or 0)

    max_dd = float(
        getattr(settings, "premium_vertical_chase_max_drawdown_from_high_pct", 8.0) or 8.0
    )
    min_mom = float(
        getattr(settings, "premium_vertical_chase_min_momentum5_pct", 35.0) or 35.0
    )
    min_range = float(
        getattr(settings, "premium_vertical_chase_min_session_range_position", 0.78) or 0.78
    )

    at_high = dd >= -max_dd
    hot_rip = abs(mom5) >= min_mom
    high_in_range = range_pos <= 0 or range_pos + 1e-6 >= min_range

    if not (at_high and hot_rip and high_in_range):
        return False, "ok", meta

    bypass, bypass_reason = _at_structural_base_bypass(candidate, snap, settings=settings)
    if bypass:
        meta["premiumChaseBypass"] = bypass_reason
        return False, "ok", meta

    if bool(getattr(settings, "premium_vertical_chase_allow_controlled_waiver", True)):
        from app.engines.controlled_explosive_chase import controlled_explosive_chase_allowed

        pretrade = getattr(candidate, "pretrade_meta", None) or {}
        ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}
        assessment = ranking if isinstance(ranking, dict) else {}
        ctrl_ok, ctrl_reason, ctrl_meta = controlled_explosive_chase_allowed(
            candidate, snap, assessment=assessment, settings=settings,
        )
        meta.update(ctrl_meta)
        if ctrl_ok:
            meta["premiumChaseBypass"] = "premium_vertical_chase_controlled_rip_waiver"
            meta["controlledChaseWaiverReason"] = ctrl_reason
            return False, "ok", meta

    meta["premiumChaseBlock"] = {
        "drawdownFromHighPct": dd,
        "premiumMomentum5Pct": mom5,
        "sessionRangePosition": range_pos,
    }
    return True, "premium_vertical_chase_at_high", meta
