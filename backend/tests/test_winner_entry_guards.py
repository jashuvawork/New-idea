"""Winner entry guards — block fading premium and loss-streak churn."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import ExplosionEvent
from app.engines.winner_entry_guards import (
    chop_weak_explosion_blocks_entry,
    premium_fading_blocks_entry,
    session_winner_gate,
)
from app.models.schemas import AutoTraderState, Regime, Side


def _event(daily_move: float = 10.0, tier: str = "EXPLODING") -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=78000.0,
        premium=200.0,
        velocity_3s=2.0,
        velocity_9s=3.0,
        velocity_15s=4.0,
        volume_surge=1.5,
        explosion_score=62.0,
        tier=tier,
        reason="test",
        daily_move_pct=daily_move,
    )


@patch("app.engines.winner_entry_guards.get_settings")
def test_fading_premium_blocks_even_high_score(mock_settings):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.execution_chart_min_premium_momentum_pct = -0.35
    mock_settings.return_value = s

    blocked, reason = premium_fading_blocks_entry(
        trade_score=100.0,
        premium_momentum_3s=-0.44,
        premium_momentum_5s=-2.35,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=5.0),
    )
    assert blocked
    assert reason == "premium_fading_at_execution"


@patch("app.engines.winner_entry_guards.get_settings")
def test_elite_extreme_move_bypasses_fading_premium(mock_settings):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    mock_settings.return_value = s

    blocked, _ = premium_fading_blocks_entry(
        trade_score=100.0,
        premium_momentum_3s=-0.44,
        premium_momentum_5s=-2.35,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=105.0, tier="ELITE"),
    )
    assert not blocked


@patch("app.engines.winner_entry_guards.get_settings")
def test_chop_weak_explosion_blocked(mock_settings):
    s = MagicMock()
    s.all_day_explosion_session_move_min_pct = 40.0
    s.aggressive_min_explosion_score = 45.0
    mock_settings.return_value = s

    snap = MagicMock()
    snap.regime = Regime.CHOP
    candidate = SimpleNamespace(
        mode="explosion",
        score=50.0,
        tier="EXPLODING",
        explosion_event=_event(daily_move=5.0),
    )
    blocked, reason = chop_weak_explosion_blocks_entry(candidate, snap)
    assert blocked
    assert reason == "chop_weak_explosion"
