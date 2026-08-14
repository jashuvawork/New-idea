"""Bullish CALL prediction at the bottom of a confirmed local premium base."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.engines.bullish_local_base import bullish_local_base_prediction
from app.engines.explosion_entry_guards import (
    explosion_entry_window_blocked,
    immature_explosion_blocked,
)
from app.engines.explosion_detector import ExplosionEvent, event_to_dict
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot


def _settings(**overrides):
    settings = MagicMock()
    settings.bullish_local_base_prediction_enabled = True
    settings.bullish_local_base_prediction_min_score = 62.0
    settings.bullish_local_base_prediction_min_vol_surge = 2.0
    settings.bullish_local_base_prediction_min_velocity_3s = 1.5
    settings.bullish_local_base_prediction_min_velocity_9s = 0.2
    settings.bullish_local_base_prediction_min_move_pct = 8.0
    settings.bullish_local_base_prediction_max_move_pct = 40.0
    settings.bullish_local_base_prediction_min_confidence = 70.0
    settings.bullish_local_base_prediction_rank_max = 18.0
    settings.local_base_turn_bypass_enabled = True
    settings.local_base_turn_min_score = 62.0
    settings.local_base_turn_min_vol_surge = 2.0
    settings.local_base_turn_min_mom_shift_pct = 0.05
    settings.explosion_entry_window_hard_enabled = True
    settings.explosion_immature_block_enabled = True
    settings.explosion_immature_min_session_move_pct = 22.0
    settings.ict_early_vertical_min_session_move_pct = 28.0
    settings.explosion_chase_use_local_base = True
    settings.explosion_local_base_entry_min_move_pct = 15.0
    settings.explosion_early_window_min_move_pct = 28.0
    settings.explosion_early_window_max_move_pct = 65.0
    settings.ict_structured_early_entry_enabled = True
    settings.ict_structured_early_min_move_pct = 15.0
    settings.ict_structured_early_max_move_pct = 65.0
    settings.elite_local_base_max_move_pct = 40.0
    settings.session_move_max_credible_pct = 500.0
    settings.ict_local_base_trust_min_move_pct = 8.0
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _snap(*, mom5=0.02, mom10=0.0, mom15=-0.10):
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-08-14T13:42:00+05:30",
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24300.0,
        tradeQualityScore=70.0,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=mom5,
            momentum10Pct=mom10,
            momentum15Pct=mom15,
            trendStrength=52.0,
            macdBias="BULLISH",
            rsi=54.0,
        ),
    )


def _event(*, side=Side.CALL, score=82.0, volume=3.0, v3=2.4, v9=0.8):
    return SimpleNamespace(
        side=side,
        tier="ELITE",
        explosion_score=score,
        volume_surge=volume,
        velocity_3s=v3,
        velocity_9s=v9,
        daily_move_pct=12.0,
        peak_move_pct=12.0,
        strike=24350.0,
    )


def _ict(*, base_rel=12.0):
    return SimpleNamespace(
        active=True,
        pattern="flat_then_vertical",
        score=82.0,
        reasons=["local_base_turn"],
        flat_then_vertical=True,
        local_swing_base=False,
        mega_rip=False,
        base_premium=90.0,
        base_relative_move_pct=base_rel,
        volume_awakening=True,
        displacement=True,
        premium_fvg=False,
        session_move_pct=12.0,
    )


@pytest.fixture
def prediction_context():
    settings = _settings()
    with (
        patch("app.engines.bullish_local_base.get_settings", return_value=settings),
        patch("app.engines.local_base_chart_bypass.get_settings", return_value=settings),
        patch(
            "app.engines.advanced_indicators.build_entry_confluence",
            return_value={"score": 3},
        ),
    ):
        yield settings


def test_predicts_bullish_call_at_local_base_turn(prediction_context):
    prediction = bullish_local_base_prediction(_snap(), _event(), _ict())

    assert prediction["active"] is True
    assert prediction["direction"] == "BULLISH"
    assert prediction["confidence"] >= 85
    assert prediction["rankBonus"] > 0
    assert prediction["baseRelativeMovePct"] == 12.0
    assert "bullish_momentum_turn" in prediction["reasons"]


def test_rejects_call_while_index_is_still_falling(prediction_context):
    prediction = bullish_local_base_prediction(
        _snap(mom5=-0.20, mom10=-0.10, mom15=-0.05),
        _event(),
        _ict(),
    )
    assert prediction["active"] is False
    assert prediction["rankBonus"] == 0.0


def test_prediction_is_call_only(prediction_context):
    prediction = bullish_local_base_prediction(
        _snap(), _event(side=Side.PUT), _ict(),
    )
    assert prediction["active"] is False
    assert prediction["reasons"] == ["not_call"]


@pytest.mark.parametrize(
    ("event", "ict"),
    [
        (_event(volume=1.2), _ict()),
        (_event(v3=0.5, v9=-0.1), _ict()),
        (_event(), _ict(base_rel=55.0)),
    ],
)
def test_requires_volume_acceleration_and_early_window(
    prediction_context, event, ict,
):
    prediction = bullish_local_base_prediction(_snap(), event, ict)
    assert prediction["active"] is False
    assert prediction["rankBonus"] == 0.0


def test_bullish_prediction_allows_first_lift_but_normal_window_does_not():
    settings = _settings()
    event = _event()
    ict = _ict(base_rel=10.0)
    with (
        patch(
            "app.engines.explosion_entry_guards.get_settings",
            return_value=settings,
        ),
        patch(
            "app.engines.elite_never_block.elite_never_block_active",
            return_value=False,
        ),
    ):
        blocked_without, _ = explosion_entry_window_blocked(event, ict=ict)
        blocked_with, _ = explosion_entry_window_blocked(
            event, ict=ict, bullish_local_base=True,
        )
        immature_without, _ = immature_explosion_blocked(event, ict=ict)
        immature_with, _ = immature_explosion_blocked(
            event, ict=ict, bullish_local_base=True,
        )

    assert blocked_without is True
    assert blocked_with is False
    assert immature_without is True
    assert immature_with is False


def test_radar_marks_confirmed_first_lift_tradeable(prediction_context):
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24350.0,
        premium=100.0,
        velocity_3s=2.4,
        velocity_9s=0.8,
        velocity_15s=0.4,
        volume_surge=3.0,
        explosion_score=82.0,
        tier="ELITE",
        reason="local_base_turn",
        daily_move_pct=10.0,
        peak_move_pct=10.0,
    )
    ict = _ict(base_rel=10.0)
    predicted = {
        "active": True,
        "direction": "BULLISH",
        "confidence": 91.0,
        "rankBonus": 16.38,
        "baseRelativeMovePct": 10.0,
        "confluenceCount": 2,
        "reasons": ["local_base", "bullish_momentum_turn"],
    }
    with (
        patch(
            "app.engines.ict_breakout_monitor.analyze_explosion_event_ict",
            return_value=ict,
        ),
        patch(
            "app.engines.bullish_local_base.bullish_local_base_prediction",
            return_value=predicted,
        ),
    ):
        radar = event_to_dict(event, _snap())

    assert radar["tradeable"] is True
    assert radar["bullishLocalBaseActive"] is True
    assert radar["bullishLocalBaseConfidence"] == 91.0
    assert radar["bullishLocalBasePrediction"]["direction"] == "BULLISH"
