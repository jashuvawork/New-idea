"""Flat-base coil breakout predictor — flag the coil + predicted side while still flat."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.coil_breakout_predictor import (
    coil_breakout_prediction,
    coil_prediction_rank_delta,
)
from app.models.schemas import Side


def _settings(**over):
    s = SimpleNamespace(
        coil_breakout_prediction_enabled=True,
        coil_prediction_influences_ranking=True,
        coil_prediction_max_range_pct=5.0,
        coil_prediction_min_direction_votes=2,
        coil_prediction_min_readiness_for_rank=60.0,
        coil_prediction_rank_bonus=10.0,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _ict(armed=True, range_pct=2.0, span=30.0, base_move=4.0):
    return SimpleNamespace(
        base_armed=armed,
        armed_base_range_pct=range_pct,
        armed_base_span_seconds=span,
        base_relative_move_pct=base_move,
    )


def _snap(symbol="NIFTY", squeeze_on=True, squeeze_dir="BULLISH", bars_on=4):
    ca = SimpleNamespace(
        squeeze={"on": squeeze_on, "bars_on": bars_on, "direction": squeeze_dir,
                 "bars_since_fired": 99},
        vwap={"reclaim": "NONE", "position": "AT"},
    )
    return SimpleNamespace(symbol=symbol, chartAnalysis=ca, heatmap=[])


def _event(side="CALL", strike=24200.0, vol_surge=1.0):
    return SimpleNamespace(side=side, strike=strike, volume_surge=vol_surge)


def _no_side_regime(*_a, **_k):
    return "NEUTRAL"


def _no_vwap(*_a, **_k):
    return False


def _no_cvd(*_a, **_k):
    return False


def test_coiling_detected_with_armed_tight_base_and_squeeze():
    with (
        patch("app.engines.side_regime.session_trade_side", _no_side_regime),
        patch("app.engines.advanced_indicators.index_vwap_confirms_side", _no_vwap),
        patch("app.engines.advanced_indicators.option_cvd_confirms_buying", _no_cvd),
    ):
        out = coil_breakout_prediction(
            _snap(), _event("CALL"), _ict(), settings=_settings(),
        )
    assert out["coiling"] is True
    assert out["armed"] is True
    assert out["readinessScore"] > 0


def test_predicted_side_call_from_squeeze_and_side_regime():
    with (
        patch("app.engines.side_regime.session_trade_side", lambda s: "CALL"),
        patch("app.engines.advanced_indicators.index_vwap_confirms_side", _no_vwap),
        patch("app.engines.advanced_indicators.option_cvd_confirms_buying", _no_cvd),
    ):
        out = coil_breakout_prediction(
            _snap(squeeze_dir="BULLISH"), _event("CALL"), _ict(), settings=_settings(),
        )
    # squeeze_dir (bull) + side_regime (CALL) = 2 votes >= min → predicts CALL.
    assert out["predictedSide"] == "CALL"
    assert out["directionVotes"] >= 2


def test_not_coiling_without_armed_base():
    out = coil_breakout_prediction(
        _snap(), _event("CALL"), _ict(armed=False), settings=_settings(),
    )
    assert out["coiling"] is False
    assert out["predictedSide"] is None


def test_no_predicted_side_when_signals_insufficient():
    with (
        patch("app.engines.side_regime.session_trade_side", _no_side_regime),
        patch("app.engines.advanced_indicators.index_vwap_confirms_side", _no_vwap),
        patch("app.engines.advanced_indicators.option_cvd_confirms_buying", _no_cvd),
    ):
        # squeeze bearish while side is CALL → 0 direction votes.
        out = coil_breakout_prediction(
            _snap(squeeze_dir="BEARISH"), _event("CALL"), _ict(), settings=_settings(),
        )
    assert out["coiling"] is True
    assert out["predictedSide"] is None


def test_disabled_is_noop():
    out = coil_breakout_prediction(
        _snap(), _event("CALL"), _ict(),
        settings=_settings(coil_breakout_prediction_enabled=False),
    )
    assert out["coiling"] is False
    assert out["readinessScore"] == 0.0


def test_rank_delta_rewards_ripe_matching_coil():
    with patch("app.engines.coil_breakout_predictor.get_settings", return_value=_settings()):
        alert = {"coilReadinessScore": 75.0, "coilPredictedSide": "CALL"}
        assert coil_prediction_rank_delta(alert, Side.CALL) == 10.0
        # Wrong side → no bonus.
        assert coil_prediction_rank_delta(alert, Side.PUT) == 0.0
        # Below readiness floor → no bonus.
        low = {"coilReadinessScore": 40.0, "coilPredictedSide": "CALL"}
        assert coil_prediction_rank_delta(low, Side.CALL) == 0.0
