"""Fresh Upstox chart fetch + pro MTF analysis immediately before trade execution."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.mtf_chart_analysis import fetch_mtf_charts, mtf_summary, validate_mtf_scalp
from app.engines.realtime_engine import _build_profile
from app.engines.index_chart_candles import fetch_index_chart_candles
from app.engines.spot_direction import (
    analyze_premium_chart,
    build_spot_chart,
    chart_blocks_side,
    chart_summary_dict,
    premium_blocks_entry,
    pro_index_quote_context,
    side_aligned_with_chart,
)
from app.models.schemas import PremiumChart, Side, SpotChart, SymbolSnapshot
from app.services.upstox import INDEX_KEYS, UpstoxClient

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def _premium_chart_dict(premium: Optional[PremiumChart]) -> dict[str, Any]:
    if not premium:
        return {}
    return {
        "direction": premium.direction,
        "lastPremium": premium.lastPremium,
        "momentum3Pct": premium.momentum3Pct,
        "momentum5Pct": premium.momentum5Pct,
        "volumeSurge": premium.volumeSurge,
        "vwap": premium.vwap,
        "aboveVwap": premium.aboveVwap,
    }


def _snapshot_chart_delta(snap_chart: SpotChart, live_chart: SpotChart) -> dict[str, Any]:
    return {
        "directionChanged": snap_chart.direction != live_chart.direction,
        "snapshotDirection": snap_chart.direction,
        "liveDirection": live_chart.direction,
        "momentum5Delta": round(live_chart.momentum5Pct - snap_chart.momentum5Pct, 3),
    }


async def fetch_live_trade_charts(
    client: UpstoxClient,
    symbol: str,
    side: Side,
    strike: float,
    snap: SymbolSnapshot,
    *,
    instrument_key: Optional[str] = None,
) -> dict[str, Any]:
    """
    Pull fresh index + option premium charts from Upstox for the exact trade leg.
    Includes multi-timeframe (1m/5m/15m/1h/4h) pre-test analysis.
    """
    settings = get_settings()
    from app.services.upstox import rate_limit_active

    force = settings.execution_chart_force_upstox_refresh and not rate_limit_active()
    count = settings.execution_chart_candle_count
    sym = symbol.upper()

    quote = await client.get_index_quote(sym, force_refresh=force)
    spot = float(quote.get("last_price") or snap.spot or 0)
    try:
        from app.services.tick_store import is_ws_active, overlay_index_ltp

        if is_ws_active():
            spot = overlay_index_ltp(sym, spot, max_age_seconds=3.0)
    except Exception:
        pass

    index_key = INDEX_KEYS.get(sym)
    candles_5m, index_candles = await fetch_index_chart_candles(client, sym, force_refresh=force)
    if not index_candles:
        index_candles = await client.get_candles(sym, count=count, force_refresh=force)
    profile = _build_profile(index_candles, spot)
    index_chart = build_spot_chart(candles_5m, spot, profile, indicator_candles_1m=index_candles)
    quote_ctx = pro_index_quote_context(quote, spot)

    index_mtf_reads = None
    premium_mtf_reads = None
    if settings.execution_mtf_enabled and index_key:
        try:
            index_mtf_reads = await fetch_mtf_charts(client, index_key, spot, force_refresh=force)
            index_mtf = mtf_summary(index_mtf_reads, side)
        except Exception as exc:
            logger.warning("Index MTF fetch failed for %s: %s", sym, exc)
            index_mtf = {"error": str(exc)[:120]}
    else:
        index_mtf = {}

    premium_chart: Optional[PremiumChart] = None
    premium_mtf: dict[str, Any] = {}
    premium_mtf_reads = None
    prem_ltp = 0.0
    if instrument_key:
        try:
            opt_candles = await client.get_historical_candles(
                instrument_key, count=min(30, count), force_refresh=force,
            )
            quotes = await client.get_full_quotes([instrument_key])
            leg = quotes.get(instrument_key) or quotes.get(instrument_key.replace("|", ":")) or {}
            prem_ltp = float(
                leg.get("last_price") or leg.get("ltp") or strike or snap.spot or 0,
            )
            from app.engines.snapshot_fast import resolve_trade_premium

            ws_prem = resolve_trade_premium(
                snap, strike, side, instrument_key=instrument_key, max_age_seconds=3.0,
            )
            if ws_prem is not None and ws_prem > 0:
                prem_ltp = ws_prem
            if not prem_ltp:
                prem_ltp = float(strike)
            premium_chart = analyze_premium_chart(opt_candles, prem_ltp)

            if settings.execution_mtf_enabled:
                try:
                    premium_mtf_reads = await fetch_mtf_charts(
                        client, instrument_key, prem_ltp, force_refresh=force,
                    )
                    premium_mtf = mtf_summary(premium_mtf_reads, side)
                except Exception as exc:
                    logger.warning("Premium MTF fetch failed: %s", exc)
                    premium_mtf = {}
            else:
                premium_mtf = {}
        except Exception as exc:
            logger.warning("Option chart fetch failed for %s: %s", instrument_key, exc)

    return {
        "source": "upstox_live",
        "fetchedAt": datetime.now(IST).isoformat(),
        "symbol": sym,
        "side": side.value,
        "strike": strike,
        "instrumentKey": instrument_key,
        "spot": round(spot, 2),
        "indexChart": chart_summary_dict(index_chart),
        "indexChartFull": index_chart.model_dump(),
        "quoteContext": quote_ctx,
        "premiumChart": _premium_chart_dict(premium_chart),
        "indexMtf": index_mtf,
        "premiumMtf": premium_mtf,
        "snapshotDelta": _snapshot_chart_delta(snap.spotChart, index_chart),
        "alignedWithChart": side_aligned_with_chart(side, index_chart),
        "recommendedSide": chart_summary_dict(index_chart).get("recommendedSide"),
        "_indexMtfReads": index_mtf_reads,
        "_premiumMtfReads": premium_mtf_reads,
    }


def _strip_mtf_reads(mtf: dict[str, Any]) -> dict[str, Any]:
    return mtf or {}


def validate_execution_charts(
    side: Side,
    index_chart: SpotChart,
    *,
    premium_chart: Optional[PremiumChart] = None,
    trade_score: float = 0.0,
    index_mtf_reads: Optional[dict] = None,
    premium_mtf_reads: Optional[dict] = None,
    breadth_aligned_bypass: bool = False,
    premium_led_bypass: bool = False,
    expiry_explosion_bypass: bool = False,
    explosion_event: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Final chart gate — 1m index + MTF scalp pre-test + premium."""
    mtf_meta: dict[str, Any] = {}

    blocked, reason = chart_blocks_side(
        side, index_chart, trade_score=trade_score,
        breadth_aligned_bypass=breadth_aligned_bypass,
        premium_led_bypass=premium_led_bypass,
        expiry_explosion_bypass=expiry_explosion_bypass,
    )
    if blocked:
        return False, f"exec_{reason}", mtf_meta

    blocked, reason = premium_blocks_entry(
        side, premium_chart, trade_score=trade_score, explosion_event=explosion_event,
    )
    if blocked:
        return False, f"exec_{reason}", mtf_meta

    if index_mtf_reads:
        passed, reason, mtf_meta = validate_mtf_scalp(
            side,
            index_mtf_reads,
            premium_mtf_reads,
            trade_score=trade_score,
            premium_led_bypass=premium_led_bypass,
        )
        if not passed:
            return False, reason, mtf_meta

    return True, "ok", mtf_meta


