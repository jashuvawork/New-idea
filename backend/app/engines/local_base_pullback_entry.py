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


def _armed_base_launch_confirmed(candidate: Any, snap: Optional[SymbolSnapshot]) -> bool:
    alert = _alert_dict(candidate)
    if alert.get("ictArmedBaseLaunch"):
        return True
    pre = getattr(candidate, "pretrade_meta", None) or {}
    rank = pre.get("causalRanking") if isinstance(pre, dict) else {}
    if isinstance(rank, dict) and rank.get("ictArmedBaseLaunch"):
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
    return bool(getattr(ict, "armed_base_launch", False))


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
    event = getattr(candidate, "explosion_event", None)
    settings = get_settings()
    if bool(getattr(settings, "new_session_base_identify_enabled", False)):
        from app.engines.new_session_base import resolve_effective_base_premium_inr

        sym = str(getattr(candidate, "symbol", "") or alert.get("symbol") or "")
        strike = float(getattr(candidate, "strike", 0) or alert.get("strike") or 0)
        side = getattr(candidate, "side", None) or alert.get("side")
        prem = float(getattr(candidate, "premium", 0) or alert.get("premium") or 0)
        v3 = float(getattr(event, "velocity_3s", 0) or alert.get("velocity3s") or 0)
        fallback = 0.0
        for key in ("ictBasePremium", "localBaseBasePremium", "basePremium"):
            try:
                v = float(alert.get(key) or 0)
                if v > 0:
                    fallback = v
                    break
            except (TypeError, ValueError):
                pass
        eff, base_meta = resolve_effective_base_premium_inr(
            alert,
            symbol=sym,
            strike=strike,
            side=side,
            premium=prem,
            velocity_3s=v3,
            fallback=fallback,
            snap=snap,
            settings=settings,
        )
        if base_meta.get("indexBaseIctFallbackRejected"):
            return 0.0
        if eff > 0:
            return eff
        if base_meta.get("indexBaseFormationBlocked") and snap is not None:
            return 0.0
    sym = str(getattr(candidate, "symbol", "") or alert.get("symbol") or "")
    side = getattr(candidate, "side", None) or alert.get("side")
    for key in ("ictBasePremium", "localBaseBasePremium", "basePremium"):
        try:
            v = float(alert.get(key) or 0)
            if v > 0:
                if key == "ictBasePremium" and not _ict_base_participation_ok(
                    sym, side, snap, settings=settings,
                ):
                    return 0.0
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
        if v > 0 and not _ict_base_participation_ok(sym, side, snap, settings=settings):
            return 0.0
        return v if v > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _ict_base_participation_ok(
    sym: str,
    side: Any,
    snap: Optional[SymbolSnapshot],
    *,
    settings: Any,
) -> bool:
    if snap is None or not sym:
        return True
    if not bool(getattr(settings, "ict_armed_base_require_index_participation", True)):
        return True
    side_u = getattr(side, "value", None) or str(side or "").upper()
    if side_u not in ("CALL", "PUT"):
        return True
    from app.models.schemas import Side
    from app.engines.new_session_base import index_participation_allows_base_side

    side_v = Side.CALL if side_u == "CALL" else Side.PUT
    allowed, _reason, _meta = index_participation_allows_base_side(
        sym, side_v, snap, state=None, settings=settings, scope="ict",
    )
    return bool(allowed)


