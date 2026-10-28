"""Execution chart fallback still runs cash-candle rollover from snapshot cache."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.execution_chart_monitor import index_candle_rollover_gate, monitor_trade_chart_before_execution
from app.engines.index_chart_candles import remember_snapshot_index_candles
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 23, 9, 28, 20, tzinfo=IST)


def _bar(minute: int, open_: float, high: float, low: float, close: float) -> list:
    ts = datetime(2026, 10, 23, 9, minute, tzinfo=IST).isoformat()
    return [ts, open_, high, low, close, 0]


def test_index_candle_gate_uses_snapshot_cache():
    candles = [
        _bar(26, 22760, 22761, 22752, 22754),
        _bar(27, 22754, 22755, 22746, 22748),
        _bar(28, 22748, 22749, 22744, 22746),
    ]
    remember_snapshot_index_candles("NIFTY", [], candles)
    s = Settings()
    blocked, reason, meta = index_candle_rollover_gate(
        Side.CALL,
        symbol="NIFTY",
        spot=22745.0,
        settings=s,
        now=NOW,
    )
    assert blocked is True
    assert reason == "index_falling_from_local_high"
    assert meta.get("timeframe") == "1m"


def test_monitor_fallback_applies_cash_candle_before_snapshot_chart():
    candles = [
        _bar(26, 22760, 22761, 22752, 22754),
        _bar(27, 22754, 22755, 22746, 22748),
        _bar(28, 22748, 22749, 22744, 22746),
    ]
    remember_snapshot_index_candles("NIFTY", [], candles)
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=NOW,
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=22745.0,
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.1,
            trendStrength=50,
            emaBias="BULLISH",
            candleBias="BULLISH",
            macdBias="BULLISH",
        ),
    )
    client = AsyncMock()

    async def _run():
        with patch(
            "app.engines.execution_chart_monitor.fetch_live_trade_charts",
            side_effect=RuntimeError("upstox timeout"),
        ):
            def _gate_with_fixed_open(*args, **kwargs):
                kwargs["now"] = NOW
                return index_candle_rollover_gate(*args, **kwargs)

            with patch(
                "app.engines.execution_chart_monitor.index_candle_rollover_gate",
                side_effect=_gate_with_fixed_open,
            ) as gate:
                return await monitor_trade_chart_before_execution(
                    client,
                    "NIFTY",
                    Side.CALL,
                    22700.0,
                    snap,
                    trade_score=80.0,
                ), gate

    (ok, reason, meta), gate = asyncio.run(_run())
    assert ok is False
    assert reason == "exec_index_falling_from_local_high"
    assert meta.get("source") == "snapshot_fallback"
    assert "indexCandleRollover" in meta
    assert gate.called
