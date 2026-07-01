"""Rally capture guards — wrong side, exhaustion, runner strike preference."""

from app.engines.explosion_detector import ExplosionEvent
from app.engines.rally_capture import (
    breadth_blocks_explosion_side,
    explosion_exhausted,
    runner_strike_rank_bonus,
)
from app.models.schemas import ExplosiveRunner, Side, SymbolSnapshot


def test_blocks_put_on_bullish_breadth():
    blocked, reason = breadth_blocks_explosion_side(Side.PUT, "BULLISH", "EXPLODING")
    assert blocked
    assert "bullish" in reason


def test_blocks_elite_counter_breadth():
    """ELITE no longer bypasses breadth — directional lock requires CE-only on bullish."""
    blocked, reason = breadth_blocks_explosion_side(Side.PUT, "BULLISH", "ELITE")
    assert blocked
    assert "bullish" in reason


def test_exhaustion_blocks_late_chase():
    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77300,
        premium=160,
        velocity_3s=0.8,
        velocity_9s=12,
        velocity_15s=22,
        volume_surge=1.2,
        explosion_score=70,
        tier="EXPLODING",
        reason="test",
    )
    blocked, reason = explosion_exhausted(event)
    assert blocked
    assert "exhausted" in reason


def test_runner_strike_bonus_prefers_atm_leg():
    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77300,
        premium=140,
        velocity_3s=4,
        velocity_9s=6,
        velocity_15s=8,
        volume_surge=2,
        explosion_score=80,
        tier="EXPLODING",
        reason="test",
    )
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-07-01T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=77200,
        atmStrike=77200,
        dataAvailable=True,
        explosiveRunner=ExplosiveRunner(
            candidate=True,
            score=85,
            side=Side.CALL,
            strike=77300,
            premium=140,
        ),
    )
    assert runner_strike_rank_bonus(event, snap) >= 15
