"""Advanced indicators: squeeze, ADX/DI, Supertrend, VWAP, Bollinger/Keltner."""

from app.engines.advanced_indicators import (
    compute_adx,
    compute_bollinger,
    compute_decisive_candle,
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


def test_index_adx_rank_adjust():
    from types import SimpleNamespace

    from app.engines.advanced_indicators import index_adx_rank_adjust

    trend_up = SimpleNamespace(
        chartAnalysis=SimpleNamespace(adx={"regime": "TREND", "direction": "BULLISH"})
    )
    assert index_adx_rank_adjust("CALL", trend_up) > 0        # aligned trend -> bonus
    assert index_adx_rank_adjust("PUT", trend_up) == 0.0      # counter -> no bonus
    chop = SimpleNamespace(chartAnalysis=SimpleNamespace(adx={"regime": "CHOP", "direction": "BULLISH"}))
    assert index_adx_rank_adjust("CALL", chop) < 0            # chop -> penalty
    assert index_adx_rank_adjust("CALL", SimpleNamespace(chartAnalysis=SimpleNamespace(adx={}))) == 0.0


def test_index_vwap_confirms_side():
    from types import SimpleNamespace

    from app.engines.advanced_indicators import index_vwap_confirms_side

    bull = SimpleNamespace(chartAnalysis=SimpleNamespace(vwap={"reclaim": "BULLISH_RECLAIM"}))
    assert index_vwap_confirms_side("CALL", bull) is True
    assert index_vwap_confirms_side("PUT", bull) is False
    bear = SimpleNamespace(chartAnalysis=SimpleNamespace(vwap={"reclaim": "BEARISH_LOSS"}))
    assert index_vwap_confirms_side("PUT", bear) is True
    none = SimpleNamespace(chartAnalysis=SimpleNamespace(vwap={"reclaim": "NONE", "position": "ABOVE"}))
    assert index_vwap_confirms_side("CALL", none) is False    # position alone is not a reclaim


def test_build_entry_confluence():
    from types import SimpleNamespace

    from app.engines.advanced_indicators import build_entry_confluence
    from app.services.cvd_store import clear, record_cvd_tick

    clear()
    ce_key = "NSE_FO|CONF_CE"
    record_cvd_tick(ce_key, 100.0, 40)
    record_cvd_tick(ce_key, 101.0, 60)  # buying
    snap = SimpleNamespace(
        heatmap=[SimpleNamespace(strike=24000.0, callInstrumentKey=ce_key, putInstrumentKey="x")],
        chartAnalysis=SimpleNamespace(
            squeeze={"state": "FIRED", "direction": "BULLISH", "bars_since_fired": 1},
            adx={"adx": 30.0, "regime": "TREND", "direction": "BULLISH"},
            vwap={"position": "ABOVE", "reclaim": "BULLISH_RECLAIM"},
            supertrend={"direction": "BULLISH"},
        ),
    )
    event = SimpleNamespace(side="CALL", strike=24000.0, tier="ELITE", explosion_score=90.0, volume_surge=3.0)
    conf = build_entry_confluence(snap, event)
    # squeeze + adx + vwap + supertrend + cvd all aligned bullish -> high confluence.
    assert conf["score"] >= 5
    assert conf["squeeze"]["aligned"] and conf["adx"]["aligned"]
    assert conf["vwap"]["aligned"] and conf["supertrend"]["aligned"] and conf["cvd"]["aligned"]

    # A PUT on the same bullish tape has ~no aligned confirmations.
    put_conf = build_entry_confluence(snap, SimpleNamespace(side="PUT", strike=24000.0, tier="ELITE", explosion_score=90.0, volume_surge=3.0))
    assert put_conf["score"] <= 1
    clear()


def test_squeeze_early_base_active():
    from types import SimpleNamespace

    from app.engines.advanced_indicators import squeeze_early_base_active

    snap = SimpleNamespace(
        chartAnalysis=SimpleNamespace(squeeze={"bars_since_fired": 1, "direction": "BULLISH"})
    )
    assert squeeze_early_base_active(SimpleNamespace(tier="ELITE", side="CALL"), snap) is True
    # Non-top tier -> no early-base allowance.
    assert squeeze_early_base_active(SimpleNamespace(tier="BUILDING", side="CALL"), snap) is False
    # Opposite direction -> not confirmed.
    assert squeeze_early_base_active(SimpleNamespace(tier="ELITE", side="PUT"), snap) is False


def test_indicators_safe_on_thin_data():
    assert compute_squeeze([1, 2], [1, 2], [1, 2]).state == "NONE"
    assert compute_adx([1, 2], [1, 2], [1, 2]).adx == 0.0
    assert compute_supertrend([1], [1], [1]).direction == "NEUTRAL"
    assert compute_vwap([], [], [], []).vwap == 0.0


def _pullback_then(final_open, final_high, final_low, final_close, n=20):
    # A steep downtrend for n bars (each red), then append the caller's final bar.
    opens = [100.0 - i * 1.0 for i in range(n)]
    closes = [op - 0.8 for op in opens]         # each bar red, closing lower
    highs = [op + 0.2 for op in opens]
    lows = [cl - 0.2 for cl in closes]
    opens.append(final_open); highs.append(final_high)
    lows.append(final_low); closes.append(final_close)
    return opens, highs, lows, closes


def test_decisive_candle_bullish_reversal_after_pullback():
    # Final bar: strong-bodied bullish engulfing after a real down leg -> BULLISH decisive.
    prev_close = 100.0 - 19 * 1.0 - 0.8  # last downtrend close (80.2)
    o, c = prev_close - 0.2, prev_close + 3.0
    r = compute_decisive_candle(*_pullback_then(o, c + 0.3, o - 0.3, c))
    assert r.direction == "BULLISH"
    assert r.decisive is True
    assert r.engulfing is True
    assert r.after_pullback is True
    assert r.body_ratio >= 0.6


def test_decisive_candle_weak_body_not_decisive():
    # Small body with big wicks after the pullback -> not decisive even if greenish.
    prev_close = 100.0 - 19 * 1.0 - 0.8
    o, c = prev_close - 0.1, prev_close + 0.3
    r = compute_decisive_candle(*_pullback_then(o, prev_close + 3.0, prev_close - 2.5, c))
    assert r.decisive is False


def test_decisive_candle_no_pullback_is_continuation_not_signal():
    # Strong bullish bar but preceded by an UPtrend -> not a reversal, not decisive.
    opens = [100.0 + i * 0.5 for i in range(20)]
    closes = [op + 0.4 for op in opens]
    highs = [cl + 0.2 for cl in closes]
    lows = [op - 0.2 for op in opens]
    prev_close = closes[-1]
    opens.append(prev_close - 0.2); highs.append(prev_close + 3.2)
    lows.append(prev_close - 0.3); closes.append(prev_close + 3.0)
    r = compute_decisive_candle(opens, highs, lows, closes)
    assert r.direction == "NEUTRAL"
    assert r.decisive is False


def test_bucket_ohlc_groups_by_time():
    from app.engines.advanced_indicators import _bucket_ohlc

    # Two 30s buckets: [10,12,11] then [20,25,22]
    series = [(0.0, 10.0), (10.0, 12.0), (20.0, 11.0), (30.0, 20.0), (40.0, 25.0), (55.0, 22.0)]
    o, h, l, c = _bucket_ohlc(series, bucket_seconds=30.0)
    assert o == [10.0, 20.0]
    assert h == [12.0, 25.0]
    assert l == [10.0, 20.0]
    assert c == [11.0, 22.0]


def test_option_decisive_breakout_confirms_on_premium_tape():
    """GainzAlgo on the OPTION premium: a decisive breakout bar off a flat base confirms."""
    from types import SimpleNamespace
    from unittest.mock import patch

    import app.engines.explosion_detector as ed
    from app.engines.advanced_indicators import option_decisive_breakout_confirms
    from app.models.schemas import Side

    # Build a premium tape: flat base ~40 (steep prior decline in premium terms), then a
    # decisive bullish breakout bar. Bucketed at 30s.
    from collections import deque
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
    key = ed._open_key("NIFTY", 24050.0, Side.CALL)
    t0 = datetime(2026, 9, 1, 11, 0, 0, tzinfo=IST)
    # A steep premium decline (each 30s bar closes lower via 2 samples: open high, close low),
    # then a strong engulfing green breakout bar that closes above the prior bar's open but
    # still below where it was 5 bars back (a genuine reversal off the base, not a full recovery).
    prems = []
    price = 60.0
    bars = 20
    for i in range(bars):
        prems.append((t0 + timedelta(seconds=i * 30), price))            # open (high)
        prems.append((t0 + timedelta(seconds=i * 30 + 15), price - 1.2))  # close (low) -> red
        price -= 2.0
    last_open = price  # 60 - 2*20 = 20
    prems.append((t0 + timedelta(seconds=bars * 30), last_open))           # open (low)
    prems.append((t0 + timedelta(seconds=bars * 30 + 15), last_open + 4.0))  # close -> green
    ed._local_base_hist[key] = deque(prems)

    s = SimpleNamespace(
        option_decisive_breakout_enabled=True,
        option_decisive_breakout_lookback_seconds=3600.0,
        option_decisive_breakout_bucket_seconds=30.0,
        decisive_candle_body_ratio_min=0.6,
        decisive_candle_rsi_ceiling=80.0,
        decisive_candle_pullback_lookback=5,
    )
    try:
        assert option_decisive_breakout_confirms("NIFTY", 24050.0, Side.CALL, settings=s) is True
        # Disabled -> no confirmation.
        s.option_decisive_breakout_enabled = False
        assert option_decisive_breakout_confirms("NIFTY", 24050.0, Side.CALL, settings=s) is False
    finally:
        ed._local_base_hist.clear()


def test_index_decisive_breakout_confirms_side_reads_snapshot():
    from types import SimpleNamespace

    from app.engines.advanced_indicators import index_decisive_breakout_confirms_side

    snap = SimpleNamespace(chartAnalysis=SimpleNamespace(
        decisiveCandle={"decisive": True, "direction": "BULLISH"}))
    assert index_decisive_breakout_confirms_side("CALL", snap) is True
    assert index_decisive_breakout_confirms_side("PUT", snap) is False
    # Not decisive -> no confirmation either way.
    snap2 = SimpleNamespace(chartAnalysis=SimpleNamespace(
        decisiveCandle={"decisive": False, "direction": "BULLISH"}))
    assert index_decisive_breakout_confirms_side("CALL", snap2) is False