async def monitor_trade_chart_before_execution(
    client: UpstoxClient,
    symbol: str,
    side: Side,
    strike: float,
    snap: SymbolSnapshot,
    *,
    trade_score: float,
    instrument_key: Optional[str] = None,
    mode: str = "",
    explosion_event: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Fetch live Upstox charts (1m–4h) for this trade and block if misaligned.
    Returns (passed, reason, metadata for entryContext.executionChart).
    """
    settings = get_settings()
    if not settings.execution_chart_gate_enabled:
        return True, "ok", {"enabled": False}

    from app.engines.expiry_day_guards import expiry_pm_itm_chart_bypass_allowed
    from app.engines.aligned_explosion_bypass import expiry_chart_bypass_for_event
    from app.engines.morning_premium_capture import premium_led_bypass_for_snap

    breadth_bypass = expiry_pm_itm_chart_bypass_allowed(side, snap, mode=mode)
    premium_bypass = premium_led_bypass_for_snap(
        side, snap, explosion_event=explosion_event,
    )
    expiry_chart_bypass = (
        expiry_chart_bypass_for_event(explosion_event, snap)
        if explosion_event is not None
        else False
    )

    try:
        meta = await fetch_live_trade_charts(
            client, symbol, side, strike, snap, instrument_key=instrument_key,
        )
    except Exception as exc:
        logger.warning("Execution chart fetch failed for %s — using snapshot: %s", symbol, exc)
        blocked, reason = chart_blocks_side(
            side, snap.spotChart, trade_score=trade_score,
            breadth_aligned_bypass=breadth_bypass,
            premium_led_bypass=premium_bypass,
            expiry_explosion_bypass=expiry_chart_bypass,
        )
        fallback = {
            "enabled": True,
            "source": "snapshot_fallback",
            "error": str(exc)[:200],
            "indexChart": chart_summary_dict(snap.spotChart),
            "alignedWithChart": side_aligned_with_chart(side, snap.spotChart),
        }
        if blocked:
            return False, f"exec_{reason}", fallback
        return True, "ok", fallback

    index_chart = SpotChart(**meta["indexChartFull"])
    premium_data = meta.get("premiumChart") or {}
    premium_chart = PremiumChart(**premium_data) if premium_data else None
    index_mtf_reads = meta.pop("_indexMtfReads", None)
    premium_mtf_reads = meta.pop("_premiumMtfReads", None)

    passed, reason, mtf_meta = validate_execution_charts(
        side,
        index_chart,
        premium_chart=premium_chart,
        trade_score=trade_score,
        index_mtf_reads=index_mtf_reads,
        premium_mtf_reads=premium_mtf_reads,
        breadth_aligned_bypass=breadth_bypass,
        premium_led_bypass=premium_bypass,
        expiry_explosion_bypass=expiry_chart_bypass,
        explosion_event=explosion_event,
    )
    if mtf_meta:
        meta["mtfPreTest"] = mtf_meta

    meta["enabled"] = True
    meta["passed"] = passed
    meta["blockReason"] = reason if not passed else None
    meta["premiumLedBypass"] = premium_bypass
    meta["expiryExplosionBypass"] = expiry_chart_bypass
    meta["breadthAlignedBypass"] = breadth_bypass
    snap_aligned = side_aligned_with_chart(side, snap.spotChart)
    exec_aligned = side_aligned_with_chart(side, index_chart)
    meta["snapshotAligned"] = snap_aligned
    meta["snapshotChart"] = chart_summary_dict(snap.spotChart) if snap.spotChart else {}
    meta["chartBypassUsed"] = bool(
        passed
        and not exec_aligned
        and (premium_bypass or expiry_chart_bypass or breadth_bypass)
    )
    if meta["chartBypassUsed"] and snap_aligned:
        meta["alignedWithChart"] = True
    return passed, reason, meta
