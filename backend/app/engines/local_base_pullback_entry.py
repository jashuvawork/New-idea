"""Defer explosion fills when signal premium chases too far above ICT local base.

Nov 17 SENSEX live: armed-base CE legs filled at session highs (drawdown≈0) while
``localBaseBasePremium`` sat 20–115 pts lower — same exits at base premium would
have ~3× session PnL. Wait for a shallow pullback (or better price) before entry.
Symmetric CE/PE (premium chase, not index direction).
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import PremiumChart, SymbolSnapshot


def _alert_dict(candidate: Any) -> dict[str, Any]:
    alert = getattr(candidate, "alert", None)
    return dict(alert) if isinstance(alert, dict) else {}


def _ict_base_armed(candidate: Any, snap: Optional[SymbolSnapshot]) -> bool:
    alert = _alert_dict(candidate)
    if alert.get("ictBaseArmed") or alert.get("ictArmedBaseLaunch"):
        return True
    pre = getattr(candidate, "pretrade_meta", None) or {}
    rank = pre.get("causalRanking") if isinstance(pre, dict) else {}
    if isinstance(rank, dict) and (
        rank.get("ictBaseArmed") or rank.get("ictArmedBaseLaunch")
    ):
        return True
    event = getattr(candidate, "explosion_event", None)
    if snap is None or event is None:
        return False
    from app.engines.ict_breakout_monitor import (
        analyze_explosion_event_ict,
        merge_alert_ict_stamps,
    )

    ict = analyze_explosion_event_ict(event, snap)
    ict = merge_alert_ict_stamps(ict, alert or None)
    return bool(getattr(ict, "base_armed", False) or getattr(ict, "armed_base_launch", False))


def _base_premium_inr(candidate: Any, snap: Optional[SymbolSnapshot]) -> float:
    alert = _alert_dict(candidate)
    for key in ("ictBasePremium", "localBaseBasePremium", "basePremium"):
        try:
            v = float(alert.get(key) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    pre = getattr(candidate, "pretrade_meta", None) or {}
    rank = pre.get("causalRanking") if isinstance(pre, dict) else {}
    if isinstance(rank, dict):
        for key in ("ictBasePremium", "localBaseBasePremium", "basePremium"):
            try:
                v = float(rank.get(key) or 0)
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
    event = getattr(candidate, "explosion_event", None)
    if snap is None or event is None:
        return 0.0
    from app.engines.ict_breakout_monitor import (
        analyze_explosion_event_ict,
        merge_alert_ict_stamps,
    )

    ict = analyze_explosion_event_ict(event, snap)
    ict = merge_alert_ict_stamps(ict, alert or None)
    try:
        v = float(getattr(ict, "base_premium", 0) or 0)
        return v if v > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _chase_metrics(
    candidate: Any,
    *,
    premium_chart: Optional[PremiumChart] = None,
) -> dict[str, float]:
    meta = getattr(candidate, "liveEntryScoreMeta", None) or {}
    out: dict[str, float] = {}
    if isinstance(meta, dict):
        for k in ("drawdownFromHighPct", "premiumMomentum5Pct"):
            try:
                out[k] = float(meta.get(k) or 0)
            except (TypeError, ValueError):
                out[k] = 0.0
    if premium_chart is not None:
        out["premiumMomentum5Pct"] = float(premium_chart.momentum5Pct or 0)
        out["drawdownFromHighPct"] = float(
            getattr(premium_chart, "drawdownFromHighPct", 0) or 0
        )
    return out


def local_base_pullback_blocks_entry(
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
    *,
    premium_chart: Optional[PremiumChart] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Block when armed-base explosion signals fire but premium is still chasing above
    the stamped local base by more than configured INR / %.

    Allows entry once price pulls back from session high (drawdown from high) OR
    signal premium sits within the chase cap of base.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not bool(getattr(settings, "local_base_pullback_entry_enabled", True)):
        return False, "ok", meta
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "ok", meta
    tier = str(getattr(candidate, "tier", "") or "").upper()
    allow_tiers = {
        t.strip().upper()
        for t in str(
            getattr(settings, "local_base_pullback_tiers_csv", "ELITE,EXPLODING")
            or "ELITE,EXPLODING"
        ).split(",")
        if t.strip()
    }
    if tier and tier not in allow_tiers:
        return False, "ok", meta

    if not _ict_base_armed(candidate, snap):
        return False, "ok", meta

    try:
        signal = float(getattr(candidate, "premium", 0) or 0)
    except (TypeError, ValueError):
        signal = 0.0
    if signal <= 0:
        alert = _alert_dict(candidate)
        try:
            signal = float(alert.get("premium") or alert.get("lastPremium") or 0)
        except (TypeError, ValueError):
            signal = 0.0
    base = _base_premium_inr(candidate, snap)
    if base <= 0 or signal <= 0:
        return False, "ok", meta

    chase_inr = signal - base
    chase_pct = 100.0 * chase_inr / base
    max_inr = float(
        getattr(settings, "local_base_pullback_max_chase_inr", 20.0) or 20.0
    )
    max_pct = float(
        getattr(settings, "local_base_pullback_max_chase_pct", 7.0) or 7.0
    )
    meta.update(
        {
            "localBasePullback": True,
            "localBaseBasePremium": round(base, 2),
            "signalPremium": round(signal, 2),
            "chaseAboveBaseInr": round(chase_inr, 2),
            "chaseAboveBasePct": round(chase_pct, 2),
        }
    )

    if chase_inr <= max_inr + 1e-6 and chase_pct <= max_pct + 1e-6:
        meta["localBasePullbackFill"] = "within_chase_cap"
        return False, "ok", meta

    metrics = _chase_metrics(candidate, premium_chart=premium_chart)
    meta["premiumChaseMetrics"] = metrics
    min_dd = float(
        getattr(settings, "local_base_pullback_min_drawdown_from_high_pct", 3.0) or 3.0
    )
    dd = float(metrics.get("drawdownFromHighPct") or 0)
    if dd <= -min_dd:
        meta["localBasePullbackFill"] = "pullback_from_high"
        return False, "ok", meta

    return True, "local_base_pullback_wait", meta