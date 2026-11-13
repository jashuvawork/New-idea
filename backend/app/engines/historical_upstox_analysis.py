"""Historical index/option chart analysis via Upstox V3 candles (Nexus setup mirror)."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.engines.chart_advanced_analysis import build_chart_analysis
from app.engines.ftv_probability import normalize_candles
from app.engines.mtf_chart_analysis import (
    SCALP_TIMEFRAMES,
    analyze_timeframe,
    mtf_summary,
    resample_candles,
)
from app.engines.realtime_engine import _build_profile
from app.engines.spot_direction import (
    analyze_premium_chart,
    build_spot_chart,
    chart_summary_dict,
    side_aligned_with_chart,
)
from app.models.schemas import MarketProfile, Side
from app.services.upstox import INDEX_KEYS, UpstoxClient, UpstoxError

IST = ZoneInfo("Asia/Kolkata")


def _parse_session_date(date_str: str) -> date:
    return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()


def _parse_anchor_ist(date_str: str, at_ist: str) -> datetime:
    d = _parse_session_date(date_str)
    parts = at_ist.strip().split(":")
    if len(parts) < 2:
        raise ValueError("at_ist must be HH:MM or HH:MM:SS")
    h, m = int(parts[0]), int(parts[1])
    sec = int(parts[2]) if len(parts) > 2 else 0
    return datetime.combine(d, time(h, m, sec), tzinfo=IST)


def _session_filter(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start = 9 * 60 + 15
    end = 15 * 60 + 35
    out: list[dict[str, Any]] = []
    for c in candles:
        ts: datetime = c["ts"]
        minute = ts.hour * 60 + ts.minute
        if start <= minute <= end:
            out.append(c)
    return out


def _until_anchor(
    candles: list[dict[str, Any]], anchor: datetime
) -> list[dict[str, Any]]:
    return [c for c in candles if c["ts"] <= anchor]


def _to_ohlcv_rows(candles: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            c["ts"].isoformat(),
            c["open"],
            c["high"],
            c["low"],
            c["close"],
            c["volume"],
        ]
        for c in candles
    ]


def build_mtf_reads_from_1m(
    candles_1m: list[dict[str, Any]],
    price: float,
) -> dict[str, Any]:
    """MTF reads from sliced 1m history (no live intraday API)."""
    rows = _to_ohlcv_rows(candles_1m)
    reads: dict[str, Any] = {}
    reads["1m"] = analyze_timeframe(rows, price, "1m")
    for frame in SCALP_TIMEFRAMES:
        label = frame["label"]
        if label == "1m":
            continue
        resample = int(frame["resample"])
        tf_rows = resample_candles(rows, resample)
        reads[label] = (
            analyze_timeframe(tf_rows, price, label)
            if tf_rows
            else analyze_timeframe([], price, label)
        )
    return reads


def _index_session_stats(candles: list[dict[str, Any]]) -> dict[str, Any]:
    if not candles:
        return {}
    opens = [c["open"] for c in candles]
    lows = [c["low"] for c in candles]
    highs = [c["high"] for c in candles]
    closes = [c["close"] for c in candles]
    session_open = opens[0]
    session_low = min(lows)
    session_high = max(highs)
    spot = closes[-1]
    off_low = ((spot - session_low) / session_low * 100) if session_low > 0 else 0.0
    off_high = ((session_high - spot) / session_high * 100) if session_high > 0 else 0.0
    from_open = ((spot - session_open) / session_open * 100) if session_open > 0 else 0.0
    return {
        "sessionOpen": round(session_open, 2),
        "sessionLow": round(session_low, 2),
        "sessionHigh": round(session_high, 2),
        "spotAtAnchor": round(spot, 2),
        "offSessionLowPct": round(off_low, 2),
        "offSessionHighPct": round(off_high, 2),
        "fromOpenPct": round(from_open, 2),
        "barCount1m": len(candles),
    }


def _premium_session_stats(candles: list[dict[str, Any]]) -> dict[str, Any]:
    if not candles:
        return {}
    lows = [c["low"] for c in candles]
    highs = [c["high"] for c in candles]
    prem = candles[-1]["close"]
    session_low = min(lows)
    session_high = max(highs)
    off_low = ((prem - session_low) / session_low * 100) if session_low > 0 else 0.0
    return {
        "sessionPremiumLow": round(session_low, 2),
        "sessionPremiumHigh": round(session_high, 2),
        "premiumAtAnchor": round(prem, 2),
        "offSessionLowPct": round(off_low, 2),
        "barCount1m": len(candles),
    }


def _base_rip_verdict(
    *,
    index_stats: dict[str, Any],
    spot_chart: dict[str, Any],
    index_mtf: dict[str, Any],
    premium_stats: dict[str, Any],
    premium_chart: dict[str, Any],
    side: Side,
) -> dict[str, Any]:
    """Heuristic labels aligned with local-base / participation-led V-rip bands."""
    notes: list[str] = []
    off_low = float(index_stats.get("offSessionLowPct") or 0)
    prem_off = float(premium_stats.get("offSessionLowPct") or 0)
    aligned = int(index_mtf.get("alignedCount") or 0)
    total = int(index_mtf.get("total") or 5)
    chart_dir = str(spot_chart.get("direction") or "NEUTRAL")
    side_ok = chart_dir == ("BULLISH" if side == Side.CALL else "BEARISH") or chart_dir == "NEUTRAL"

    in_spot_band = 0.5 <= off_low <= 25.0
    in_prem_band = 2.0 <= prem_off <= 22.0 if premium_stats else False

    if in_prem_band or (in_spot_band and prem_off <= 0 and premium_stats):
        notes.append("off_session_low_in_band")
    if aligned >= 3 and side_ok:
        notes.append("mtf_aligned")
    if float(premium_chart.get("volumeSurge") or 0) >= 1.5:
        notes.append("premium_volume_surge")
    if float(spot_chart.get("momentum5Pct") or 0) * (1 if side == Side.CALL else -1) > 0:
        notes.append("index_momentum_with_side")

    if notes and (in_prem_band or aligned >= 3):
        verdict = "BASE_RIP_SETUP"
    elif aligned >= 2 and side_ok:
        verdict = "WATCH_BASE"
    else:
        verdict = "NO_SETUP"

    return {
        "verdict": verdict,
        "side": side.value,
        "signals": notes,
        "indexOffSessionLowPct": off_low,
        "premiumOffSessionLowPct": prem_off,
        "mtfAligned": f"{aligned}/{total}",
    }


async def fetch_instrument_1m_for_date(
    client: UpstoxClient,
    instrument_key: str,
    session_date: str,
    *,
    force_refresh: bool = True,
) -> list[dict[str, Any]]:
    d = _parse_session_date(session_date)
    iso = d.isoformat()
    raw = await client.get_historical_candles_v3(
        instrument_key,
        unit="minutes",
        interval=1,
        to_date=iso,
        from_date=iso,
        force_refresh=force_refresh,
    )
    return _session_filter(normalize_candles(raw))


async def analyze_historical_setup(
    client: UpstoxClient,
    *,
    symbol: str,
    session_date: str,
    at_ist: str,
    side: str = "PUT",
    instrument_key: Optional[str] = None,
) -> dict[str, Any]:
    """
    Point-in-time Nexus-style chart read from Upstox historical 1m candles.

    Requires valid Upstox OAuth token (same as live chart pre-test).
    """
    sym = symbol.upper()
    index_key = INDEX_KEYS.get(sym)
    if not index_key:
        raise ValueError(f"Unknown symbol: {sym}")

    anchor = _parse_anchor_ist(session_date, at_ist)
    side_enum = Side(side.upper())

    index_day = await fetch_instrument_1m_for_date(
        client, index_key, session_date, force_refresh=True
    )
    index_slice = _until_anchor(index_day, anchor)
    if len(index_slice) < 16:
        raise UpstoxError(
            f"Insufficient index candles at {at_ist} on {session_date} "
            f"(got {len(index_slice)}). Check date is a session day and Upstox history exists."
        )

    spot = float(index_slice[-1]["close"])
    rows_1m = _to_ohlcv_rows(index_slice)
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    candles_5m = resample_candles(rows_1m, settings.spot_chart_timeframe_minutes)
    profile = _build_profile(rows_1m, spot)
    spot_chart = build_spot_chart(
        candles_5m, spot, profile, indicator_candles_1m=rows_1m
    )
    index_stats = _index_session_stats(index_slice)

    prev_close = float(index_slice[0]["open"])
    day_high = max(c["high"] for c in index_slice)
    day_low = min(c["low"] for c in index_slice)
    chart_analysis = build_chart_analysis(
        rows_1m,
        candles_5m,
        spot,
        profile,
        prev_close=prev_close,
        day_high=day_high,
        day_low=day_low,
        symbol=sym,
    )
    mtf_reads = build_mtf_reads_from_1m(index_slice, spot)
    index_mtf = mtf_summary(mtf_reads, side_enum)

    out: dict[str, Any] = {
        "source": "upstox_historical_v3",
        "symbol": sym,
        "sessionDate": session_date,
        "anchorIst": anchor.isoformat(),
        "side": side_enum.value,
        "indexInstrumentKey": index_key,
        "indexSession": index_stats,
        "indexChart": chart_summary_dict(spot_chart),
        "alignedWithChart": side_aligned_with_chart(side_enum, spot_chart),
        "indexMtf": index_mtf,
        "chartAnalysisSummary": {
            "consensus": chart_analysis.consensus,
            "alignedCount": chart_analysis.alignedCount,
            "totalTimeframes": chart_analysis.totalTimeframes,
            "keySignals": list(chart_analysis.keySignals or [])[:8],
            "decisiveCandle": chart_analysis.decisiveCandle,
        },
    }

    premium_slice: list[dict[str, Any]] = []
    if instrument_key:
        try:
            prem_day = await fetch_instrument_1m_for_date(
                client, instrument_key, session_date, force_refresh=True
            )
            premium_slice = _until_anchor(prem_day, anchor)
        except Exception as exc:
            out["premiumError"] = str(exc)[:200]
        if premium_slice:
            prem_ltp = float(premium_slice[-1]["close"])
            prem_rows = _to_ohlcv_rows(premium_slice)
            premium_chart = analyze_premium_chart(prem_rows, prem_ltp)
            prem_mtf_reads = build_mtf_reads_from_1m(premium_slice, prem_ltp)
            out["instrumentKey"] = instrument_key
            out["premiumSession"] = _premium_session_stats(premium_slice)
            out["premiumChart"] = {
                "direction": premium_chart.direction,
                "lastPremium": premium_chart.lastPremium,
                "momentum3Pct": premium_chart.momentum3Pct,
                "momentum5Pct": premium_chart.momentum5Pct,
                "volumeSurge": premium_chart.volumeSurge,
                "vwap": premium_chart.vwap,
                "aboveVwap": premium_chart.aboveVwap,
                "rsi": premium_chart.rsi,
                "macdBias": premium_chart.macdBias,
            }
            out["premiumMtf"] = mtf_summary(prem_mtf_reads, side_enum)
        else:
            out["premiumChart"] = {}
            out["premiumMtf"] = {}
    else:
        out["premiumChart"] = {}
        out["premiumMtf"] = {}

    out["baseRip"] = _base_rip_verdict(
        index_stats=index_stats,
        spot_chart=out["indexChart"],
        index_mtf=index_mtf,
        premium_stats=out.get("premiumSession") or {},
        premium_chart=out.get("premiumChart") or {},
        side=side_enum,
    )
    return out
