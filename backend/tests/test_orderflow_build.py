"""Orderflow metrics — chart + chain fusion when index candle volume is zero."""

from app.engines.realtime_engine import _build_orderflow
from app.models.schemas import SpotChart


def _candles_zero_volume():
    return [
        [1, 100, 101, 99, 100, 0],
        [2, 100, 101, 99, 100.2, 0],
        [3, 100.2, 101, 99.5, 100.5, 0],
        [4, 100.5, 101.2, 100, 101, 0],
        [5, 101, 102, 100.5, 101.5, 0],
    ]


def _nifty_1m_candles():
    """Realistic NIFTY ~24600 series with a 12pt last bar (used to print as tickMomentum≈0)."""
    base = 24600.0
    closes = [base, base + 3, base + 1, base - 2, base + 2, base + 5, base + 8, base + 20]
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append([i, o, max(o, c) + 2, min(o, c) - 2, c, 1000])
    return out


def test_orderflow_uses_chart_when_candle_volume_zero():
    chart = SpotChart(
        direction="BULLISH",
        momentum5Pct=0.35,
        momentum15Pct=0.55,
        trendStrength=42,
    )
    chain = [
        {
            "strike_price": 77000,
            "call_options": {"volume": 120000},
            "put_options": {"volume": 80000},
        },
        {
            "strike_price": 77100,
            "call_options": {"volume": 95000},
            "put_options": {"volume": 60000},
        },
    ]
    of = _build_orderflow(
        _candles_zero_volume(),
        chain,
        spot=77050,
        atm=77100,
        symbol="SENSEX",
        spot_chart=chart,
    )
    assert of.deltaVelocity > 8
    assert of.breakoutVelocity > 8
    assert of.bidAskImbalance > 50
    assert of.volumeAcceleration > 0
    assert of.tickMomentum > 8


def test_nifty_tick_momentum_not_stuck_at_zero():
    """12pt NIFTY bar must score well above 0 (old *2000 scale → ~1.0 → UI 0)."""
    of = _build_orderflow(
        _nifty_1m_candles(),
        [],
        spot=24620.0,
        atm=24600.0,
        symbol="NIFTY",
    )
    assert of.tickMomentum >= 10
    assert of.tickMomentum <= 100


def test_live_spot_patches_stale_last_close_for_tick_momentum():
    """Forming bar close equal to prior → 0 unless live spot is patched in."""
    candles = [
        [1, 24600, 24610, 24590, 24600, 1000],
        [2, 24600, 24610, 24590, 24600, 1000],
        [3, 24600, 24610, 24590, 24600, 1000],
        [4, 24600, 24610, 24590, 24600, 1000],
        [5, 24600, 24610, 24590, 24600, 1000],
    ]
    flat = _build_orderflow(candles, [], spot=24600.0, atm=24600.0, symbol="NIFTY")
    assert flat.tickMomentum == 0
    moving = _build_orderflow(candles, [], spot=24618.0, atm=24600.0, symbol="NIFTY")
    assert moving.tickMomentum >= 10


def test_chart_fallback_tick_momentum_on_quiet_candles():
    chart = SpotChart(
        direction="BULLISH",
        momentum5Pct=0.20,
        momentum15Pct=0.30,
        trendStrength=35,
    )
    candles = [
        [1, 24600, 24602, 24598, 24600, 0],
        [2, 24600, 24602, 24598, 24600, 0],
        [3, 24600, 24602, 24598, 24600, 0],
        [4, 24600, 24602, 24598, 24600, 0],
        [5, 24600, 24602, 24598, 24600, 0],
    ]
    of = _build_orderflow(
        candles, [], spot=24600.0, atm=24600.0, symbol="NIFTY", spot_chart=chart,
    )
    assert of.tickMomentum >= 8
