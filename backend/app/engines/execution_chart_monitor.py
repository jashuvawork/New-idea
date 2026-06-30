"""Fresh Upstox chart fetch + pro analysis immediately before trade execution."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.realtime_engine import _build_profile
from app.engines.spot_direction import (
    analyze_premium_chart,
    analyze_spot_chart,
    chart_blocks_side,
    chart_summary_dict,
    premium_blocks_entry,
    pro_index_quote_context,
    side_aligned_with_chart,
)
from app.models.schemas import PremiumChart, Side, SpotChart, SymbolSnapshot
from app.services.upstox import UpstoxClient

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
  """
    settings = get_settings()
    force = settings.execution_chart_force_upstox_refresh
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

    index_candles = await client.get_candles(sym, count=count, force_refresh=force)
    profile = _build_profile(index_candles, spot)
    index_chart = analyze_spot_chart(index_candles, spot, profile)
    quote_ctx = pro_index_quote_context(quote, spot)

    premium_chart: Optional[PremiumChart] = None
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
            if not prem_ltp:
                prem_ltp = float(strike)  # fallback for analysis shape
            premium_chart = analyze_premium_chart(opt_candles, prem_ltp)
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
        "snapshotDelta": _snapshot_chart_delta(snap.spotChart, index_chart),
        "alignedWithChart": side_aligned_with_chart(side, index_chart),
        "recommendedSide": chart_summary_dict(index_chart).get("recommendedSide"),
    }


def validate_execution_charts(
    side: Side,
    index_chart: SpotChart,
    *,
    premium_chart: Optional[PremiumChart] = None,
    trade_score: float = 0.0,
) -> tuple[bool, str]:
    """Final chart gate at execution — index direction + premium expansion."""
    blocked, reason = chart_blocks_side(
        side, index_chart, trade_score=trade_score,
    )
    if blocked:
        return False, f"exec_{reason}"

    blocked, reason = premium_blocks_entry(side, premium_chart, trade_score=trade_score)
    if blocked:
        return False, f"exec_{reason}"

    return True, "ok"


async def monitor_trade_chart_before_execution(
    client: UpstoxClient,
    symbol: str,
    side: Side,
    strike: float,
    snap: SymbolSnapshot,
    *,
    trade_score: float,
    instrument_key: Optional[str] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Fetch live Upstox charts for this trade and block if index/premium disagree.
    Returns (passed, reason, metadata for entryContext.executionChart).
    """
    settings = get_settings()
    if not settings.execution_chart_gate_enabled:
        return True, "ok", {"enabled": False}

    try:
        meta = await fetch_live_trade_charts(
            client, symbol, side, strike, snap, instrument_key=instrument_key,
        )
    except Exception as exc:
        logger.warning("Execution chart fetch failed for %s — using snapshot: %s", symbol, exc)
        blocked, reason = chart_blocks_side(side, snap.spotChart, trade_score=trade_score)
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

    passed, reason = validate_execution_charts(
        side, index_chart, premium_chart=premium_chart, trade_score=trade_score,
    )
    meta["enabled"] = True
    meta["passed"] = passed
    meta["blockReason"] = reason if not passed else None
    return passed, reason, meta
