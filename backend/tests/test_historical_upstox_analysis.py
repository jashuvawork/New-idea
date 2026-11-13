"""Unit tests for historical Upstox setup analysis (no live API)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.engines.historical_upstox_analysis import (
    _index_session_stats,
    _parse_anchor_ist,
    _session_filter,
    _to_ohlcv_rows,
    _until_anchor,
    build_mtf_reads_from_1m,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _candle(h: int, m: int, o: float, c: float) -> dict:
    ts = datetime(2026, 11, 13, h, m, tzinfo=IST)
    return {
        "ts": ts,
        "open": o,
        "high": max(o, c) + 1,
        "low": min(o, c) - 1,
        "close": c,
        "volume": 1000.0,
    }


def test_parse_anchor_and_slice():
    anchor = _parse_anchor_ist("2026-11-13", "10:50:00")
    candles = [_candle(9, 15, 100, 101), _candle(10, 50, 102, 103)]
    session = _session_filter(candles)
    assert len(session) == 2
    sliced = _until_anchor(session, anchor)
    assert len(sliced) == 2
    assert sliced[-1]["close"] == 103


def test_mtf_reads_from_synthetic_uptrend():
    base = 24_000.0
    candles = [
        _candle(9, 15 + i, base + i, base + i + 2) for i in range(40)
    ]
    reads = build_mtf_reads_from_1m(candles, candles[-1]["close"])
    assert "1m" in reads and "5m" in reads
    assert reads["1m"].direction in ("BULLISH", "NEUTRAL", "BEARISH")


def test_index_session_stats_off_low():
    candles = [
        _candle(9, 15, 100, 100),
        _candle(9, 20, 99, 98),
        _candle(10, 0, 98, 102),
    ]
    stats = _index_session_stats(candles)
    assert stats["sessionLow"] == 97.0  # low of bar 2
    assert stats["offSessionLowPct"] > 0
    rows = _to_ohlcv_rows(candles)
    assert len(rows[0]) == 6
