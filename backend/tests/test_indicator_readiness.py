"""Spot-chart indicator warmup — cold open must not fake MACD/EMA/Ichimoku."""

from __future__ import annotations

from app.engines.advanced_indicators import compute_adx, compute_squeeze
from app.engines.chart_advanced_analysis import _compute_classic_ichimoku
from app.engines.explosion_entry_guards import spot_chart_indicators_cold_blocked
from app.engines.indicator_readiness import MACD_MIN_CLOSES, readiness_from_closes
from app.engines.spot_direction import build_spot_chart
from app.models.schemas import MarketProfile, SpotChart, SymbolSnapshot


def _synthetic_1m_closes(n: int, start: float = 22400.0, step: float = 0.5) -> list[list]:
    rows = []
    for i in range(n):
        c = start + i * step
        rows.append([float(i), c - 0.2, c + 0.3, c - 0.3, c, 0.0])
    return rows


def test_readiness_cold_vs_warm():
    cold = readiness_from_closes([22400.0 + i for i in range(25)])
    assert cold.macd_ready is False
    assert cold.indicators_warm is False

    warm = readiness_from_closes([22400.0 + i * 0.1 for i in range(MACD_MIN_CLOSES + 5)])
    assert warm.macd_ready is True
    assert warm.ema21_ready is True
    assert warm.indicators_warm is True


def test_build_spot_chart_cold_macd_neutral_and_zero():
    candles_5m = _synthetic_1m_closes(5)
    candles_1m = _synthetic_1m_closes(25)
    profile = MarketProfile()
    spot = float(candles_1m[-1][4])
    chart = build_spot_chart(
        candles_5m, spot, profile, indicator_candles_1m=candles_1m,
    )
    assert chart.macdReady is False
    assert chart.indicatorsWarm is False
    assert chart.macd == 0.0
    assert chart.macdBias == "NEUTRAL"


def test_build_spot_chart_warm_macd_prints():
    candles_1m = _synthetic_1m_closes(400, step=0.15)
    from app.engines.mtf_chart_analysis import resample_candles

    candles_5m = resample_candles(candles_1m, 5)
    spot = float(candles_1m[-1][4])
    profile = MarketProfile()
    chart = build_spot_chart(
        candles_5m, spot, profile, indicator_candles_1m=candles_1m,
    )
    assert chart.indicatorBarCount >= MACD_MIN_CLOSES
    assert chart.macdReady is True
    assert chart.indicatorsWarm is True
    assert chart.ema21Ready is True
    assert chart.ema9 != chart.ema21 or chart.emaBias == "NEUTRAL"


def test_ichimoku_not_collapsed_on_five_bars():
    highs = [22410.0 + i for i in range(5)]
    lows = [22390.0 + i for i in range(5)]
    closes = [22400.0 + i for i in range(5)]
    ich = _compute_classic_ichimoku(highs, lows, closes, closes[-1])
    assert ich.get("ichimokuReady") is False
    assert ich.get("cloudBias") == "NEUTRAL"


def test_adx_not_chop_when_insufficient_bars():
    adx = compute_adx([1.0] * 10, [1.0] * 10, [1.0] * 10)
    assert adx.ready is False
    assert adx.regime == "NEUTRAL"


def test_squeeze_not_ready_on_thin_series():
    sq = compute_squeeze([1.0] * 10, [1.0] * 10, [1.0] * 10)
    assert sq.ready is False


def test_chart_analysis_uses_1m_seed_for_ichimoku_when_5m_thin():
    from app.engines.chart_advanced_analysis import build_chart_analysis

    candles_1m = _synthetic_1m_closes(400, step=0.12)
    candles_5m = _synthetic_1m_closes(5)  # native intraday only
    spot = float(candles_1m[-1][4])
    analysis = build_chart_analysis(
        candles_1m, candles_5m, spot, MarketProfile(), symbol="NIFTY",
    )
    assert analysis.ichimoku.get("ichimokuReady") is True
    assert analysis.adx.get("ready") is True
    assert analysis.squeeze.get("ready") is True


def test_cold_indicators_do_not_ban_the_entry():
    """A missing MACD seed stays quiet. It does not drop the explosion."""
    from types import SimpleNamespace

    snap = SimpleNamespace(
        spotChart=SpotChart(
            direction="BEARISH",
            spot=22400.0,
            indicatorsWarm=False,
            indicatorBarCount=25,
        ),
    )
    blocked, reason = spot_chart_indicators_cold_blocked(snap)
    assert blocked is False
    assert reason == ""


def test_short_ichimoku_does_not_hand_the_gate_a_cloud():
    from app.engines.chart_advanced_analysis import compute_ichimoku

    highs = [22450.0 - i * 2 for i in range(12)]
    lows = [22420.0 - i * 2 for i in range(12)]
    closes = [22440.0 - i * 2 for i in range(12)]
    ich = compute_ichimoku(highs, lows, closes, closes[-1])
    assert ich.get("ichimokuReady") is False
    assert ich.get("smartCloudBias") == "NEUTRAL"
    assert ich.get("smartPriceVsCloud") == "INSIDE"
    assert ich.get("breakConfirmed") is False


def test_mtf_prefers_prior_session_seed_over_thin_intraday():
    from app.engines.mtf_chart_analysis import prefer_warmup_series

    thin = _synthetic_1m_closes(5)
    seeded = _synthetic_1m_closes(80)
    chosen = prefer_warmup_series(thin, seeded)
    assert len(chosen) == 80

    native_ready = _synthetic_1m_closes(40)
    shorter_seed = _synthetic_1m_closes(35)
    assert len(prefer_warmup_series(native_ready, shorter_seed)) == 40
