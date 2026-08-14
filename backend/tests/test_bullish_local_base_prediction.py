"""Local-base reversal prediction — CE and PE first lifts with ICT confirms."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.engines.bullish_local_base import (
    bullish_local_base_prediction,
    local_base_reversal_prediction,
)
from app.engines.explosion_entry_guards import (
    explosion_entry_window_blocked,
    immature_explosion_blocked,
)
from app.engines.explosion_detector import ExplosionEvent, event_to_dict
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot


def _settings(**overrides):
    settings = MagicMock()
    settings.bullish_local_base_prediction_enabled = True
    settings.local_base_reversal_prediction_enabled = True
    settings.bullish_local_base_prediction_min_score = 62.0
    settings.bullish_local_base_prediction_min_vol_surge = 2.0
    settings.bullish_local_base_prediction_min_velocity_3s = 1.5
    settings.bullish_local_base_prediction_min_velocity_9s = 0.2
    settings.bullish_local_base_prediction_min_move_pct = 8.0
    settings.bullish_local_base_prediction_max_move_pct = 40.0
    settings.bullish_local_base_prediction_min_confidence = 70.0
    settings.bullish_local_base_prediction_rank_max = 18.0
    settings.local_base_reversal_ict_bonus_max = 18.0
    settings.local_base_reversal_kill_zone_bonus_enabled = True
    settings.local_base_reversal_require_ict_confirm = False
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


def _snap(*, mom5=0.02, mom10=0.0, mom15=-0.10, side="CALL", smc=None):
    """CALL turn: mom5 rising vs mom15. PUT turn: mom5 falling vs mom15."""
    if side == "PUT" and mom5 == 0.02 and mom15 == -0.10:
        mom5, mom10, mom15 = -0.02, 0.0, 0.10
    direction = "BULLISH" if side == "CALL" else "BEARISH"
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-08-14T13:42:00+05:30",
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24300.0,
        tradeQualityScore=70.0,
        spotChart=SpotChart(
            direction=direction,
            momentum5Pct=mom5,
            momentum10Pct=mom10,
            momentum15Pct=mom15,
            trendStrength=52.0,
            macdBias=direction,
            rsi=54.0 if side == "CALL" else 46.0,
        ),
    )
    if smc is not None:
        snap.chartAnalysis = SimpleNamespace(
            institutional=smc,
            squeeze={},
            adx={},
            supertrend={},
            vwap={},
        )
    return snap


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


def _ict(*, base_rel=12.0, premium_fvg=False, displacement=True):
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
        displacement=displacement,
        premium_fvg=premium_fvg,
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
    prediction = local_base_reversal_prediction(_snap(), _event(), _ict())

    assert prediction["active"] is True
    assert prediction["side"] == "CALL"
    assert prediction["direction"] == "BULLISH"
    assert prediction["confidence"] >= 85
    assert prediction["rankBonus"] > 0
    assert prediction["baseRelativeMovePct"] == 12.0
    assert "bullish_momentum_turn" in prediction["reasons"]


def test_predicts_bearish_put_at_local_base_turn(prediction_context):
    prediction = local_base_reversal_prediction(
        _snap(side="PUT"),
        _event(side=Side.PUT),
        _ict(),
    )

    assert prediction["active"] is True
    assert prediction["side"] == "PUT"
    assert prediction["direction"] == "BEARISH"
    assert prediction["confidence"] >= 85
    assert prediction["rankBonus"] > 0
    assert "bearish_momentum_turn" in prediction["reasons"]


def test_rejects_call_while_index_is_still_falling(prediction_context):
    prediction = local_base_reversal_prediction(
        _snap(mom5=-0.20, mom10=-0.10, mom15=-0.05),
        _event(),
        _ict(),
    )
    assert prediction["active"] is False
    assert prediction["rankBonus"] == 0.0


def test_rejects_put_while_index_is_still_rising(prediction_context):
    prediction = local_base_reversal_prediction(
        _snap(side="PUT", mom5=0.20, mom10=0.10, mom15=0.05),
        _event(side=Side.PUT),
        _ict(),
    )
    assert prediction["active"] is False
    assert prediction["rankBonus"] == 0.0


def test_alias_bullish_local_base_prediction_supports_put(prediction_context):
    prediction = bullish_local_base_prediction(
        _snap(side="PUT"),
        _event(side=Side.PUT),
        _ict(),
    )
    assert prediction["active"] is True
    assert prediction["side"] == "PUT"


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
    prediction = local_base_reversal_prediction(_snap(), event, ict)
    assert prediction["active"] is False
    assert prediction["rankBonus"] == 0.0


def test_ict_confirms_boost_confidence_for_call(prediction_context):
    smc = {
        "premiumDiscount": "DISCOUNT",
        "stopHunt": "buy_side_liquidity_sweep",
        "judasSwing": True,
        "displacement": True,
        "choch": "bullish_choch",
        "bos": "bullish_bos",
        "inKillZone": True,
        "killZone": "open_kill_zone",
    }
    base = local_base_reversal_prediction(_snap(), _event(), _ict())
    boosted = local_base_reversal_prediction(
        _snap(smc=smc),
        _event(),
        _ict(premium_fvg=True),
    )
    assert boosted["active"] is True
    assert boosted["confidence"] >= base["confidence"]
    assert "premium_fvg" in boosted["ictConfirms"]
    assert "index_discount_ote" in boosted["ictConfirms"]
    assert "judas_buy_side_reclaim" in boosted["ictConfirms"]
    assert "bullish_mss" in boosted["ictConfirms"]


def test_ict_confirms_boost_confidence_for_put(prediction_context):
    smc = {
        "premiumDiscount": "PREMIUM",
        "stopHunt": "sell_side_liquidity_sweep",
        "judasSwing": True,
        "displacement": True,
        "choch": "bearish_choch",
        "bos": "bearish_bos",
        "inKillZone": False,
    }
    prediction = local_base_reversal_prediction(
        _snap(side="PUT", smc=smc),
        _event(side=Side.PUT),
        _ict(premium_fvg=True),
    )
    assert prediction["active"] is True
    assert "premium_fvg" in prediction["ictConfirms"]
    assert "index_premium_ote" in prediction["ictConfirms"]
    assert "judas_sell_side_reclaim" in prediction["ictConfirms"]
    assert "bearish_mss" in prediction["ictConfirms"]


def test_local_base_reversal_allows_first_lift_window_for_put():
    settings = _settings()
    event = _event(side=Side.PUT)
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


def test_radar_marks_confirmed_first_lift_tradeable_call(prediction_context):
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
        "side": "CALL",
        "direction": "BULLISH",
        "confidence": 91.0,
        "rankBonus": 16.38,
        "baseRelativeMovePct": 10.0,
        "confluenceCount": 2,
        "ictConfirms": ["premium_fvg"],
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
    assert radar["localBaseReversalActive"] is True
    assert radar["localBaseReversalSide"] == "CALL"
    assert radar["bullishLocalBaseConfidence"] == 91.0


def test_radar_marks_confirmed_first_lift_tradeable_put(prediction_context):
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
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
        "side": "PUT",
        "direction": "BEARISH",
        "confidence": 91.0,
        "rankBonus": 16.38,
        "baseRelativeMovePct": 10.0,
        "confluenceCount": 2,
        "ictConfirms": ["index_premium_ote", "bearish_mss"],
        "reasons": ["local_base", "bearish_momentum_turn"],
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
        radar = event_to_dict(event, _snap(side="PUT"))

    assert radar["tradeable"] is True
    assert radar["localBaseReversalActive"] is True
    assert radar["localBaseReversalSide"] == "PUT"
    assert radar["localBaseReversalPrediction"]["direction"] == "BEARISH"
