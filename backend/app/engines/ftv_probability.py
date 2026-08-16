"""Historical time-to-flat-to-vertical probability advisory.

The model uses Upstox V3 one-minute index candles to estimate empirical,
time-of-day breakout rates after compressed bases. It is deliberately
advisory: live option premium, volume, orderflow, liquidity, and entry gates
must confirm a CE/PE trade.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import MarketPhase, SymbolSnapshot
from app.services.upstox import INDEX_KEYS, UpstoxClient

IST = ZoneInfo("Asia/Kolkata")
HORIZONS = (1, 3, 5, 15)
_profile_cache: dict[str, tuple[float, dict[str, Any], list[dict[str, Any]]]] = {}
_profile_locks: dict[str, asyncio.Lock] = {}


def clear_ftv_probability_cache() -> None:
    """Clear fitted profiles (tests and explicit deployment resets)."""
    _profile_cache.clear()
    _profile_locks.clear()


def _number(value: Any) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        epoch = float(value)
        if epoch > 10_000_000_000:
            epoch /= 1000
        try:
            parsed = datetime.fromtimestamp(epoch, tz=IST)
        except (OSError, ValueError):
            return None
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(IST)


def normalize_candles(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """Normalize Upstox list/dict candles, sort ascending, and deduplicate."""
    by_ts: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, Mapping):
            ts = _timestamp(
                row.get("timestamp") or row.get("time") or row.get("ts")
            )
            open_px = _number(row.get("open"))
            high = _number(row.get("high"))
            low = _number(row.get("low"))
            close = _number(row.get("close"))
            volume = _number(row.get("volume"))
            oi = _number(row.get("oi") or row.get("open_interest"))
        elif isinstance(row, (list, tuple)) and len(row) >= 5:
            ts = _timestamp(row[0])
            open_px, high, low, close = (
                _number(row[1]), _number(row[2]), _number(row[3]), _number(row[4])
            )
            volume = _number(row[5]) if len(row) > 5 else 0.0
            oi = _number(row[6]) if len(row) > 6 else 0.0
        else:
            continue
        if ts is None or min(open_px, high, low, close) <= 0 or high < low:
            continue
        by_ts[ts] = {
            "ts": ts,
            "open": open_px,
            "high": high,
            "low": low,
            "close": close,
            "volume": max(0.0, volume),
            "oi": max(0.0, oi),
        }
    return [by_ts[key] for key in sorted(by_ts)]


def _market_candles(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        candle for candle in candles
        if 9 * 60 + 15 <= candle["ts"].hour * 60 + candle["ts"].minute <= 15 * 60 + 30
    ]


def _bucket_label(ts: datetime, bucket_minutes: int) -> str:
    minute = ts.hour * 60 + ts.minute
    bucket = (minute // bucket_minutes) * bucket_minutes
    return f"{bucket // 60:02d}:{bucket % 60:02d}"


def _posterior_rate(wins: int, samples: int, global_rate: float) -> float:
    # Eight pseudo-observations stabilize sparse 15-minute time buckets.
    prior = 8.0
    return (wins + global_rate * prior) / (samples + prior) if samples >= 0 else global_rate


def build_historical_profile(
    rows: Iterable[Any],
    *,
    base_window: int = 5,
    bucket_minutes: int = 15,
    flat_max_range_pct: float = 0.22,
    vertical_move_pct: float = 0.18,
) -> dict[str, Any]:
    """Fit leakage-safe empirical CE/PE breakout rates from index candles."""
    candles = _market_candles(normalize_candles(rows))
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candle in candles:
        by_day[candle["ts"].date().isoformat()].append(candle)

    global_counts = {
        side: {h: {"wins": 0, "samples": 0} for h in HORIZONS}
        for side in ("CALL", "PUT")
    }
    bucket_counts: dict[str, dict[str, dict[int, dict[str, int]]]] = defaultdict(
        lambda: {
            side: {h: {"wins": 0, "samples": 0} for h in HORIZONS}
            for side in ("CALL", "PUT")
        }
    )
    base_samples = 0
    range_total = 0.0

    for day_rows in by_day.values():
        for i in range(base_window - 1, len(day_rows) - 1):
            base = day_rows[i - base_window + 1 : i + 1]
            anchor = day_rows[i]
            anchor_close = anchor["close"]
            base_range = (
                (max(c["high"] for c in base) - min(c["low"] for c in base))
                / anchor_close
                * 100.0
            )
            if base_range > flat_max_range_pct:
                continue
            base_samples += 1
            range_total += base_range
            bucket = _bucket_label(anchor["ts"], bucket_minutes)
            for horizon in HORIZONS:
                future = day_rows[i + 1 : i + 1 + horizon]
                if len(future) < horizon:
                    continue
                call_win = (
                    (max(c["high"] for c in future) - anchor_close)
                    / anchor_close
                    * 100.0
                ) >= vertical_move_pct
                put_win = (
                    (anchor_close - min(c["low"] for c in future))
                    / anchor_close
                    * 100.0
                ) >= vertical_move_pct
                for side, won in (("CALL", call_win), ("PUT", put_win)):
                    global_counts[side][horizon]["samples"] += 1
                    bucket_counts[bucket][side][horizon]["samples"] += 1
                    if won:
                        global_counts[side][horizon]["wins"] += 1
                        bucket_counts[bucket][side][horizon]["wins"] += 1

    rates: dict[str, dict[str, Any]] = {}
    for side in ("CALL", "PUT"):
        rates[side] = {}
        for horizon in HORIZONS:
            counts = global_counts[side][horizon]
            rate = counts["wins"] / counts["samples"] if counts["samples"] else 0.0
            rates[side][str(horizon)] = {
                **counts,
                "probabilityPct": round(rate * 100.0, 2),
            }

    buckets: dict[str, Any] = {}
    for bucket, side_rows in bucket_counts.items():
        buckets[bucket] = {}
        for side in ("CALL", "PUT"):
            buckets[bucket][side] = {}
            for horizon in HORIZONS:
                counts = side_rows[side][horizon]
                global_rate = rates[side][str(horizon)]["probabilityPct"] / 100.0
                posterior = _posterior_rate(
                    counts["wins"], counts["samples"], global_rate,
                )
                buckets[bucket][side][str(horizon)] = {
                    **counts,
                    "probabilityPct": round(posterior * 100.0, 2),
                }

    leaders: dict[str, list[dict[str, Any]]] = {}
    for side in ("CALL", "PUT"):
        options = [
            {
                "time": bucket,
                "probabilityPct": values[side]["5"]["probabilityPct"],
                "samples": values[side]["5"]["samples"],
            }
            for bucket, values in buckets.items()
            if values[side]["5"]["samples"] >= 3
        ]
        leaders[side] = sorted(
            options,
            key=lambda row: (row["probabilityPct"], row["samples"]),
            reverse=True,
        )[:4]

    dates = sorted(by_day)
    return {
        "status": "READY" if base_samples else "INSUFFICIENT_DATA",
        "candleCount": len(candles),
        "sessionCount": len(dates),
        "fromDate": dates[0] if dates else None,
        "toDate": dates[-1] if dates else None,
        "baseSamples": base_samples,
        "averageBaseRangePct": round(range_total / base_samples, 4) if base_samples else 0.0,
        "baseWindowMinutes": base_window,
        "timeBucketMinutes": bucket_minutes,
        "flatMaxRangePct": flat_max_range_pct,
        "verticalMovePct": vertical_move_pct,
        "rates": rates,
        "buckets": buckets,
        "timeOfDayLeaders": leaders,
    }


def _latest_session(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candles:
        return []
    latest_date = candles[-1]["ts"].date()
    return [candle for candle in candles if candle["ts"].date() == latest_date]


def _alert_support(snapshot: SymbolSnapshot, side: str) -> float:
    support = 0.0
    for alert in snapshot.explosionAlerts or []:
        if str(alert.get("side") or "").upper() != side:
            continue
        score = _number(alert.get("explosionScore"))
        if alert.get("ictFirstLift") or alert.get("firstLift") or alert.get("flatThenVertical"):
            score += 8.0
        support = max(support, min(100.0, score))
    return support


def estimate_live_probabilities(
    profile: Mapping[str, Any],
    live_rows: Iterable[Any],
    snapshot: SymbolSnapshot,
) -> dict[str, Any]:
    """Blend historical priors with live base, chart, breadth, and radar proof."""
    settings = get_settings()
    candles = _latest_session(_market_candles(normalize_candles(live_rows)))
    base_window = max(3, int(settings.ftv_probability_base_window_minutes))
    if len(candles) < base_window:
        return {
            "status": "WAITING_LIVE_CANDLES",
            "liveReady": False,
            "dominantSide": "NEUTRAL",
            "reason": f"Need {base_window} current-session one-minute candles",
        }

    recent = candles[-base_window:]
    close = recent[-1]["close"]
    base_range = (
        (max(c["high"] for c in recent) - min(c["low"] for c in recent))
        / close
        * 100.0
    )
    local_base_ready = base_range <= float(settings.ftv_probability_flat_max_range_pct)
    bucket = _bucket_label(
        recent[-1]["ts"],
        max(5, int(settings.ftv_probability_time_bucket_minutes)),
    )
    momentum_ref = candles[-4]["close"] if len(candles) >= 4 else recent[0]["close"]
    momentum3 = (close - momentum_ref) / momentum_ref * 100.0 if momentum_ref else 0.0
    prior_volumes = [c["volume"] for c in candles[-21:-1] if c["volume"] > 0]
    volume_ratio = (
        recent[-1]["volume"] / (sum(prior_volumes) / len(prior_volumes))
        if prior_volumes and recent[-1]["volume"] > 0
        else 1.0
    )
    chart_direction = str(snapshot.spotChart.direction or "NEUTRAL").upper()
    breadth_bias = str(snapshot.breadth.bias or "NEUTRAL").upper()

    estimates: dict[str, Any] = {}
    for side in ("CALL", "PUT"):
        side_direction = "BULLISH" if side == "CALL" else "BEARISH"
        support = _alert_support(snapshot, side)
        probabilities: dict[str, float] = {}
        sample_counts: dict[str, int] = {}
        for horizon in HORIZONS:
            bucket_row = (
                (profile.get("buckets") or {}).get(bucket, {})
                .get(side, {})
                .get(str(horizon))
            )
            global_row = (
                (profile.get("rates") or {}).get(side, {}).get(str(horizon), {})
            )
            source_row = bucket_row if bucket_row and bucket_row.get("samples", 0) >= 3 else global_row
            probability = _number(source_row.get("probabilityPct")) if source_row else 0.0
            sample_counts[str(horizon)] = int(_number(source_row.get("samples"))) if source_row else 0

            probability *= 1.18 if local_base_ready else 0.62
            directional_momentum = momentum3 if side == "CALL" else -momentum3
            probability += max(-8.0, min(8.0, directional_momentum * 28.0))
            if chart_direction == side_direction:
                probability += 5.0
            elif chart_direction not in ("NEUTRAL", side_direction):
                probability -= 5.0
            if breadth_bias == side_direction:
                probability += 4.0
            elif breadth_bias not in ("NEUTRAL", side_direction):
                probability -= 4.0
            probability += max(0.0, min(6.0, (volume_ratio - 1.0) * 4.0))
            probability += support * 0.12
            probabilities[str(horizon)] = round(max(1.0, min(95.0, probability)), 1)

        earliest = next(
            (h for h in HORIZONS if probabilities[str(h)] >= 35.0),
            max(HORIZONS, key=lambda h: probabilities[str(h)]),
        )
        estimates[side] = {
            "probabilities": probabilities,
            "sampleCounts": sample_counts,
            "earliestLikelyMinutes": earliest,
            "radarSupport": round(support, 1),
        }

    call_peak = max(estimates["CALL"]["probabilities"].values())
    put_peak = max(estimates["PUT"]["probabilities"].values())
    dominant = (
        "CALL" if call_peak >= 20 and call_peak >= put_peak + 5
        else "PUT" if put_peak >= 20 and put_peak >= call_peak + 5
        else "NEUTRAL"
    )
    max_samples = max(
        estimates[side]["sampleCounts"][str(h)]
        for side in ("CALL", "PUT")
        for h in HORIZONS
    )
    confidence = (
        "HIGH" if max_samples >= 250 and local_base_ready
        else "MEDIUM" if max_samples >= 100
        else "LOW"
    )
    return {
        "status": "READY",
        "liveReady": True,
        "asOf": recent[-1]["ts"].isoformat(),
        "timeBucket": bucket,
        "baseRangePct": round(base_range, 4),
        "localBaseReady": local_base_ready,
        "momentum3Pct": round(momentum3, 4),
        "volumeRatio": round(volume_ratio, 2),
        "dominantSide": dominant,
        "confidence": confidence,
        "estimatedWindow": (
            f"{estimates[dominant]['earliestLikelyMinutes']}m"
            if dominant in estimates else None
        ),
        "sides": estimates,
    }


async def _load_symbol_profile(
    symbol: str,
    client: UpstoxClient,
    *,
    force: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    settings = get_settings()
    now = datetime.now(IST)
    cache_seconds = max(60, int(settings.ftv_probability_profile_cache_seconds))
    cached = _profile_cache.get(symbol)
    if not force and cached and time.monotonic() - cached[0] < cache_seconds:
        return cached[1], cached[2]

    lock = _profile_locks.setdefault(symbol, asyncio.Lock())
    async with lock:
        cached = _profile_cache.get(symbol)
        if not force and cached and time.monotonic() - cached[0] < cache_seconds:
            return cached[1], cached[2]
        instrument_key = INDEX_KEYS[symbol]
        history_days = max(7, min(31, int(settings.ftv_probability_history_days)))
        to_date = now.date().isoformat()
        from_date = (now.date() - timedelta(days=history_days)).isoformat()
        historical_raw, intraday_raw = await asyncio.gather(
            client.get_historical_candles_v3(
                instrument_key,
                unit="minutes",
                interval=1,
                to_date=to_date,
                from_date=from_date,
                force_refresh=force,
            ),
            client.get_intraday_candles_v3(
                instrument_key,
                unit="minutes",
                interval=1,
                force_refresh=force,
            ),
        )
        historical = normalize_candles(historical_raw)
        # Never train on today's partial session.
        training = [c for c in historical if c["ts"].date() < now.date()]
        profile = build_historical_profile(
            training,
            base_window=max(3, int(settings.ftv_probability_base_window_minutes)),
            bucket_minutes=max(5, int(settings.ftv_probability_time_bucket_minutes)),
            flat_max_range_pct=float(settings.ftv_probability_flat_max_range_pct),
            vertical_move_pct=float(settings.ftv_probability_vertical_move_pct),
        )
        profile.update({
            "symbol": symbol,
            "instrumentKey": instrument_key,
            "source": "upstox_v3_index_1m",
            "trainedAt": now.isoformat(),
        })
        intraday = normalize_candles(intraday_raw)
        _profile_cache[symbol] = (time.monotonic(), profile, intraday)
        return profile, intraday


async def build_ftv_probability_dashboard(
    snapshots: Mapping[str, SymbolSnapshot],
    *,
    client: Optional[UpstoxClient] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Build NIFTY/SENSEX historical priors and live time-to-breakout estimates."""
    settings = get_settings()
    now = datetime.now(IST)
    if not settings.ftv_probability_enabled:
        return {"enabled": False, "status": "DISABLED", "symbols": {}}
    client = client or UpstoxClient()
    symbols = list(dict.fromkeys(
        symbol.upper()
        for symbol in [*snapshots.keys(), *settings.symbols]
        if symbol.upper() in INDEX_KEYS
    ))

    async def build_one(symbol: str) -> tuple[str, dict[str, Any]]:
        snapshot = snapshots.get(symbol) or SymbolSnapshot(
            symbol=symbol,
            timestamp=now,
            marketPhase=MarketPhase.CLOSED,
            dataAvailable=False,
        )
        try:
            profile, intraday = await _load_symbol_profile(symbol, client, force=force)
            minimum = max(1, int(settings.ftv_probability_min_training_samples))
            history_ready = int(profile.get("baseSamples") or 0) >= minimum
            live = estimate_live_probabilities(profile, intraday, snapshot)
            return symbol, {
                "status": "READY" if history_ready else "LEARNING",
                "historyReady": history_ready,
                "source": profile.get("source"),
                "instrumentBasis": "INDEX_SPOT_PROXY",
                "optionHistory": "UPSTOX_PLUS_REQUIRED_FOR_EXPIRED_OPTIONS",
                "profile": {
                    key: profile.get(key)
                    for key in (
                        "trainedAt", "sessionCount", "candleCount", "baseSamples",
                        "fromDate", "toDate", "averageBaseRangePct",
                        "flatMaxRangePct", "verticalMovePct", "timeOfDayLeaders",
                    )
                },
                "live": live,
            }
        except Exception as exc:
            return symbol, {
                "status": "UNAVAILABLE",
                "historyReady": False,
                "error": str(exc)[:240],
                "source": "upstox_v3_index_1m",
            }

    results = await asyncio.gather(*(build_one(symbol) for symbol in symbols))
    payload = dict(results)
    live_rows = [
        (symbol, row.get("live") or {})
        for symbol, row in payload.items()
        if (row.get("live") or {}).get("liveReady")
    ]
    dominant = max(
        live_rows,
        key=lambda pair: max(
            max((pair[1].get("sides") or {}).get(side, {}).get("probabilities", {}).values(), default=0)
            for side in ("CALL", "PUT")
        ),
        default=None,
    )
    return {
        "enabled": True,
        "status": (
            "LIVE" if live_rows
            else "HISTORICAL_READY" if any(row.get("historyReady") for row in payload.values())
            else "UNAVAILABLE"
        ),
        "generatedAt": now.isoformat(),
        "symbols": payload,
        "topLiveSymbol": dominant[0] if dominant else None,
        "guardrail": (
            "Historical probability is advisory only; a trade still requires live "
            "premium, volume, orderflow, liquidity, and local-base confirmation."
        ),
        "limitations": (
            "Standard Upstox V3 index history is the directional proxy. Exact expired "
            "option-premium backtests require the Upstox Plus Expired Instruments APIs."
        ),
    }
