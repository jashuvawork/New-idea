"""One final entry validation at the order wire — fresh index snapshot + live tape context.

Runs only the gates that can go stale between early ``validate_candidate`` and
``place_entry_order``: wire hydration from execution chart, participation veto,
session participation / MTF intent, and live index-leg alignment.
Premium tape checks stay in ``execution_order_preflight_blocked`` and execution chart.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, ChartAnalysis, SpotChart, SymbolSnapshot


def _sync_candidate_snap(
    candidate: Any,
    snapshots: Optional[dict[str, SymbolSnapshot]],
) -> None:
    if not snapshots:
        return
    sym = str(getattr(candidate, "symbol", "") or "").upper()
    fresh = snapshots.get(sym)
    if fresh is not None:
        try:
            candidate.snap = fresh
        except Exception:
            pass


def hydrate_wire_snapshot_from_chart(
    snap: SymbolSnapshot,
    chart_meta: Optional[dict[str, Any]],
    *,
    settings: Any = None,
) -> SymbolSnapshot:
    """Merge execution-chart fetch into the wire snapshot (spot, MTF, reconciled direction)."""
    settings = settings or get_settings()
    if not chart_meta or not bool(getattr(settings, "order_time_entry_pass_wire_hydration", True)):
        return snap
    if str(chart_meta.get("source") or "") == "snapshot_fallback":
        return snap

    updates: dict[str, Any] = {}
    live_spot = float(chart_meta.get("spot") or 0)
    if live_spot > 0:
        updates["spot"] = live_spot

    full = chart_meta.get("indexChartFull")
    if full:
        index_chart = SpotChart(**full) if isinstance(full, dict) else full
        breadth = str(getattr(snap.breadth, "bias", None) or "NEUTRAL").upper() if snap.breadth else "NEUTRAL"
        from_open = float(getattr(snap, "dayFromOpenPct", 0) or 0)
        if snap.chartAnalysis:
            from app.engines.spot_direction import reconcile_spot_chart_with_mtf

            index_chart = reconcile_spot_chart_with_mtf(
                index_chart,
                snap.chartAnalysis,
                breadth_bias=breadth,
                from_open_pct=from_open,
            )
        updates["spotChart"] = index_chart

    index_mtf = chart_meta.get("indexMtf") if isinstance(chart_meta.get("indexMtf"), dict) else {}
    tfs = index_mtf.get("timeframes") if isinstance(index_mtf, dict) else None
    if isinstance(tfs, dict) and tfs:
        consensus = str(index_mtf.get("consensus") or "").upper()
        if snap.chartAnalysis:
            ca = snap.chartAnalysis.model_copy(deep=True)
            merged = dict(ca.timeframes or {})
            for label, data in tfs.items():
                if isinstance(data, dict):
                    merged[str(label)] = data
            ca.timeframes = merged
            if consensus in ("BULLISH", "BEARISH", "NEUTRAL"):
                ca.consensus = consensus
            updates["chartAnalysis"] = ca
        else:
            updates["chartAnalysis"] = ChartAnalysis(
                consensus=consensus or "NEUTRAL",
                timeframes={str(k): v for k, v in tfs.items() if isinstance(v, dict)},
            )

    qctx = chart_meta.get("quoteContext") if isinstance(chart_meta.get("quoteContext"), dict) else {}
    day_high = float(qctx.get("dayHigh") or 0)
    day_low = float(qctx.get("dayLow") or 0)
    day_open = float(qctx.get("dayOpen") or day_low or 0)
    if day_high > 0 and day_low > 0:
        ca = updates.get("chartAnalysis") or snap.chartAnalysis
        if ca is not None:
            ca = ca.model_copy(deep=True)
            inst = dict(getattr(ca, "institutional", None) or {})
            inst.update(
                dayHigh=day_high,
                dayLow=day_low,
                sessionHigh=day_high,
                sessionLow=day_low,
            )
            if day_open > 0:
                inst["dayOpen"] = day_open
            ca.institutional = inst
            updates["chartAnalysis"] = ca

    if not updates:
        return snap
    return snap.model_copy(update=updates)


def _institutional_day_range_missing(snap: SymbolSnapshot) -> bool:
    ca = snap.chartAnalysis
    inst = getattr(ca, "institutional", None) if ca is not None else None
    if not isinstance(inst, dict):
        return True
    hi = float(inst.get("dayHigh") or 0)
    lo = float(inst.get("dayLow") or 0)
    return hi <= 0 or lo <= 0 or hi <= lo


def hydrate_wire_snapshot_from_preflight(
    snap: SymbolSnapshot,
    preflight_meta: Optional[dict[str, Any]],
) -> SymbolSnapshot:
    """Stamp day high/low from execution preflight when the wire snap still lacks broker OHLC."""
    if not preflight_meta or not _institutional_day_range_missing(snap):
        return snap
    iel = preflight_meta.get("indexExtremeLaunch")
    if not isinstance(iel, dict):
        return snap
    hi = float(iel.get("sessionHigh") or 0)
    lo = float(iel.get("sessionLow") or 0)
    if hi <= 0 or lo <= 0 or hi <= lo:
        return snap
    ca = snap.chartAnalysis.model_copy(deep=True) if snap.chartAnalysis else ChartAnalysis()
    inst = dict(getattr(ca, "institutional", None) or {})
    inst.update(
        dayHigh=round(hi, 2),
        dayLow=round(lo, 2),
        sessionHigh=round(hi, 2),
        sessionLow=round(lo, 2),
    )
    if float(inst.get("dayOpen") or 0) <= 0:
        inst["dayOpen"] = round(lo, 2)
    ca.institutional = inst
    live_spot = float(iel.get("spot") or 0)
    updates: dict[str, Any] = {"chartAnalysis": ca}
    if live_spot > 0:
        updates["spot"] = live_spot
    return snap.model_copy(update=updates)


def _participation_veto_margin(settings: Any) -> float:
    return float(getattr(settings, "order_time_participation_veto_margin_pts", 15.0) or 15.0)


def participation_veto_blocks_entry(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Block counter-participation at mid-pad when slide/rally points + chart/breadth agree.
    CE/PE symmetric; near-base and trend-breakout paths stay open.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not bool(getattr(settings, "order_time_entry_pass_participation_veto", True)):
        return False, "ok", meta

    from app.engines.session_intent_authority import (
        _local_pad_from_candidate,
        _side_counter_to_participation,
        resolve_session_intent,
    )

    side_u = str(getattr(getattr(candidate, "side", None), "value", candidate.side) or "").upper()
    if side_u not in ("CALL", "PUT"):
        return False, "ok", meta

    sym = str(getattr(candidate, "symbol", "") or "").upper()
    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None:
        return False, "ok", meta

    near_cap = float(
        getattr(settings, "session_intent_counter_near_base_max_pct", 8.0) or 8.0
    )
    local_pad = _local_pad_from_candidate(candidate)
    meta["localPadPct"] = round(local_pad, 2)
    if local_pad <= near_cap + 1e-6:
        return False, "ok", meta

    from app.engines.index_rally_side_flip import _min_move_pts, index_rally_metrics
    from app.engines.index_tick_helpers import index_trend_breakout

    if index_trend_breakout(sym, side_u, snap, settings=settings).get("breakout"):
        meta["trendBreakout"] = True
        return False, "ok", meta

    min_pts = _min_move_pts(sym, settings)
    margin = _participation_veto_margin(settings)
    metrics = index_rally_metrics(sym, snap, settings=settings)
    meta["indexRallyMetrics"] = metrics
    slide = float(metrics.get("slidePoints") or 0)
    rally = float(metrics.get("rallyPoints") or 0)

    br = snap.breadth
    bb = str(getattr(br, "bias", None) or "NEUTRAL").upper() if br else "NEUTRAL"
    chart = str(getattr(snap.spotChart, "direction", None) or "NEUTRAL").upper()
    breadth_aligned = bool(getattr(br, "aligned", False)) if br else False

    if side_u == "CALL":
        if (
            slide >= min_pts
            and slide > rally + margin
            and (bb == "BEARISH" or chart == "BEARISH")
            and (breadth_aligned or slide > rally + margin * 2)
        ):
            return True, "participation_veto_counter_ce_on_slide", meta
    elif side_u == "PUT":
        if (
            rally >= min_pts
            and rally > slide + margin
            and (bb == "BULLISH" or chart == "BULLISH")
            and (breadth_aligned or rally > slide + margin * 2)
        ):
            return True, "participation_veto_counter_pe_on_rally", meta

    intent = resolve_session_intent(sym, snap, state, settings=settings)
    meta["sessionIntent"] = intent
    if intent.get("enabled") and _side_counter_to_participation(side_u, intent):
        mtf_side = (intent.get("mtf") or {}).get(side_u) or {}
        htf_oppose = int(mtf_side.get("htfOpposeCount") or 0)
        if intent.get("confidence") == "HIGH" and local_pad > near_cap and htf_oppose >= 1:
            return True, "participation_veto_session_intent_htf", meta

    from app.engines.index_session_dominant_trend import (
        index_session_dominant_trend,
        side_aligns_with_dominant_trend,
    )

    dom, dom_meta = index_session_dominant_trend(sym, snap, state, settings=settings)
    meta["indexDominantTrend"] = dom
    meta.update(dom_meta)
    if dom not in ("NEUTRAL", "") and not side_aligns_with_dominant_trend(side_u, dom):
        return True, "participation_veto_dominant_leg", meta

    return False, "ok", meta


def order_time_entry_blocked(
    candidate: Any,
    state: AutoTraderState,
    snapshots: Optional[dict[str, SymbolSnapshot]],
    *,
    premium_chart: Any = None,
    chart_meta: Optional[dict[str, Any]] = None,
    preflight_meta: Optional[dict[str, Any]] = None,
    is_live: bool = False,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Last structural pass before broker/paper entry.

    Returns (blocked, reason, metadata) for entryContext / funnel.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"orderTimeEntryPass": True, "checks": {}}
    if not bool(getattr(settings, "order_time_entry_pass_enabled", True)):
        return False, "ok", meta

    sym = str(getattr(candidate, "symbol", "") or "").upper()
    snapshots = dict(snapshots or {})
    if sym and sym not in snapshots:
        wire = getattr(candidate, "snap", None)
        if wire is not None:
            snapshots[sym] = wire
    if sym and chart_meta:
        hydrated = hydrate_wire_snapshot_from_chart(
            snapshots[sym], chart_meta, settings=settings,
        )
        if hydrated is not snapshots[sym]:
            snapshots[sym] = hydrated
            meta["checks"]["wireHydration"] = {
                "applied": True,
                "spot": round(float(hydrated.spot or 0), 2),
                "chartDirection": getattr(hydrated.spotChart, "direction", None),
            }
    if sym and preflight_meta:
        pref_hydrated = hydrate_wire_snapshot_from_preflight(
            snapshots[sym], preflight_meta,
        )
        if pref_hydrated is not snapshots[sym]:
            snapshots[sym] = pref_hydrated
            meta["checks"]["preflightSessionRange"] = {
                "applied": True,
                "indexExtremeLaunch": (
                    preflight_meta.get("indexExtremeLaunch")
                    if isinstance(preflight_meta.get("indexExtremeLaunch"), dict)
                    else None
                ),
            }

    if snapshots:
        _sync_candidate_snap(candidate, snapshots)

    if snapshots and bool(getattr(settings, "order_time_entry_pass_participation_veto", True)):
        pv_blocked, pv_reason, pv_meta = participation_veto_blocks_entry(
            candidate, state, snapshots, settings=settings,
        )
        meta["checks"]["participationVeto"] = {
            "blocked": pv_blocked,
            "reason": pv_reason,
            **(pv_meta if isinstance(pv_meta, dict) else {}),
        }
        if pv_blocked:
            return True, f"order_time_{pv_reason}", meta

    if bool(getattr(settings, "order_time_entry_pass_session_intent", True)):
        if snapshots:
            from app.engines.session_intent_authority import session_intent_blocks_entry

            si_blocked, si_reason, si_meta = session_intent_blocks_entry(
                candidate, state, snapshots, settings=settings,
            )
            meta["checks"]["sessionIntent"] = {
                "blocked": si_blocked,
                "reason": si_reason,
                **(si_meta if isinstance(si_meta, dict) else {}),
            }
            if si_blocked:
                return True, f"order_time_{si_reason}", meta

    if is_live and bool(
        getattr(settings, "order_time_entry_pass_live_index_leg", True)
    ):
        if snapshots:
            from app.engines.live_entry_integrity import live_index_leg_hard_blocks_entry

            leg_blocked, leg_reason, leg_meta = live_index_leg_hard_blocks_entry(
                candidate, state, snapshots, settings=settings,
            )
            meta["checks"]["liveIndexLeg"] = {
                "blocked": leg_blocked,
                "reason": leg_reason,
                **(leg_meta if isinstance(leg_meta, dict) else {}),
            }
            if leg_blocked:
                return True, f"order_time_{leg_reason}", meta

    if premium_chart is not None:
        meta["checks"]["premiumChartSynced"] = True
    if chart_meta:
        meta["checks"]["executionChartMerged"] = True

    return False, "ok", meta