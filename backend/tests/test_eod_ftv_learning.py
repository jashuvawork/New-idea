"""EOD FTV learning: distil radar outcomes into a near-base entry / TP / SL knowledge profile."""

from app.engines.eod_ftv_learning import learn_ftv_profile


def _entry(symbol, side, tier, mfe, mae, base_rel=15.0, ftv=True):
    return {
        "symbol": symbol, "side": side, "tier": tier,
        "alert": {
            "symbol": symbol, "side": side, "tier": tier,
            "ictFlatThenVertical": ftv, "ictBaseRelativeMovePct": base_rel,
        },
        "outcome": {"mfePct": mfe, "maePct": mae},
    }


def test_learns_peak_and_hitrate_per_bucket():
    entries = [
        _entry("SENSEX", "CALL", "ELITE", 300.0, -40.0),
        _entry("SENSEX", "CALL", "ELITE", 400.0, -50.0),
        _entry("SENSEX", "CALL", "ELITE", 200.0, -30.0),
    ]
    prof = learn_ftv_profile(entries)
    p = prof["SENSEX:CALL:ELITE"]
    assert p["count"] == 3
    assert p["medianPeakPct"] == 300.0
    assert p["hitRate"] == 1.0  # all >= 50% real-leg floor
    assert 0.6 <= p["recommendedTrailKeepRatio"] <= 0.85
    assert p["recommendedStopPct"] > 0


def test_low_hitrate_tightens_recommendations():
    # Mostly fizzles (below the 50% real-leg floor) -> low hit rate, conservative keep.
    entries = [_entry("NIFTY", "PUT", "EXPLODING", 10.0, -20.0) for _ in range(6)]
    entries.append(_entry("NIFTY", "PUT", "EXPLODING", 120.0, -18.0))
    prof = learn_ftv_profile(entries)
    p = prof["NIFTY:PUT:EXPLODING"]
    assert p["count"] == 7
    assert p["hitRate"] < 0.5
    # Low hit rate -> conservative keep near the 0.60 floor (well below the 0.85 cap).
    assert p["recommendedTrailKeepRatio"] < 0.70


def test_non_ftv_low_tier_ignored():
    entries = [
        {"symbol": "NIFTY", "side": "CALL", "tier": "WATCH",
         "alert": {"symbol": "NIFTY", "side": "CALL", "tier": "WATCH",
                   "ictFlatThenVertical": False, "ictPattern": "watch"},
         "outcome": {"mfePct": 5.0, "maePct": -2.0}},
    ]
    assert learn_ftv_profile(entries) == {}


def test_merge_across_days_is_count_weighted():
    from app.engines.eod_ftv_learning import _merge_profiles
    agg = {"SENSEX:CALL:ELITE": {"count": 2, "medianPeakPct": 100.0,
                                 "recommendedTrailKeepRatio": 0.70}}
    day = {"SENSEX:CALL:ELITE": {"count": 2, "medianPeakPct": 300.0,
                                 "recommendedTrailKeepRatio": 0.80}}
    out = _merge_profiles(agg, day)
    p = out["SENSEX:CALL:ELITE"]
    assert p["count"] == 4
    assert p["medianPeakPct"] == 200.0  # (100*2 + 300*2)/4


def test_low_hit_size_multiplier(monkeypatch, tmp_path):
    from app.engines import eod_ftv_learning as m
    # Point the learned store at a temp file with a low-hit + a high-hit bucket.
    store = {
        "profiles": {
            "NIFTY:PUT:EXPLODING": {"count": 14, "hitRate": 0.0},
            "SENSEX:CALL:ELITE": {"count": 12, "hitRate": 0.58},
            "SENSEX:PUT:OTHER": {"count": 3, "hitRate": 0.0},  # too few samples
        }
    }
    monkeypatch.setattr(m, "load_learned_params", lambda: store)
    # Low-hit with enough samples -> shrink.
    assert m.low_hit_size_multiplier("NIFTY", "PUT", "EXPLODING") < 1.0
    # High-hit -> no change.
    assert m.low_hit_size_multiplier("SENSEX", "CALL", "ELITE") == 1.0
    # Low hit but too few samples -> no change.
    assert m.low_hit_size_multiplier("SENSEX", "PUT", "OTHER") == 1.0
    # Unknown bucket -> no change.
    assert m.low_hit_size_multiplier("NIFTY", "CALL", "WATCH") == 1.0
