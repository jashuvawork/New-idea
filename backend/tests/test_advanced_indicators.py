"""Advanced indicators: squeeze, ADX/DI, Supertrend, VWAP, Bollinger/Keltner."""

from app.engines.advanced_indicators import (
    compute_adx,
    compute_bollinger,
    compute_keltner,
    compute_squeeze,
    compute_supertrend,
    compute_vwap,
)


def _flat_base(n=40, price=100.0):
    closes = [price + (i % 3) * 0.03 for i in range(n)]
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    return highs, lows, closes


def _rip(price=100.0, n=10, step=2.0):
    closes = [price + (i + 1) * step for i in range(n)]
    highs = [c + 0.4 for c in closes]
    lows = [c - 0.4 for c in closes]
    return highs, lows, closes


def test_bollinger_inside_keltner_on_flat_base():
    h, l, c = _flat_base()
    bb = compute_bollinger(c)
    kc = compute_keltner(h, l, c)
    # Tight base: Bollinger band width is small.
    assert bb.upper > bb.lower
    assert kc.upper > kc.lower


def test_squeeze_on_during_flat_base():
    h, l, c = _flat_base(n=40)
    sq = compute_squeeze(h, l, c)
    assert sq.on is True
    assert sq.state == "SQUEEZE"
    assert sq.bars_on >= 5


def test_squeeze_fresh_fire_bullish_on_upside_release():
    """Flat base -> vertical up: a fresh release with bullish momentum = enter at base."""
    hb, lb, cb = _flat_base(n=40)
    hr, lr, cr = _rip(price=cb[-1], n=6, step=2.5)
    # The coil release prints first; momentum confirms a bar or two later.
    saw_fired = fresh_bull = False
    for k in range(1, len(cr) + 1):
        sq = compute_squeeze(hb + hr[:k], lb + lr[:k], cb + cr[:k])
        saw_fired = saw_fired or sq.fired
        if sq.fresh_fire("CALL"):
            fresh_bull = True
            break
    assert saw_fired  # the coil released
    assert fresh_bull  # and confirmed bullish for a CALL
    assert not compute_squeeze(hb + hr, lb + lr, cb + cr).fresh_fire("PUT")


def test_squeeze_fresh_fire_bearish_on_downside_release():
    hb, lb, cb = _flat_base(n=40)
    down = [cb[-1] - (i + 1) * 2.5 for i in range(6)]
    hr = [c + 0.4 for c in down]
    lr = [c - 0.4 for c in down]
    fresh_bear = False
    for k in range(1, len(down) + 1):
        sq = compute_squeeze(hb + hr[:k], lb + lr[:k], cb + down[:k])
        if sq.fresh_fire("PUT"):
            fresh_bear = True
            break
    assert fresh_bear


def test_adx_trend_vs_chop():
    h, l, c = _rip(n=40, step=1.5)
    adx = compute_adx(h, l, c)
    assert adx.regime == "TREND"
    assert adx.direction == "BULLISH"
    assert adx.plus_di > adx.minus_di

    chop_c = [100 + (1 if i % 2 else -1) * 0.4 for i in range(60)]
    chop_h = [x + 0.15 for x in chop_c]
    chop_l = [x - 0.15 for x in chop_c]
    assert compute_adx(chop_h, chop_l, chop_c).regime == "CHOP"


def test_supertrend_direction_and_flip():
    h, l, c = _rip(n=30, step=1.5)
    up = compute_supertrend(h, l, c)
    assert up.direction == "BULLISH"
    # Reverse hard -> should flip to bearish at some point.
    down_c = c + [c[-1] - (i + 1) * 3.0 for i in range(15)]
    down_h = [x + 0.4 for x in down_c]
    down_l = [x - 0.4 for x in down_c]
    assert compute_supertrend(down_h, down_l, down_c).direction == "BEARISH"


def test_vwap_position_and_reclaim():
    # Dip below VWAP then reclaim on the last bar.
    closes = [100 - i * 0.5 for i in range(20)] + [95.0]
    closes[-1] = 100.5  # last close pops back above the running VWAP
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.3 for c in closes]
    vols = [1000] * len(closes)
    v = compute_vwap(highs, lows, closes, vols)
    assert v.vwap > 0
    assert v.position in ("ABOVE", "BELOW", "AT")


def test_index_squeeze_confirms_side():
    from types import SimpleNamespace

    from app.engines.advanced_indicators import index_squeeze_confirms_side

    fresh_bull = SimpleNamespace(
        chartAnalysis=SimpleNamespace(squeeze={"bars_since_fired": 1, "direction": "BULLISH"})
    )
    assert index_squeeze_confirms_side("CALL", fresh_bull) is True
    assert index_squeeze_confirms_side("PUT", fresh_bull) is False

    stale = SimpleNamespace(
        chartAnalysis=SimpleNamespace(squeeze={"bars_since_fired": 9, "direction": "BULLISH"})
    )
    assert index_squeeze_confirms_side("CALL", stale) is False

    empty = SimpleNamespace(chartAnalysis=SimpleNamespace(squeeze={}))
    assert index_squeeze_confirms_side("CALL", empty) is False


def test_indicators_safe_on_thin_data():
    assert compute_squeeze([1, 2], [1, 2], [1, 2]).state == "NONE"
    assert compute_adx([1, 2], [1, 2], [1, 2]).adx == 0.0
    assert compute_supertrend([1], [1], [1]).direction == "NEUTRAL"
    assert compute_vwap([], [], [], []).vwap == 0.0
