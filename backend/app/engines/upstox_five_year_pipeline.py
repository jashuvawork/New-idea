"""Download ~5 years of Upstox index data on EC2 and run full Nexus-aligned analysis."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.ftv_probability import normalize_candles
from app.engines.upstox_history_store import (
    chunk_path,
    history_root,
    load_all_minute_candles,
    load_manifest,
    read_job_status,
    save_manifest,
    write_chunk,
    write_job_status,
)
from app.engines.upstox_years_analysis import (
    analyze_daily_years,
    analyze_minute_profile,
    fetch_upstox_candles,
    iter_minute_chunks,
)
from app.services.upstox import INDEX_KEYS, UpstoxClient, UpstoxError

IST = ZoneInfo("Asia/Kolkata")
UPSTOX_MINUTE_EARLIEST = date(2022, 1, 1)


def five_year_window(
    *,
    years: int = 5,
    as_of: Optional[date] = None,
) -> tuple[date, date, date, date]:
    """Return (daily_from, daily_to, minute_from, minute_to) for a 5y study."""
    end = as_of or datetime.now(IST).date()
    daily_from = end - timedelta(days=int(years * 365.25))
    minute_from = max(UPSTOX_MINUTE_EARLIEST, daily_from)
    return daily_from, end, minute_from, end


async def download_minute_chunks_resumable(
    client: UpstoxClient,
    symbol: str,
    store_root: Path,
    *,
    minute_from: date,
    minute_to: date,
    resume: bool = True,
    on_progress: Optional[Any] = None,
) -> dict[str, Any]:
    """Fetch 1m candles in 28-day chunks; skip completed chunk files when resume=True."""
    settings = get_settings()
    pause_s = max(0.2, settings.upstox_min_request_interval_ms / 1000.0)
    chunks = list(iter_minute_chunks(minute_from, minute_to))
    stats = {
        "totalChunks": len(chunks),
        "downloaded": 0,
        "skipped": 0,
        "failed": [],
        "bytesWritten": 0,
    }
    key = INDEX_KEYS.get(symbol.upper(), "")

    for i, (lo, hi) in enumerate(chunks):
        dest = chunk_path(store_root, lo, hi)
        if resume and dest.is_file() and dest.stat().st_size > 0:
            stats["skipped"] += 1
            if on_progress:
                on_progress(i + 1, len(chunks), "skipped", lo, hi)
            continue
        try:
            rows = await client.get_historical_candles_v3(
                key,
                unit="minutes",
                interval=1,
                to_date=hi.isoformat(),
                from_date=lo.isoformat(),
                force_refresh=True,
            )
            candles = normalize_candles(rows)
            nbytes = write_chunk(dest, candles)
            stats["downloaded"] += 1
            stats["bytesWritten"] += nbytes
            if on_progress:
                on_progress(i + 1, len(chunks), "ok", lo, hi, len(candles))
        except (UpstoxError, ValueError) as exc:
            stats["failed"].append({"from": lo.isoformat(), "to": hi.isoformat(), "error": str(exc)})
            if on_progress:
                on_progress(i + 1, len(chunks), "error", lo, hi, str(exc))
        if pause_s > 0 and i + 1 < len(chunks):
            await asyncio.sleep(pause_s)

    return stats


async def run_five_year_pipeline(
    *,
    symbol: str = "NIFTY",
    years: int = 5,
    resume: bool = True,
    store_dir: Optional[Path] = None,
    analyze: bool = True,
) -> dict[str, Any]:
    """Full pull + analysis. Intended for EC2 (live Upstox token)."""
    settings = get_settings()
    base = store_dir or Path(settings.trade_store_dir)
    root = history_root(base, symbol)
    daily_from, daily_to, minute_from, minute_to = five_year_window(years=years)

    write_job_status(
        root,
        {
            "status": "running",
            "phase": "download_minutes",
            "symbol": symbol.upper(),
            "years": years,
            "minuteFrom": minute_from.isoformat(),
            "minuteTo": minute_to.isoformat(),
        },
    )

    client = UpstoxClient()
    report: dict[str, Any] = {
        "symbol": symbol.upper(),
        "generatedAt": datetime.now(IST).isoformat(),
        "storeRoot": str(root),
        "window": {
            "years": years,
            "dailyFrom": daily_from.isoformat(),
            "dailyTo": daily_to.isoformat(),
            "minuteFrom": minute_from.isoformat(),
            "minuteTo": minute_to.isoformat(),
            "minuteNote": "Upstox 1m history starts 2022-01-01",
        },
    }

    def progress(done: int, total: int, state: str, lo: date, hi: date, extra: Any = None) -> None:
        write_job_status(
            root,
            {
                "status": "running",
                "phase": "download_minutes",
                "progress": f"{done}/{total}",
                "lastChunk": {"from": lo.isoformat(), "to": hi.isoformat(), "state": state, "detail": extra},
            },
        )

    try:
        minute_stats = await download_minute_chunks_resumable(
            client,
            symbol,
            root,
            minute_from=minute_from,
            minute_to=minute_to,
            resume=resume,
            on_progress=progress,
        )
        report["minuteDownload"] = minute_stats

        write_job_status(root, {"status": "running", "phase": "download_daily"})
        daily_candles = await fetch_upstox_candles(
            client,
            symbol,
            unit="days",
            interval=1,
            from_date=daily_from,
            to_date=daily_to,
        )
        report["upstoxDaily5y"] = analyze_daily_years(daily_candles)
        daily_path = root / "daily_5y.jsonl"
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        with daily_path.open("w", encoding="utf-8") as fh:
            for c in daily_candles:
                ts = c["ts"].isoformat()
                fh.write(
                    json.dumps(
                        {
                            "ts": ts,
                            "open": c["open"],
                            "high": c["high"],
                            "low": c["low"],
                            "close": c["close"],
                            "volume": c.get("volume", 0),
                        }
                    )
                    + "\n"
                )
        report["dailyArtifact"] = str(daily_path)

        if analyze:
            write_job_status(root, {"status": "running", "phase": "analyze_minutes"})
            candles = load_all_minute_candles(root)
            report["minuteCandlesLoaded"] = len(candles)
            if candles:
                report["upstoxMinuteProfile"] = analyze_minute_profile(candles, symbol=symbol)
                report["minuteRangeLoaded"] = {
                    "from": candles[0]["ts"].isoformat(),
                    "to": candles[-1]["ts"].isoformat(),
                }

        save_manifest(
            root,
            {
                "symbol": symbol.upper(),
                "lastRun": report["generatedAt"],
                "minuteDownload": minute_stats,
                "years": years,
            },
        )

        analysis_path = root / f"analysis_{years}y.json"
        analysis_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        report["analysisArtifact"] = str(analysis_path)

        write_job_status(root, {"status": "completed", "analysisArtifact": str(analysis_path)})
        report["status"] = "completed"
        return report
    except Exception as exc:
        write_job_status(root, {"status": "failed", "error": str(exc)})
        report["status"] = "failed"
        report["error"] = str(exc)
        raise


def get_five_year_job_status(symbol: str, store_dir: Optional[Path] = None) -> dict[str, Any]:
    settings = get_settings()
    base = store_dir or Path(settings.trade_store_dir)
    root = history_root(base, symbol)
    status = read_job_status(root)
    status["storeRoot"] = str(root)
    status["manifest"] = load_manifest(root)
    analysis = root / "analysis_5y.json"
    if analysis.is_file():
        status["analysisArtifact"] = str(analysis)
    return status