def _session_trough_premium(
    candidate: Any,
    snap: Optional[SymbolSnapshot],
) -> float:
    alert = _alert_dict(candidate)
    for key in ("sessionLowPremium", "sessionTroughPremium"):
        try:
            v = float(alert.get(key) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    if snap is None:
        return 0.0
    event = getattr(candidate, "explosion_event", None)
    if event is None:
        return 0.0
    try:
        from app.engines.explosion_detector import get_session_low_premium

        return float(
            get_session_low_premium(
                str(getattr(event, "symbol", "") or ""),
                float(getattr(event, "strike", 0) or 0),
                getattr(event, "side", None),
            )
            or 0
        )
    except Exception:
        return 0.0


def _stale_base_vs_session_trough(
    candidate: Any,
    snap: Optional[SymbolSnapshot],
    base: float,
    *,
    settings: Any,
    meta: dict[str, Any],
) -> bool:
    stale_gap = float(
        getattr(settings, "local_base_pullback_stale_trough_gap_pct", 15.0) or 15.0
    )
    sess_low = _session_trough_premium(candidate, snap)
    if sess_low <= 0 or base <= 0:
        return False
    gap_pct = (base - sess_low) / sess_low * 100.0
    stale = gap_pct >= stale_gap - 1e-6
    if stale:
        meta["armedBaseStaleVsSessionTrough"] = round(gap_pct, 1)
    return stale


def _elevated_pad_chase_cap_blocked(
    candidate: Any,
    metrics: dict[str, float],
    alert: dict[str, Any],
    *,
    settings: Any,
    meta: dict[str, Any],
) -> tuple[bool, str]:
    pad_thr = float(
        getattr(
            settings,
            "local_base_pullback_chase_cap_require_pullback_above_pad_pct",
            8.0,
        )
        or 8.0
    )
    try:
        pad = float(
            alert.get("localBaseMovePct")
            or alert.get("offLowMovePct")
            or alert.get("offHighMovePct")
            or 0
        )
    except (TypeError, ValueError):
        pad = 0.0
    if pad <= pad_thr + 1e-6:
        return False, "ok"
    min_dd = float(
        getattr(settings, "local_base_pullback_min_drawdown_from_high_pct", 3.0) or 3.0
    )
    dd = float(metrics.get("drawdownFromHighPct") or 0)
    if dd <= -min_dd + 1e-6:
        return False, "ok"
    meta["chaseCapElevatedPadPct"] = round(pad, 2)
    meta["chaseCapDrawdownFromHighPct"] = round(dd, 2)
    return True, "local_base_chase_cap_elevated_pad_no_pullback"


def _chase_cap_preflight_blocks_entry(
    candidate: Any,
    snap: Optional[SymbolSnapshot],
    *,
    premium_chart: Optional[PremiumChart] = None,
    settings: Any,
    meta: dict[str, Any],
) -> tuple[bool, str]:
    """Same structural vetoes as armed-launch waiver — applied before within_chase_cap pass."""
    if bool(
        getattr(settings, "local_base_pullback_armed_launch_stale_trough_blocks_waiver", True)
    ):
        base = _base_premium_inr(candidate, snap)
        if _stale_base_vs_session_trough(candidate, snap, base, settings=settings, meta=meta):
            return True, "local_base_pullback_wait"

    if bool(getattr(settings, "local_base_pullback_armed_launch_respect_rip_fall", True)):
        event = getattr(candidate, "explosion_event", None)
        if event is not None:
            from app.engines.explosion_entry_guards import (
                explosion_session_rip_fall_entry_blocked,
            )

            metrics = _chase_metrics(candidate, premium_chart=premium_chart)
            rip_block, rip_reason, rip_meta = explosion_session_rip_fall_entry_blocked(
                event,
                settings=settings,
                momentum5_pct=float(metrics.get("premiumMomentum5Pct") or 0),
                snap=snap,
            )
            if rip_block:
                meta.update(rip_meta)
                return True, rip_reason

    if bool(getattr(settings, "local_base_pullback_block_mid_pad_at_session_extreme", True)):
        alert = _alert_dict(candidate)
        from app.engines.index_extreme_launch_block import session_extreme_mid_pad_chase_blocked

        chase_block, chase_reason, chase_meta = session_extreme_mid_pad_chase_blocked(
            getattr(candidate, "side", None), snap, alert=alert, settings=settings,
        )
        if chase_block:
            meta.update(chase_meta)
            return True, chase_reason

    metrics = _chase_metrics(candidate, premium_chart=premium_chart)
    alert = _alert_dict(candidate)
    elev_block, elev_reason = _elevated_pad_chase_cap_blocked(
        candidate, metrics, alert, settings=settings, meta=meta,
    )
    if elev_block:
        return True, elev_reason

    return False, "ok"


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

    if _armed_base_launch_confirmed(candidate, snap):
        armed_base = _base_premium_inr(candidate, snap)
        stale = False
        if bool(
            getattr(
                settings,
                "local_base_pullback_armed_launch_stale_trough_blocks_waiver",
                True,
            )
        ):
            stale = _stale_base_vs_session_trough(
                candidate, snap, armed_base, settings=settings, meta=meta,
            )

        if not stale and bool(
            getattr(settings, "local_base_pullback_armed_launch_respect_rip_fall", True)
        ):
            event = getattr(candidate, "explosion_event", None)
            if event is not None:
                from app.engines.explosion_entry_guards import (
                    explosion_session_rip_fall_entry_blocked,
                )

                metrics = _chase_metrics(candidate, premium_chart=premium_chart)
                rip_block, rip_reason, rip_meta = explosion_session_rip_fall_entry_blocked(
                    event,
                    settings=settings,
                    momentum5_pct=float(metrics.get("premiumMomentum5Pct") or 0),
                    snap=snap,
                )
                if rip_block:
                    meta.update(rip_meta)
                    return True, rip_reason, meta

        if not stale and bool(
            getattr(settings, "local_base_pullback_block_mid_pad_at_session_extreme", True)
        ):
            alert = _alert_dict(candidate)
            from app.engines.index_extreme_launch_block import session_extreme_mid_pad_chase_blocked

            chase_block, chase_reason, chase_meta = session_extreme_mid_pad_chase_blocked(
                getattr(candidate, "side", None), snap, alert=alert, settings=settings,
            )
            if chase_block:
                meta.update(chase_meta)
                return True, chase_reason, meta

        if not stale:
            meta["localBasePullbackFill"] = "armed_base_launch_waiver"
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
    if signal <= 0:
        return False, "ok", meta
    if base <= 0:
        if _ict_base_armed(candidate, snap) and snap is not None:
            return True, "local_base_pullback_participation_base", meta
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
        cap_block, cap_reason = _chase_cap_preflight_blocks_entry(
            candidate, snap, premium_chart=premium_chart, settings=settings, meta=meta,
        )
        if cap_block:
            return True, cap_reason, meta
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