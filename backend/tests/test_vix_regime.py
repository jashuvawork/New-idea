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


def test_from_snapshot_reads_indiaVix():
    snap = SimpleNamespace(indiaVix=16.0, indiaVixRef=15.0)
    r = vix_regime_from_snapshot(snap)
    assert r.available is True and r.posture == "AGGRESSIVE"
    # No field -> inert.
    assert vix_regime_from_snapshot(SimpleNamespace()).available is False


def test_parse_india_vix_quote_ref_from_ohlc():
    from app.services.upstox import parse_india_vix_quote

    # Prior close nested in ohlc.close (the real Upstox shape).
    q = {"last_price": 11.41, "ohlc": {"open": 11.0, "high": 12.0, "low": 10.9, "close": 10.8}}
    out = parse_india_vix_quote(q)
    assert out == {"value": 11.41, "ref": 10.8}


def test_parse_india_vix_quote_ref_from_net_change():
    from app.services.upstox import parse_india_vix_quote

    q = {"last_price": 12.0, "net_change": 1.5}  # prior close = 12.0 - 1.5
    out = parse_india_vix_quote(q)
    assert out["value"] == 12.0
    assert abs(out["ref"] - 10.5) < 1e-9


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
