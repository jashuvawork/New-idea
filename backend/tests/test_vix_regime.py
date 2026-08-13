"""India VIX regime classification — day-type posture."""

from types import SimpleNamespace

from app.engines.vix_regime import classify_vix_regime, vix_regime_from_snapshot


def test_inert_when_no_vix():
    r = classify_vix_regime(None)
    assert r.available is False
    assert r.posture == "NORMAL"
    assert r.level == "UNKNOWN"


def test_rising_elevated_is_expansion_aggressive():
    r = classify_vix_regime(16.0, vix_reference=15.0)
    assert r.available is True
    assert r.level == "ELEVATED"
    assert r.trend == "RISING"
    assert r.regime == "EXPANSION"
    assert r.posture == "AGGRESSIVE"


def test_calm_falling_is_contraction_stand_down():
    r = classify_vix_regime(10.0, vix_reference=10.6)
    assert r.level == "CALM"
    assert r.trend == "FALLING"
    assert r.regime == "CONTRACTION"
    assert r.posture == "STAND_DOWN"


def test_high_spike_sizes_down():
    r = classify_vix_regime(24.0, vix_reference=20.0)
    assert r.level == "HIGH"
    assert r.posture == "SIZE_DOWN"


def test_normal_band_is_normal():
    r = classify_vix_regime(13.0, vix_reference=13.0)
    assert r.level == "NORMAL"
    assert r.posture == "NORMAL"


def test_vix_size_multiplier_observe_and_apply():
    from app.engines.vix_regime import vix_size_multiplier

    # High VIX spike -> SIZE_DOWN -> shrink multiplier; context records it.
    mult, ctx = vix_size_multiplier(SimpleNamespace(indiaVix=24.0, indiaVixRef=20.0))
    assert ctx["posture"] == "SIZE_DOWN"
    assert mult == 0.5 and ctx["multiplier"] == 0.5 and ctx["applied"] is False

    # Expansion -> normal size.
    m2, c2 = vix_size_multiplier(SimpleNamespace(indiaVix=16.0, indiaVixRef=15.0))
    assert c2["posture"] == "AGGRESSIVE" and m2 == 1.0

    # No VIX -> no-op, inert.
    m3, c3 = vix_size_multiplier(SimpleNamespace())
    assert m3 == 1.0 and c3["available"] is False


def test_from_snapshot_reads_indiaVix():
    snap = SimpleNamespace(indiaVix=16.0, indiaVixRef=15.0)
    r = vix_regime_from_snapshot(snap)
    assert r.available is True and r.posture == "AGGRESSIVE"
    # No field -> inert.
    assert vix_regime_from_snapshot(SimpleNamespace()).available is False


def test_parse_india_vix_quote_prefers_net_change_over_stale_ohlc_close():
    from app.services.upstox import parse_india_vix_quote

    # Live index quote: ohlc.close == last_price (today's running close, useless for trend).
    # net_change must win so the ref is the true prior close (12.0 - 1.5 = 10.5).
    q = {"last_price": 12.0, "net_change": 1.5, "ohlc": {"close": 12.0}}
    out = parse_india_vix_quote(q)
    assert out["value"] == 12.0
    assert abs(out["ref"] - 10.5) < 1e-9


def test_parse_india_vix_quote_ref_from_distinct_ohlc_close():
    from app.services.upstox import parse_india_vix_quote

    # No net_change; ohlc.close clearly differs from ltp -> a real prior close.
    q = {"last_price": 11.41, "ohlc": {"open": 11.0, "high": 12.0, "low": 10.9, "close": 10.8}}
    assert parse_india_vix_quote(q) == {"value": 11.41, "ref": 10.8}


def test_parse_india_vix_quote_ignores_ohlc_close_equal_to_ltp():
    from app.services.upstox import parse_india_vix_quote

    # ohlc.close == ltp and no net_change -> ref stays 0 (FLAT) rather than a fake reference.
    out = parse_india_vix_quote({"last_price": 11.42, "ohlc": {"close": 11.42}})
    assert out == {"value": 11.42, "ref": 0.0}


def test_parse_india_vix_quote_top_level_prev_close():
    from app.services.upstox import parse_india_vix_quote

    assert parse_india_vix_quote({"last_price": 13.0, "prev_close": 12.5})["ref"] == 12.5


def test_parse_india_vix_quote_no_last_price():
    from app.services.upstox import parse_india_vix_quote

    assert parse_india_vix_quote({"ohlc": {"close": 10.0}}) is None
    assert parse_india_vix_quote({}) is None


def test_real_symbol_snapshot_carries_vix():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models.schemas import MarketPhase, SymbolSnapshot

    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(ZoneInfo("Asia/Kolkata")),
        marketPhase=MarketPhase.LIVE_MARKET,
        indiaVix=16.0,
        indiaVixRef=15.0,
    )
    r = vix_regime_from_snapshot(snap)
    assert r.available is True and r.posture == "AGGRESSIVE"
    # Default snapshot (no VIX) stays inert.
    bare = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(ZoneInfo("Asia/Kolkata")),
        marketPhase=MarketPhase.LIVE_MARKET,
    )
    assert vix_regime_from_snapshot(bare).available is False
