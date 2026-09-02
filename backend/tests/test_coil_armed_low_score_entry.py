"""Coil-armed LOW-SCORE base entry — take a top setup at the base before the score catches up (opt-in)."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.ict_breakout_monitor import _coil_armed_low_score_readiness


def _settings(**over):
    s = SimpleNamespace(
        coil_armed_low_score_entry_enabled=True,
        coil_armed_low_score_min_readiness=72.0,
        coil_armed_low_score_min_direction_votes=3,
        coil_armed_low_score_max_base_move_pct=12.0,
        coil_armed_low_score_min_score=40.0,
        coil_armed_low_score_min_vol_surge=1.5,
        near_base_lane_min_quality=70.0,
        near_base_lane_strong_score=90.0,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _event(side="CALL", score=45.0, strike=24200.0, vol_surge=2.0):
    return SimpleNamespace(
        side=side, explosion_score=score, strike=strike,
        volume_surge=vol_surge, base_relative_move_pct=6.0,
    )


def _ict(base_move=6.0, quality=82.0):
    # A genuine coil-armed base setup carries strong FTV quality (the proven separator on the
    # 11-day data) — that's what lets a LOW score enter at the base without taking a dud.
    return SimpleNamespace(
        base_relative_move_pct=base_move, volume_awakening=True,
        flat_vertical_quality=quality,
    )


def _snap(symbol="NIFTY", spot=24200.0, atm=24200.0):
    return SimpleNamespace(symbol=symbol, spot=spot, atmStrike=atm, chartAnalysis=None, heatmap=[])


def _pred(coiling=True, side="CALL", readiness=80.0, votes=3):
    return {
        "coiling": coiling, "predictedSide": side,
        "readinessScore": readiness, "directionVotes": votes,
    }


def test_low_score_entry_fires_when_coil_ripe_and_directional():
    with patch(
        "app.engines.coil_breakout_predictor.coil_breakout_prediction",
        return_value=_pred(),
    ):
        ok, reason = _coil_armed_low_score_readiness(
            snap=_snap(), event=_event(score=45.0), ict=_ict(),
            alert={"tier": "EXPLODING"}, settings=_settings(),
        )
    assert ok is True
    assert reason == "coil_armed_low_score_base_entry"


def test_low_quality_low_score_near_base_dud_is_blocked():
    """Data-calibrated: a ripe coil with a LOW score AND weak FTV quality is the near-base
    dud bucket — block it. Low score is only allowed when quality is strong."""
    with patch(
        "app.engines.coil_breakout_predictor.coil_breakout_prediction",
        return_value=_pred(),
    ):
        ok, reason = _coil_armed_low_score_readiness(
            snap=_snap(), event=_event(score=45.0), ict=_ict(quality=40.0),
            alert={"tier": "EXPLODING"}, settings=_settings(),
        )
    assert ok is False
    assert reason == "coil_armed_below_quality_score_floor"


def test_disabled_by_default_is_noop():
    ok, reason = _coil_armed_low_score_readiness(
        snap=_snap(), event=_event(), ict=_ict(), alert={},
        settings=_settings(coil_armed_low_score_entry_enabled=False),
    )
    assert ok is False
    assert reason == ""


def test_blocked_below_hard_noise_floor():
    """Even a ripe coil is skipped if score is genuine junk (below the noise floor)."""
    with patch(
        "app.engines.coil_breakout_predictor.coil_breakout_prediction",
        return_value=_pred(),
    ):
        ok, _ = _coil_armed_low_score_readiness(
            snap=_snap(), event=_event(score=25.0), ict=_ict(),
            alert={}, settings=_settings(),
        )
    assert ok is False


def test_blocked_when_predicted_side_mismatch():
    with patch(
        "app.engines.coil_breakout_predictor.coil_breakout_prediction",
        return_value=_pred(side="PUT"),
    ):
        ok, _ = _coil_armed_low_score_readiness(
            snap=_snap(), event=_event(side="CALL"), ict=_ict(),
            alert={}, settings=_settings(),
        )
    assert ok is False


def test_blocked_when_readiness_or_votes_low():
    with patch(
        "app.engines.coil_breakout_predictor.coil_breakout_prediction",
        return_value=_pred(readiness=60.0, votes=2),
    ):
        ok, _ = _coil_armed_low_score_readiness(
            snap=_snap(), event=_event(), ict=_ict(), alert={}, settings=_settings(),
        )
    assert ok is False


def test_blocked_when_too_far_off_base():
    with patch(
        "app.engines.coil_breakout_predictor.coil_breakout_prediction",
        return_value=_pred(),
    ):
        ok, _ = _coil_armed_low_score_readiness(
            snap=_snap(), event=_event(), ict=_ict(base_move=18.0),
            alert={"ictBaseRelativeMovePct": 18.0}, settings=_settings(),
        )
    assert ok is False


def test_requires_atm_itm():
    with patch(
        "app.engines.coil_breakout_predictor.coil_breakout_prediction",
        return_value=_pred(),
    ):
        ok, reason = _coil_armed_low_score_readiness(
            snap=_snap(spot=24000.0, atm=24000.0),
            event=_event(strike=24600.0), ict=_ict(),
            alert={}, settings=_settings(),
        )
    assert ok is False
    assert reason == "coil_armed_requires_atm_itm"
