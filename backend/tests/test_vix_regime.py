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
