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
