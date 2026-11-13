"""Unit tests for multi-year index analysis helpers."""

from datetime import date

from app.engines.upstox_years_analysis import (
    analyze_daily_years,
    iter_day_chunks,
    iter_minute_chunks,
)


def test_iter_minute_chunks_28_day_cap():
    chunks = list(iter_minute_chunks(date(2022, 1, 1), date(2022, 3, 15), max_days=28))
    assert len(chunks) >= 2
    assert chunks[0][0] == date(2022, 1, 1)


def test_iter_day_chunks_covers_range():
    chunks = list(iter_day_chunks(date(2010, 1, 1), date(2015, 6, 1), max_days=3650))
    assert chunks[0][0] == date(2010, 1, 1)
    assert chunks[-1][1] == date(2015, 6, 1)


def test_analyze_daily_years_minimal():
    candles = [
        {
            "ts": __import__("datetime").datetime(2020, 1, 2, 15, 30),
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1.0,
        },
        {
            "ts": __import__("datetime").datetime(2020, 1, 3, 15, 30),
            "open": 101.0,
            "high": 103.0,
            "low": 100.0,
            "close": 100.5,
            "volume": 1.0,
        },
    ]
    out = analyze_daily_years(candles)
    assert out["status"] == "OK"
    assert out["candleCount"] == 2
    assert "2020" in out["annual"]
