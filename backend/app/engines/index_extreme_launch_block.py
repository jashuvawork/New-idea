"""Pre-entry block: counter-trend launch at session extremes without index + premium momentum."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import PremiumChart, Side, SymbolSnapshot


def _side_val(side: Any) -> str:
    if isinstance(side, Side):
        return side.value
    return str(side or "").upper()


def _off_session_pcts(hi: float, lo: float, spot: float) -> tuple[float, float]:
    off_high = ((hi - spot) / hi * 100.0) if hi > 0 and spot > 0 else 999.0
    off_low = ((spot - lo) / lo * 100.0) if lo > 0 and spot > 0 else 999.0
    return off_high, off_low


def _local_pad_pct_from_alert(alert: Optional[dict[str, Any]]) -> float:
    if not isinstance(alert, dict):
        return 0.0
    return float(
        alert.get("localBaseMovePct")
        or alert.get("offLowMovePct")
        or alert.get("offHighMovePct")
        or 0
    )


def session_extreme_mid_pad_chase_blocked(
    side: Any,
    snap: Optional[SymbolSnapshot],
    *,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Block mid-pad chase at session high (CALL) or low (PUT) — waivers are for near-base only.
    CE/PE symmetric (Nov27 25750 pattern).
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    side_u = _side_val(side)
    if snap is None or side_u not in ("CALL", "PUT"):
        return False, "ok", meta

    sym = str(getattr(snap, "symbol", "") or "").upper()
    if not sym and isinstance(alert, dict):
        sym = str(alert.get("symbol") or "").upper()
    from app.engines.index_tick_helpers import resolve_index_session

    ext = resolve_index_session(sym, snap)
    hi = float(ext.get("hi") or 0)
    lo = float(ext.get("lo") or 0)
    spot = float(ext.get("last") or 0) or float(getattr(snap, "spot", 0) or 0)
    if hi <= 0 or lo <= 0 or spot <= 0:
        return False, "ok", meta

    off_high, off_low = _off_session_pcts(hi, lo, spot)
    near_pct = float(getattr(settings, "pre_entry_index_near_extreme_pct", 1.0) or 1.0)
    pad = _local_pad_pct_from_alert(alert)
    max_shallow = float(
        getattr(settings, "pre_entry_mid_pad_at_extreme_max_local_pad_pct", 8.0) or 8.0
    )
    meta.update(
        localPadPct=round(pad, 2),
        offSessionHighPct=round(off_high, 3),
        offSessionLowPct=round(off_low, 3),
        nearExtremePct=near_pct,
    )

    if side_u == "CALL" and bool(
        getattr(settings, "pre_entry_block_call_mid_pad_at_session_high", True)
    ):
        if off_high <= near_pct + 1e-6 and pad > max_shallow + 1e-6:
            meta["sessionExtremeMidPadChase"] = "call_at_session_high"
            return True, "exec_preflight_call_mid_pad_at_session_high", meta
    if side_u == "PUT" and bool(
        getattr(settings, "pre_entry_block_put_mid_pad_at_session_low", True)
    ):
        if off_low <= near_pct + 1e-6 and pad > max_shallow + 1e-6:
            meta["sessionExtremeMidPadChase"] = "put_at_session_low"
            return True, "exec_preflight_put_mid_pad_at_session_low", meta
    return False, "ok", meta


def index_extreme_launch_preflight_blocked(
    side: Any,
    snap: Optional[SymbolSnapshot],
    *,
    premium_chart: Optional[PremiumChart] = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Last-line gate: do not launch PUT at the session high (or CALL at the low) unless the
    index is already moving with the trade, with optional premium mom5 floor on expensive
    entries (Nov25 SENSEX 83600 PE pattern).
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"indexExtremeLaunchBlock": True}
    if not bool(getattr(settings, "pre_entry_index_extreme_block_enabled", True)):
        return False, "ok", meta

    side_u = _side_val(side)
    sym = ""
    if isinstance(alert, dict):
        sym = str(alert.get("symbol") or "").upper()
    if not sym and snap is not None:
        sym = str(getattr(snap, "symbol", "") or "").upper()

    # --- Premium momentum launch quality (CE/PE) ---
    if premium_chart is not None:
        ltp = float(premium_chart.lastPremium or 0)
        prem_mom5 = float(premium_chart.momentum5Pct or 0)
        hi_inr = float(getattr(settings, "pre_entry_high_premium_inr_threshold", 300.0) or 300.0)
        min_mom5 = float(
            getattr(settings, "pre_entry_high_premium_min_mom5_pct", 1.0) or 1.0
        )
        meta.update(
            entryPremiumInr=round(ltp, 2),
            premiumMomentum5Pct=round(prem_mom5, 3),
            highPremiumThresholdInr=hi_inr,
        )
        # Positive but weak ignition only — negative mom5 is handled by falling-momentum gate.
        if (
            ltp >= hi_inr - 1e-6
            and prem_mom5 >= -1e-9
            and prem_mom5 < min_mom5 - 1e-9
        ):
            return True, "exec_preflight_weak_premium_launch_mom5", meta

    if snap is None or not sym:
        return False, "ok", meta

    from app.engines.index_tick_helpers import resolve_index_session

    ext = resolve_index_session(sym, snap)
    hi = float(ext.get("hi") or 0)
    lo = float(ext.get("lo") or 0)
    spot = float(ext.get("last") or 0) or float(getattr(snap, "spot", 0) or 0)
    if hi <= 0 or lo <= 0 or spot <= 0:
        meta["indexExtremeReason"] = "missing_session_range"
        return False, "ok", meta

    off_high, off_low = _off_session_pcts(hi, lo, spot)
    near_pct = float(getattr(settings, "pre_entry_index_near_extreme_pct", 1.0) or 1.0)
    min_mom = float(
        getattr(settings, "pre_entry_index_extreme_min_adverse_mom5_pct", 0.05) or 0.05
    )
    meta.update(
        sessionHigh=round(hi, 2),
        sessionLow=round(lo, 2),
        spot=round(spot, 2),
        offSessionHighPct=round(off_high, 3),
        offSessionLowPct=round(off_low, 3),
        nearExtremePct=near_pct,
    )

    chart = getattr(snap, "spotChart", None)
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0) if chart else 0.0
    mom_min = min_mom

    if side_u == "PUT":
        chase_block, chase_reason, chase_meta = session_extreme_mid_pad_chase_blocked(
            side_u, snap, alert=alert, settings=settings,
        )
        meta.update(chase_meta)
        if chase_block:
            return True, chase_reason, meta

        near_high = off_high <= near_pct + 1e-6
        if not near_high:
            return False, "ok", meta
        slide_ok = False
        if bool(getattr(settings, "pre_entry_index_extreme_allow_slide_flip_waiver", True)):
            from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

            slide_ok, slide_reason, slide_meta = index_rally_side_flip_bypass(
                sym, Side.PUT, snap, settings=settings,
            )
            meta["indexSlideFlipWaiver"] = {
                "ok": slide_ok,
                "reason": slide_reason,
                **(slide_meta or {}),
            }
        meta["indexMom5Pct"] = round(mom5, 4)
        # At session high: index must already be sliding (negative mom5).
        if mom5 > -mom_min + 1e-9 and not slide_ok:
            return True, "exec_preflight_put_at_session_high_weak_index", meta
        chart_dir = str(getattr(chart, "direction", "") or "").upper() if chart else ""
        if (
            bool(getattr(settings, "pre_entry_index_extreme_block_put_bullish_chart", True))
            and chart_dir == "BULLISH"
            and mom5 > -mom_min + 1e-9
            and not slide_ok
        ):
            return True, "exec_preflight_put_bullish_chart_at_high", meta

    elif side_u == "CALL":
        chase_block, chase_reason, chase_meta = session_extreme_mid_pad_chase_blocked(
            side_u, snap, alert=alert, settings=settings,
        )
        meta.update(chase_meta)
        if chase_block:
            return True, chase_reason, meta

        near_low = off_low <= near_pct + 1e-6
        if not near_low:
            return False, "ok", meta
        rally_ok = False
        if bool(getattr(settings, "pre_entry_index_extreme_allow_rally_flip_waiver", True)):
            from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

            rally_ok, rally_reason, rally_meta = index_rally_side_flip_bypass(
                sym, Side.CALL, snap, settings=settings,
            )
            meta["indexRallyFlipWaiver"] = {
                "ok": rally_ok,
                "reason": rally_reason,
                **(rally_meta or {}),
            }
        meta["indexMom5Pct"] = round(mom5, 4)
        if mom5 < mom_min - 1e-9 and not rally_ok:
            return True, "exec_preflight_call_at_session_low_weak_index", meta
        chart_dir = str(getattr(chart, "direction", "") or "").upper() if chart else ""
        if (
            bool(getattr(settings, "pre_entry_index_extreme_block_call_bearish_chart", True))
            and chart_dir == "BEARISH"
            and mom5 < mom_min - 1e-9
            and not rally_ok
        ):
            return True, "exec_preflight_call_bearish_chart_at_low", meta

    return False, "ok", meta