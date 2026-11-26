"""Final tape re-check immediately before broker/paper entry orders.

Selection and preorder use radar fields that can be minutes stale. This gate runs once at
the order boundary with fresh snapshot alert + execution premium chart (no fade waivers).
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import PremiumChart, Side, SymbolSnapshot


def _side_val(side: Any) -> str:
    if isinstance(side, Side):
        return side.value
    return str(side or "").upper()


def _fresh_alert_for_contract(
    candidate: Any,
    snap: Optional[SymbolSnapshot],
) -> dict[str, Any]:
    alert = getattr(candidate, "alert", None)
    alert = alert if isinstance(alert, dict) else {}
    if snap is None:
        return alert
    sym = str(getattr(candidate, "symbol", "") or alert.get("symbol") or "").upper()
    side = _side_val(getattr(candidate, "side", None) or alert.get("side"))
    strike = float(getattr(candidate, "strike", 0) or alert.get("strike") or 0)
    for row in snap.explosionAlerts or []:
        if not isinstance(row, dict):
            continue
        if (
            str(row.get("symbol") or "").upper() == sym
            and str(row.get("side") or "").upper() == side
            and float(row.get("strike") or 0) == strike
        ):
            return row
    return alert


def _live_near_base_retest(alert: dict[str, Any], settings: Any) -> bool:
    pad = float(alert.get("localPadPct") or alert.get("padPct") or 0)
    sr = float(alert.get("sessionRangePosition") or 0)
    pad_max = float(
        getattr(settings, "execution_order_preflight_live_near_base_pad_max_pct", 5.0)
        or 5.0
    )
    range_max = float(
        getattr(settings, "execution_order_preflight_live_near_base_range_max", 0.35)
        or 0.35
    )
    return pad <= pad_max + 1e-6 and sr <= range_max + 1e-6


def _live_extended_chase_context(
    alert: dict[str, Any],
    settings: Any,
) -> tuple[bool, dict[str, Any]]:
    from app.engines.live_paper_parity import armed_trading_book_applies_entry_gates

    meta: dict[str, Any] = {}
    if not armed_trading_book_applies_entry_gates(settings):
        return False, meta
    if not bool(
        getattr(settings, "execution_order_preflight_live_extended_fade_enabled", True)
    ):
        return False, meta
    if _live_near_base_retest(alert, settings):
        return False, meta
    pad = float(alert.get("localPadPct") or alert.get("padPct") or 0)
    sr = float(alert.get("sessionRangePosition") or 0)
    pad_min = float(
        getattr(settings, "execution_order_preflight_live_extended_pad_pct_min", 8.0)
        or 8.0
    )
    sr_min = float(
        getattr(settings, "execution_order_preflight_live_extended_session_range_min", 0.85)
        or 0.85
    )
    extended = pad >= pad_min - 1e-6 or sr >= sr_min - 1e-6
    meta.update(
        localPadPct=round(pad, 2),
        sessionRangePosition=round(sr, 3),
        liveExtendedChase=extended,
    )
    return extended, meta


def _sync_live_event_premium(candidate: Any, premium_chart: Optional[PremiumChart]) -> None:
    ev = getattr(candidate, "explosion_event", None)
    if ev is None or premium_chart is None:
        return
    ltp = float(getattr(premium_chart, "lastPremium", 0) or 0)
    if ltp <= 0:
        return
    try:
        setattr(ev, "premium", ltp)
    except Exception:
        pass
    mom3 = float(getattr(premium_chart, "momentum3Pct", 0) or 0)
    mom5 = float(getattr(premium_chart, "momentum5Pct", 0) or 0)
    for attr, val in (("velocity_3s", mom3), ("velocity_9s", mom5)):
        try:
            setattr(ev, attr, val)
        except Exception:
            pass


def execution_order_preflight_blocked(
    candidate: Any,
    snap: Optional[SymbolSnapshot],
    *,
    premium_chart: Optional[PremiumChart] = None,
    premium_candles_1m: Optional[list] = None,
    chart_meta: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Last-line revalidation before place_entry_order / simulate_entry_order.

    Uses live execution premium chart when present; does not honor exec fade waivers.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"executionOrderPreflight": True}
    if not bool(getattr(settings, "execution_order_preflight_enabled", True)):
        return False, "ok", meta

    _sync_live_event_premium(candidate, premium_chart)
    alert = _fresh_alert_for_contract(candidate, snap)
    meta["freshAlertPremium"] = alert.get("premium")
    meta["freshAlertVelocity3s"] = alert.get("velocity3s")

    if premium_chart is not None:
        meta["premiumMomentum3Pct"] = float(premium_chart.momentum3Pct or 0)
        meta["premiumMomentum5Pct"] = float(premium_chart.momentum5Pct or 0)
        meta["premiumDirection"] = premium_chart.direction
        meta["drawdownFromHighPct"] = getattr(premium_chart, "drawdownFromHighPct", None)
        meta["postSpikeDump"] = getattr(premium_chart, "postSpikeDump", False)

        from app.engines.premium_spike_dump_guard import premium_chart_post_spike_dump

        if bool(getattr(settings, "execution_order_preflight_block_post_spike_chart", True)):
            if premium_chart_post_spike_dump(premium_chart):
                return True, "exec_preflight_post_spike_dump", meta

        if bool(getattr(settings, "execution_order_preflight_block_bearish_premium", True)):
            mom3 = float(premium_chart.momentum3Pct or 0)
            mom5 = float(premium_chart.momentum5Pct or 0)
            direction = str(premium_chart.direction or "").upper()
            dd = float(getattr(premium_chart, "drawdownFromHighPct", 0) or 0)
            min_dd = float(
                getattr(settings, "execution_order_preflight_min_drawdown_pct", 8.0) or 8.0
            )
            if (
                dd <= -min_dd
                and mom3 < 0
                and mom5 < 0
                and direction == "BEARISH"
            ):
                return True, "exec_preflight_bearish_premium_tape", meta

        if bool(
            getattr(settings, "execution_order_preflight_block_falling_momentum", True)
        ):
            mom3 = float(premium_chart.momentum3Pct or 0)
            mom5 = float(premium_chart.momentum5Pct or 0)
            if mom3 < 0 and mom5 < 0:
                return True, "exec_preflight_falling_premium_momentum", meta
            extended, ext_meta = _live_extended_chase_context(alert, settings)
            meta["liveExtendedChaseContext"] = ext_meta
            if extended and mom3 < 0:
                return True, "exec_preflight_live_extended_fade_mom3", meta
        side = _side_val(getattr(candidate, "side", None))
        sym = str(getattr(candidate, "symbol", "") or alert.get("symbol") or "")
        candles = premium_candles_1m
        if not candles and chart_meta:
            candles = chart_meta.get("_premiumCandles1m") or []
        ltp = float(getattr(premium_chart, "lastPremium", 0) or 0)

        from app.engines.winner_entry_guards import (
            fast_bullish_call_rally_exec_lane,
            put_slide_rally_exec_lane,
        )

        if side == "CALL" and fast_bullish_call_rally_exec_lane(alert):
            from app.engines.premium_spike_dump_guard import (
                fast_bullish_post_spike_red_candle_blocked,
                opposite_put_rip_blocks_call_dump,
            )

            blocked, reason, trap_meta = fast_bullish_post_spike_red_candle_blocked(
                list(candles or []), ltp, settings=settings,
            )
            meta.update(trap_meta or {})
            if blocked:
                return True, reason, meta
            if snap is not None:
                opp, opp_reason, opp_meta = opposite_put_rip_blocks_call_dump(
                    sym, snap, premium_chart, settings=settings,
                )
                meta.update(opp_meta or {})
                if opp:
                    return True, opp_reason, meta
        elif side == "PUT" and put_slide_rally_exec_lane(alert) and snap is not None:
            from app.engines.premium_spike_dump_guard import (
                opposite_call_rip_blocks_put_dump,
                put_slide_post_spike_red_candle_blocked,
            )

            blocked, reason, trap_meta = put_slide_post_spike_red_candle_blocked(
                list(candles or []), ltp, settings=settings,
            )
            meta.update(trap_meta or {})
            if blocked:
                return True, reason, meta
            opp, opp_reason, opp_meta = opposite_call_rip_blocks_put_dump(
                sym, snap, premium_chart, settings=settings,
            )
            meta.update(opp_meta or {})
            if opp:
                return True, opp_reason, meta

    if bool(getattr(settings, "execution_order_preflight_min_live_score_recheck", True)):
        from app.engines.live_entry_score import (
            live_entry_score_blocks_entry,
            refresh_candidate_live_entry_score,
        )

        refresh_candidate_live_entry_score(
            candidate, snap, premium_chart=premium_chart,
        )
        blocked, reason, live_meta = live_entry_score_blocks_entry(
            candidate,
            snap,
            premium_chart=premium_chart,
        )
        meta["liveEntryRecheck"] = live_meta
        if blocked:
            return True, f"exec_preflight_{reason}", meta

    from app.engines.premium_spike_dump_guard import (
        alert_premium_spike_dump_meta,
        post_spike_premium_dump_blocked,
    )

    force_dump = bool(getattr(settings, "execution_order_preflight_force_post_spike_dump", True))
    if force_dump:
        dump_meta = alert_premium_spike_dump_meta(alert, settings=settings)
        meta["alertDumpRecheck"] = dump_meta
        if dump_meta.get("active"):
            return True, "exec_preflight_premium_post_spike_dump", meta
        if bool(
            getattr(settings, "execution_order_preflight_block_deep_near_low_falling", True)
        ):
            dd_peak = float(dump_meta.get("drawdownFromPeakPct") or 0)
            min_dd_peak = float(
                getattr(
                    settings,
                    "execution_order_preflight_deep_near_low_min_drawdown_pct",
                    25.0,
                )
                or 25.0
            )
            if dump_meta.get("nearSessionLow") and dd_peak <= -min_dd_peak:
                mom3 = meta.get("premiumMomentum3Pct")
                mom5 = meta.get("premiumMomentum5Pct")
                if mom3 is None and premium_chart is not None:
                    mom3 = float(premium_chart.momentum3Pct or 0)
                    mom5 = float(premium_chart.momentum5Pct or 0)
                try:
                    m3 = float(mom3 or 0)
                    m5 = float(mom5 or 0)
                except (TypeError, ValueError):
                    m3 = m5 = 0.0
                if m3 < 0 or m5 < 0:
                    return True, "exec_preflight_deep_near_low_falling", meta
    else:
        dump_blocked, dump_reason, dump_meta = post_spike_premium_dump_blocked(
            getattr(candidate, "explosion_event", None),
            alert=alert,
            settings=settings,
        )
        meta["alertDumpRecheck"] = dump_meta
        if dump_blocked:
            return True, f"exec_preflight_{dump_reason}", meta

    return False, "ok", meta