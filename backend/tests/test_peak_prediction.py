"""Peak prediction — gamma impulse, historical analogues, live ratchet."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.engines.peak_prediction import (
    gamma_premium_projection,
    historical_analogue_peak,
    index_impulse_projection,
    predict_peak,
    ratchet_toward_predicted_peak,
    resolve_strike_greeks,
)
from app.models.schemas import Greeks, MarketPhase, PaperTrade, Side, SymbolSnapshot


def _settings(**overrides):
    base = {
        "peak_prediction_enabled": True,
        "peak_prediction_gamma_weight": 0.35,
        "peak_prediction_analogue_weight": 0.40,
        "peak_prediction_structure_weight": 0.25,
        "peak_prediction_impulse_horizon_seconds": 90.0,
        "peak_prediction_nifty_max_impulse_pts": 120.0,
        "peak_prediction_sensex_max_impulse_pts": 180.0,
        "peak_prediction_min_move_pct": 15.0,
        "peak_prediction_max_move_pct": 250.0,
        "peak_prediction_sensex_max_move_pct": 300.0,
        "peak_prediction_analogue_min_samples": 3,
        "peak_prediction_live_ratchet_enabled": True,
        "peak_prediction_ratchet_trigger_frac": 0.85,
        "peak_prediction_ratchet_hot_velocity_3s": 2.0,
        "peak_prediction_ratchet_hot_stretch": 1.12,
        "moment_stage_max_projected_tp": 800.0,
        "moment_stage_trail_enabled": True,
        "moment_stage_min_projected_tp": 40.0,
        "moment_stage_count": 8,
        "moment_stage_min_size": 5.0,
        "moment_stage_max_size": 55.0,
        "moment_stage_giveback_ratio": 0.5,
        "moment_stage_extend_trigger_frac": 0.92,
        "moment_stage_extend_stages": 2.0,
        "moment_stage_extend_hot_velocity_3s": 2.5,
        "moment_stage_extend_hot_stages": 4.0,
        "moment_stage_base_extension_mult": 3.0,
        "moment_stage_entry_premium_mult": 4.2,
        "moment_stage_base_premium_mult": 5.5,
        "ict_max_profit_target_points": 180.0,
        "moment_stage_ict_target_floor_frac": 0.90,
        "nifty_strike_step": 50.0,
        "sensex_strike_step": 100.0,
        "index_drift_enabled": True,
        "index_drift_window_seconds": 45.0,
        "index_drift_min_move_pct": 0.05,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _snap(symbol: str = "SENSEX", spot: float = 81000.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp="2026-08-19T14:14:00+05:30",
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=spot,
        atmStrike=81000.0,
        greeks=Greeks(delta=0.45, gamma=0.002),
    )


def test_gamma_projection_put_index_down():
    out = gamma_premium_projection(
        entry_premium=95.0,
        impulse_pts=-80.0,
        delta=0.42,
        gamma=0.002,
        side="PUT",
    )
    assert out["premiumMovePts"] > 0
    assert out["predictedPremium"] > 95.0
    assert out["movePct"] > 10.0


def test_gamma_projection_call_index_up():
    out = gamma_premium_projection(
        entry_premium=50.0,
        impulse_pts=60.0,
        delta=0.45,
        gamma=0.002,
        side="CALL",
    )
    assert out["predictedPremium"] > 50.0


def test_resolve_strike_greeks_from_chain():
    chain = [
        {
            "strike_price": 76900.0,
            "put_options": {
                "greeks": {"delta": -0.38, "gamma": 0.0018},
            },
        }
    ]
    g = resolve_strike_greeks("SENSEX", "PUT", 76900.0, _snap(), chain=chain)
    assert g["source"] == "chain"
    assert g["delta"] > 0.3


@patch("app.engines.index_tick_helpers.evaluate_index_tick_helpers")
@patch("app.engines.index_tick_helpers.recent_index_drift")
def test_index_impulse_sensex_put(mock_drift, mock_helpers):
    mock_drift.return_value = {"pts": -95.0, "net_pct": -0.12, "drift": True, "aligned": True}
    mock_helpers.return_value = SimpleNamespace(
        velocity_3s=-0.05,
        velocity_9s=-0.03,
        helpers=["index_drift", "index_mom_turn"],
    )

    out = index_impulse_projection("SENSEX", "PUT", _snap(), settings=_settings())
    assert out["impulsePts"] < 0
    assert out["confidence"] > 0.3


@patch("app.engines.eod_ftv_learning.load_learned_params")
def test_historical_analogue_uses_learned_profile(mock_load):
    mock_load.return_value = {
        "profiles": {
            "SENSEX:PUT:ELITE:FTV": {
                "count": 8,
                "medianPeakPct": 85.0,
                "p25PeakPct": 55.0,
                "p75PeakPct": 110.0,
                "hitRate": 0.75,
            }
        }
    }
    out = historical_analogue_peak(
        "SENSEX", "PUT", "ELITE", "FTV", base_rel_pct=12.0, settings=_settings()
    )
    assert out["available"] is True
    assert out["predictedMovePct"] >= 85.0


@patch("app.engines.peak_prediction.historical_analogue_peak")
@patch("app.engines.peak_prediction.index_impulse_projection")
def test_predict_peak_blends_components(mock_impulse, mock_analogue):
    mock_impulse.return_value = {
        "impulsePts": -70.0,
        "confidence": 0.6,
        "indexHelpers": ["index_drift"],
    }
    mock_analogue.return_value = {
        "available": True,
        "predictedMovePct": 90.0,
        "p75MfePct": 105.0,
        "sampleCount": 5,
    }
    out = predict_peak(
        symbol="SENSEX",
        side="PUT",
        strike=76900.0,
        entry_premium=92.0,
        snap=_snap(),
        tier="ELITE",
        base_premium=80.0,
        base_rel_pct=15.0,
        flat_then_vertical=True,
        settings=_settings(),
    )
    assert out["enabled"] is True
    assert out["predictedMaxLtp"] > 92.0
    assert out["predictedMaxMovePct"] >= 15.0
    assert out["predictedMaxTpPoints"] > 0


def test_ratchet_extends_toward_predicted_peak():
    trade = PaperTrade(
        id="t1",
        symbol="SENSEX",
        side=Side.PUT,
        strike=76900,
        entryPremium=95.0,
        currentPremium=140.0,
        lots=10,
        openedAt="2026-08-19T14:14:00+05:30",
        sessionDate="2026-08-19",
        entryContext={
            "predictedMaxTpPoints": 120.0,
            "predictedMaxLtp": 215.0,
            "projectedMaxTp": 80.0,
            "liveVelocity3s": 3.5,
            "stageSize": 20.0,
            "momentStageLadder": True,
        },
    )
    new_pts = ratchet_toward_predicted_peak(trade, best=95.0, settings=_settings())
    assert new_pts >= 80.0


def test_predict_peak_rejects_unsupported_symbol():
    out = predict_peak(
        symbol="BANKNIFTY",
        side="CALL",
        strike=50000.0,
        entry_premium=100.0,
        snap=_snap(symbol="BANKNIFTY"),
        settings=_settings(),
    )
    assert out.get("enabled") is False
