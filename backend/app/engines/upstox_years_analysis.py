"""Pull multi-year index history (Upstox V3) and fit Nexus FTV-style profiles."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.ftv_probability import build_historical_profile, normalize_candles
from app.services.upstox import INDEX_KEYS, UpstoxClient, UpstoxError

IST = ZoneInfo("Asia/Kolkata")

YAHOO_INDEX = {
    "NIFTY": "^NSEI",
    "SENSEX": "^BSESN",
    "BANKNIFTY": "^NSEBANK",
}


def _parse_ymd(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def iter_day_chunks(
    start: date,
    end: date,
    *,
    max_days: int = 3650,
) -> Iterator[tuple[date, date]]:
    """Chunk inclusive ranges for Upstox daily candles (max ~10 years per call)."""
    cur = start
    while cur <= end:
        chunk_end = min(end, cur + timedelta(days=max_days - 1))
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def iter_minute_chunks(
    start: date,
    end: date,
    *,
    max_days: int = 28,
) -> Iterator[tuple[date, date]]:
    cur = start
    while cur <= end:
        chunk_end = min(end, cur + timedelta(days=max_days - 1))
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


async def fetch_upstox_candles(
    client: UpstoxClient,
    symbol: str,
    *,
    unit: str,
    interval: int,
    from_date: date,
    to_date: date,
    pause_s: float = 0.35,
) -> list[dict[str, Any]]:
    key = INDEX_KEYS.get(symbol.upper())
    if not key:
        raise ValueError(f"Unknown symbol: {symbol}")
    merged: dict[datetime, dict[str, Any]] = {}
    chunk_iter = (
        iter_day_chunks(from_date, to_date, max_days=3650)
        if unit == "days"
        else iter_minute_chunks(from_date, to_date, max_days=28)
    )
    chunks = list(chunk_iter)
    for i, (lo, hi) in enumerate(chunks):
        rows = await client.get_historical_candles_v3(
            key,
            unit=unit,
            interval=interval,
            to_date=hi.isoformat(),
            from_date=lo.isoformat(),
            force_refresh=True,
        )
        for row in normalize_candles(rows):
            merged[row["ts"]] = row
        if pause_s > 0 and i + 1 < len(chunks):
            await asyncio.sleep(pause_s)
    return [merged[k] for k in sorted(merged)]


def yahoo_daily_candles(
    symbol: str,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Long daily history via Yahoo (research fallback when Upstox OAuth missing)."""
    import yfinance as yf

    ticker = YAHOO_INDEX.get(symbol.upper())
    if not ticker:
        raise ValueError(f"No Yahoo mapping for {symbol}")
    tk = yf.Ticker(ticker)
    if start or end:
        df = tk.history(start=start, end=end, interval="1d")
    else:
        df = tk.history(period="max", interval="1d")
    if df.empty:
        return []
    if df.index.tz is None:
        df = df.tz_localize("UTC")
    df = df.tz_convert(IST)
    out: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        v = float(row.get("Volume") or 0)
        if min(o, h, l, c) <= 0:
            continue
        local = ts.astimezone(IST).replace(hour=15, minute=30, second=0, microsecond=0)
        out.append(
            {
                "ts": local,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
    return out


def analyze_daily_years(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Macro stats on daily bars (not intraday FTV)."""
    if not candles:
        return {"status": "EMPTY"}
    by_year: dict[int, list[float]] = {}
    ranges: list[float] = []
    for c in candles:
        yr = c["ts"].year
        ret = (c["close"] - c["open"]) / c["open"] * 100 if c["open"] else 0
        by_year.setdefault(yr, []).append(ret)
        if c["open"]:
            ranges.append((c["high"] - c["low"]) / c["open"] * 100)
    annual = {}
    for yr, rets in sorted(by_year.items()):
        annual[str(yr)] = {
            "sessions": len(rets),
            "avgDayReturnPct": round(sum(rets) / len(rets), 3),
            "greenDaysPct": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
        }
    return {
        "status": "OK",
        "candleCount": len(candles),
        "fromDate": candles[0]["ts"].date().isoformat(),
        "toDate": candles[-1]["ts"].date().isoformat(),
        "avgRangePct": round(sum(ranges) / len(ranges), 3) if ranges else 0,
        "annual": annual,
    }


def analyze_minute_profile(
    candles: list[dict[str, Any]],
    *,
    symbol: str,
) -> dict[str, Any]:
    settings = get_settings()
    profile = build_historical_profile(
        candles,
        base_window=max(3, int(settings.ftv_probability_base_window_minutes)),
        bucket_minutes=max(5, int(settings.ftv_probability_time_bucket_minutes)),
        flat_max_range_pct=float(settings.ftv_probability_flat_max_range_pct),
        vertical_move_pct=float(settings.ftv_probability_vertical_move_pct),
    )
    profile["symbol"] = symbol.upper()
    return profile


async def run_years_analysis(
    *,
    symbol: str = "NIFTY",
    minute_from: str = "2022-01-01",
    minute_to: Optional[str] = None,
    include_yahoo_daily: bool = True,
    include_upstox_minutes: bool = True,
    max_minute_chunks: Optional[int] = None,
    out_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Pull long history and return merged analysis report."""
    symbol = symbol.upper()
    end = _parse_ymd(minute_to or date.today().isoformat())
    start = _parse_ymd(minute_from)
    report: dict[str, Any] = {
        "symbol": symbol,
        "generatedAt": datetime.now(IST).isoformat(),
        "minuteRange": {"from": start.isoformat(), "to": end.isoformat()},
    }

    if include_yahoo_daily:
        daily = yahoo_daily_candles(symbol)
        report["yahooDaily"] = analyze_daily_years(daily)
        report["sources"] = report.get("sources", []) + ["yahoo_daily_max"]

    if include_upstox_minutes:
        client = UpstoxClient()
        try:
            chunks = list(iter_minute_chunks(start, end))
            if max_minute_chunks is not None:
                chunks = chunks[: max(1, max_minute_chunks)]
                eff_end = chunks[-1][1]
            else:
                eff_end = end
            report["minuteRange"]["toEffective"] = eff_end.isoformat()
            report["minuteChunks"] = len(chunks)
            candles = await fetch_upstox_candles(
                client,
                symbol,
                unit="minutes",
                interval=1,
                from_date=chunks[0][0],
                to_date=eff_end,
            )
            report["upstoxMinutes"] = {
                "candleCount": len(candles),
                "from": candles[0]["ts"].isoformat() if candles else None,
                "to": candles[-1]["ts"].isoformat() if candles else None,
                "profile": analyze_minute_profile(candles, symbol=symbol),
            }
            report["sources"] = report.get("sources", []) + ["upstox_v3_1m"]
        except UpstoxError as exc:
            report["upstoxMinutesError"] = str(exc)

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"years_analysis_{symbol.lower()}.json"
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        report["artifactPath"] = str(path)

    return report
