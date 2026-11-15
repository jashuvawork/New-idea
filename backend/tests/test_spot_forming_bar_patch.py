"""Forming index bar OHLC must include live spot (audit index 5m low drift)."""

from app.engines.spot_direction import _patch_forming_candle_ohlc


def test_patch_forming_candle_extends_high_low_with_spot():
    candles = [["t0", 100.0, 100.5, 99.8, 100.2]]
    out = _patch_forming_candle_ohlc(candles, 101.2)
    assert out[-1][2] == 101.2
    assert out[-1][3] == 99.8
    assert out[-1][4] == 101.2

    out2 = _patch_forming_candle_ohlc(candles, 99.0)
    assert out2[-1][3] == 99.0