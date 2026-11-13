"""Tests for five-year Upstox store and window helpers."""

from datetime import date
from pathlib import Path

from app.engines.upstox_five_year_pipeline import five_year_window
from app.engines.upstox_history_store import (
    chunk_path,
    history_root,
    load_all_minute_candles,
    write_chunk,
)


def test_five_year_window_clamps_minutes_to_2022():
    daily_from, daily_to, minute_from, minute_to = five_year_window(
        years=5, as_of=date(2026, 11, 13)
    )
    assert daily_from < date(2022, 1, 1)
    assert minute_from == date(2022, 1, 1)
    assert minute_to == date(2026, 11, 13)


def test_chunk_roundtrip(tmp_path: Path):
    root = history_root(tmp_path, "NIFTY")
    lo, hi = date(2024, 1, 1), date(2024, 1, 28)
    candles = [
        {
            "ts": __import__("datetime").datetime(2024, 1, 2, 9, 15, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Kolkata")),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
        }
    ]
    path = chunk_path(root, lo, hi)
    write_chunk(path, candles)
    loaded = load_all_minute_candles(root)
    assert len(loaded) == 1
    assert loaded[0]["close"] == 100.5
