"""Tighter explosive runner / explosion entry gates."""

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_profit import check_explosion_entry
from app.models.schemas import Breadth, Side, StrategyType, SuggestedTrade


def _event(**kwargs) -> ExplosionEvent:
    base = dict(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24500.0,
        premium=80.0,
        velocity_3s=2.2,
        velocity_9s=3.2,
        velocity_15s=4.0,
        volume_surge=1.4,
        explosion_score=48.0,
        tier="EXPLODING",
        reason="test",
    )
    base.update(kwargs)
    return ExplosionEvent(**base)


def _trade() -> SuggestedTrade:
    return SuggestedTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24500.0,
        lastPremium=80.0,
        tqs=55,
        strategyType=StrategyType.EXPLOSIVE,
        confidence=48,
    )


def test_weak_velocity_blocked():
    event = _event(velocity_3s=2.0, velocity_9s=2.8)
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert not ok
    assert reason == "velocity_too_low"


def test_score_48_exploding_blocked():
    event = _event(explosion_score=48.0, velocity_3s=3.0, velocity_9s=4.0)
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert not ok
    assert reason == "not_confirmed"


def test_score_45_still_blocked():
    event = _event(explosion_score=45.0, velocity_3s=3.0, velocity_9s=4.0)
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert not ok
    assert reason == "not_confirmed"


def test_score_58_exploding_confirmed():
    event = _event(explosion_score=58.0, velocity_3s=3.0, velocity_9s=4.0)
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert ok
    assert reason == "explosion_confirmed"


def test_score_55_exploding_still_blocked():
    event = _event(explosion_score=55.0, velocity_3s=3.0, velocity_9s=4.0)
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert not ok
    assert reason == "not_confirmed"


def test_score_52_exploding_still_blocked():
    event = _event(explosion_score=52.0, velocity_3s=3.0, velocity_9s=4.0)
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert not ok
    assert reason == "not_confirmed"


def test_breadth_alignment_required():
    event = _event(explosion_score=58.0, velocity_3s=3.0, velocity_9s=4.0)
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=False), False)
    assert not ok
    assert reason == "breadth_not_aligned"


def test_elite_bypasses_score_floor():
    event = _event(explosion_score=48.0, velocity_3s=3.0, velocity_9s=4.0, tier="ELITE")
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert ok
    assert reason == "elite_explosion"


def test_early_explosion_bypass_removed():
    event = _event(
        explosion_score=45.0,
        velocity_3s=3.6,
        velocity_9s=4.0,
        volume_surge=1.9,
        tier="EXPLODING",
    )
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert not ok
    assert reason == "not_confirmed"
