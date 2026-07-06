"""Execution-time Upstox chart monitor — fresh fetch before order."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.engines.execution_chart_monitor import (
    fetch_live_trade_charts,
    monitor_trade_chart_before_execution,
    validate_execution_charts,
)
from app.engines.mtf_chart_analysis import resample_candles
from app.models.schemas import (
    Breadth,
    PremiumChart,
    Side,
    SpotChart,
    SymbolSnapshot,
)
from tests.test_spot_direction import _declining_candles, _rising_candles


def _snap(chart: SpotChart) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2025-06-30T10:00:00",
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        tradeQualityScore=60,
        regime="TREND_EXPANSION",
        spot=chart.spot,
        breadth=Breadth(score=50, bias="NEUTRAL", aligned=False),
        spotChart=chart,
    )


def _settings():
    s = MagicMock()
    s.execution_chart_gate_enabled = True
    s.execution_chart_force_upstox_refresh = True
    s.execution_chart_premium_check_enabled = True
    s.execution_chart_min_premium_momentum_pct = -0.35
    s.execution_chart_candle_count = 60
    s.spot_chart_timeframe_minutes = 5
    s.spot_chart_1m_bars = 300
    s.execution_mtf_enabled = True
    s.execution_mtf_use_v3_native = False
    s.execution_mtf_1m_bars = 300
    s.execution_mtf_min_align = 3
    s.execution_mtf_block_htf_conflict = True
    s.chart_alignment_enabled = True
    s.chart_min_trend_strength = 25.0
    s.chart_min_momentum_pct = 0.04
    s.chart_override_min_score = 75
    return s


def test_validate_execution_blocks_call_on_bearish_index():
    chart = SpotChart(
        direction="BEARISH",
        momentum5Pct=-0.12,
        momentum15Pct=-0.18,
        trendStrength=40,
        orPosition="BELOW",
        belowPoc=True,
    )
    ok, reason, _ = validate_execution_charts(Side.CALL, chart, trade_score=60)
    assert not ok
    assert reason.startswith("exec_chart_")


def test_validate_execution_blocks_fading_premium():
    index = SpotChart(direction="NEUTRAL", momentum5Pct=0.01, momentum15Pct=0.0, trendStrength=10)
    premium = PremiumChart(direction="BEARISH", momentum5Pct=-0.5, momentum3Pct=-0.3)
    ok, reason, _ = validate_execution_charts(
        Side.CALL, index, premium_chart=premium, trade_score=60,
    )
    assert not ok
    assert "premium" in reason


def test_monitor_fetches_upstox_and_blocks_counter_chart():
    with patch("app.engines.execution_chart_monitor.get_settings") as mock_settings:
        mock_settings.return_value = _settings()
        candles = _declining_candles()
        spot = candles[-1][4]
        snap = _snap(SpotChart(direction="BULLISH", momentum5Pct=0.05))

        client = AsyncMock()
        client.get_index_quote = AsyncMock(return_value={
            "last_price": spot,
            "ohlc": {"open": spot + 1, "high": spot + 2, "low": spot - 2},
            "close": spot + 1,
        })
        client.get_candles = AsyncMock(return_value=candles)
        client.get_historical_candles = AsyncMock(return_value=candles)
        client.get_full_quotes = AsyncMock(return_value={
            "NSE_FO|OPT": {"last_price": 85.0, "ltp": 85.0},
        })
        candles_5m = resample_candles(candles, 5)
        with patch(
            "app.engines.execution_chart_monitor.fetch_index_chart_candles",
            AsyncMock(return_value=(candles_5m, candles)),
        ):
            passed, reason, meta = asyncio.run(monitor_trade_chart_before_execution(
                client,
                "NIFTY",
                Side.CALL,
                23900,
                snap,
                trade_score=62,
                instrument_key="NSE_FO|OPT",
            ))

        assert meta["source"] == "upstox_live"
        assert meta["indexChart"]["direction"] == "BEARISH"
        assert not passed
        assert reason.startswith("exec_")


def test_monitor_passes_aligned_put_on_decline():
    with patch("app.engines.execution_chart_monitor.get_settings") as mock_settings:
        mock_settings.return_value = _settings()
        candles = _declining_candles()
        spot = candles[-1][4]
        snap = _snap(SpotChart(direction="BEARISH"))

        client = AsyncMock()
        client.get_index_quote = AsyncMock(return_value={
            "last_price": spot,
            "ohlc": {"open": spot + 1, "high": spot + 2, "low": spot - 2},
            "close": spot + 1,
        })
        client.get_candles = AsyncMock(return_value=candles)
        async def hist_side_effect(key, **kwargs):
            if "FO" in str(key):
                return _rising_candles(start=80)
            return candles

        client.get_historical_candles = AsyncMock(side_effect=hist_side_effect)
        client.get_full_quotes = AsyncMock(return_value={
            "NSE_FO|OPT": {"last_price": 90.0},
        })
        candles_5m = resample_candles(candles, 5)
        with patch(
            "app.engines.execution_chart_monitor.fetch_index_chart_candles",
            AsyncMock(return_value=(candles_5m, candles)),
        ):
            passed, reason, meta = asyncio.run(monitor_trade_chart_before_execution(
                client, "NIFTY", Side.PUT, 23900, snap, trade_score=65, instrument_key="NSE_FO|OPT",
            ))
        assert passed
        assert reason == "ok"
        assert meta["alignedWithChart"] is True


def test_fetch_live_trade_charts_includes_quote_context():
    with patch("app.engines.execution_chart_monitor.get_settings") as mock_settings:
        mock_settings.return_value = _settings()
        candles = _rising_candles()
        spot = candles[-1][4]

        client = AsyncMock()
        client.get_index_quote = AsyncMock(return_value={
            "last_price": spot,
            "ohlc": {"open": spot - 1, "high": spot + 1, "low": spot - 2},
            "close": spot - 0.5,
        })
        client.get_candles = AsyncMock(return_value=candles)
        candles_5m = resample_candles(candles, 5)
        with patch(
            "app.engines.execution_chart_monitor.fetch_index_chart_candles",
            AsyncMock(return_value=(candles_5m, candles)),
        ):
            meta = asyncio.run(fetch_live_trade_charts(
                client, "NIFTY", Side.CALL, 24000, _snap(SpotChart()), instrument_key=None,
            ))
        assert meta["quoteContext"]["dayOpen"] > 0
        assert meta["indexChart"]["direction"] == "BULLISH"
