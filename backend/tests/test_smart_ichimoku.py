"""GainzAlgo-style Smart Ichimoku — HMA cloud + break probability."""

from unittest.mock import MagicMock, patch

from app.engines.smart_ichimoku import (
    compute_smart_ichimoku,
    ichimoku_break_supports_side,
)
from app.engines.chart_advanced_analysis import compute_ichimoku
from app.models.schemas import (
    Breadth,
    ChartAnalysis,
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _uptrend(n: int = 90):
    highs = [100 + i * 0.5 for i in range(n)]
    lows = [99 + i * 0.5 for i in range(n)]
    closes = [99.5 + i * 0.5 for i in range(n)]
    return highs, lows, closes


def _downtrend(n: int = 90):
    highs = [150 - i * 0.45 for i in range(n)]
    lows = [148 - i * 0.45 for i in range(n)]
    closes = [149 - i * 0.45 for i in range(n)]
    return highs, lows, closes


def _settings(**kw):
    s = MagicMock()
    s.smart_ichimoku_use_hma = True
    s.smart_ichimoku_tenkan_period = 9
    s.smart_ichimoku_kijun_period = 26
    s.smart_ichimoku_senkou_b_period = 52
    s.smart_ichimoku_displacement = 26
    s.smart_ichimoku_break_min_probability = 0.60
    s.smart_ichimoku_continuation_min_probability = 0.55
    s.smart_ichimoku_flat_vertical_confirm_enabled = True
    s.smart_ichimoku_weight_rsi = 0.85
    s.smart_ichimoku_weight_stoch = 0.65
    s.smart_ichimoku_weight_zscore = 0.90
    s.smart_ichimoku_weight_depth = 1.10
    for k, v in kw.items():
        setattr(s, k, v)
    return s


@patch("app.engines.smart_ichimoku.get_settings")
def test_hma_uptrend_break_fields(mock_gs):
    mock_gs.return_value = _settings()
    h, l, c = _uptrend()
    ich = compute_smart_ichimoku(h, l, c, c[-1])
    assert ich["engine"] == "hma_logistic"
    assert ich["priceVsCloud"] == "ABOVE"
    assert ich["breakSide"] == "BULLISH"
    assert "breakProbability" in ich
    assert 0.0 <= ich["breakProbability"] <= 1.0
    assert ich["smartBias"] in ("BULLISH", "NEUTRAL", "BEARISH")


@patch("app.engines.smart_ichimoku.get_settings")
def test_hma_downtrend_break_side(mock_gs):
    mock_gs.return_value = _settings()
    h, l, c = _downtrend()
    ich = compute_smart_ichimoku(h, l, c, c[-1])
    assert ich["priceVsCloud"] == "BELOW"
    assert ich["breakSide"] == "BEARISH"
    assert ich["breakProbability"] >= 0.0


@patch("app.engines.smart_ichimoku.get_settings")
def test_compute_ichimoku_classic_levels_plus_smart_break(mock_gs):
    """SL/TP geometry stays classic; flat→vertical gate keeps HMA break-P."""
    mock_gs.return_value = _settings()
    h, l, c = _uptrend()
    ich = compute_ichimoku(h, l, c, c[-1])
    smart = compute_smart_ichimoku(h, l, c, c[-1])
    # Classic Donchian mid tenkan (last 9 highs/lows)
    classic_tenkan = (max(h[-9:]) + min(l[-9:])) / 2
    assert ich["levelsEngine"] == "classic"
    assert ich["tenkan"] == round(classic_tenkan, 2)
    assert ich["tenkan"] != smart["tenkan"] or ich["kijun"] != smart["kijun"]
    assert ich["engine"] == "hma_logistic"
    assert "breakConfirmed" in ich
    assert ich["smartPriceVsCloud"] == smart["priceVsCloud"]
    assert ich["priceVsCloud"] in ("ABOVE", "BELOW", "INSIDE")


@patch("app.engines.smart_ichimoku.get_settings")
def test_break_supports_put_when_confirmed_below(mock_gs):
    mock_gs.return_value = _settings()
    ich = {
        "priceVsCloud": "BELOW",
        "breakSide": "BEARISH",
        "breakProbability": 0.72,
        "breakConfirmed": True,
        "smartBias": "BEARISH",
    }
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24500.0,
        atmStrike=24500.0,
        tradeQualityScore=50,
        breadth=Breadth(bias="BEARISH", score=50, aligned=True),
        spotChart=SpotChart(direction="BEARISH"),
        chartAnalysis=ChartAnalysis(consensus="BEARISH", ichimoku=ich),
    )
    ok, reason = ichimoku_break_supports_side(Side.PUT, snap)
    assert ok is True
    assert "bearish" in reason


@patch("app.engines.smart_ichimoku.get_settings")
def test_break_rejects_put_when_above_cloud(mock_gs):
    mock_gs.return_value = _settings()
    ich = {
        "priceVsCloud": "ABOVE",
        "breakSide": "BULLISH",
        "breakProbability": 0.80,
        "breakConfirmed": True,
        "smartBias": "BULLISH",
    }
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24500.0,
        atmStrike=24500.0,
        tradeQualityScore=50,
        breadth=Breadth(bias="BULLISH", score=50, aligned=True),
        spotChart=SpotChart(direction="BULLISH"),
        chartAnalysis=ChartAnalysis(consensus="BULLISH", ichimoku=ich),
    )
    ok, reason = ichimoku_break_supports_side(Side.PUT, snap)
    assert ok is False
    assert "not_below" in reason


@patch("app.engines.smart_ichimoku.get_settings")
def test_fail_open_without_chart_analysis(mock_gs):
    mock_gs.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24500.0,
        atmStrike=24500.0,
        tradeQualityScore=50,
        breadth=Breadth(bias="BEARISH", score=50, aligned=True),
        spotChart=SpotChart(direction="BEARISH"),
    )
    ok, reason = ichimoku_break_supports_side(Side.PUT, snap)
    assert ok is True
    assert reason == "no_ichimoku"
