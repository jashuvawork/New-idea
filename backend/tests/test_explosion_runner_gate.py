"""Jun 25 explosion entry gates — score 45+, no breadth block when sure-shot off."""

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
    event = _event(velocity_3s=1.5, velocity_9s=2.5)
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert not ok
    assert reason == "velocity_too_low"


def test_score_45_exploding_confirmed():
    event = _event(explosion_score=48.0, velocity_3s=3.0, velocity_9s=4.0)
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert ok
    assert reason == "explosion_confirmed"


def test_score_40_blocked():
    event = _event(explosion_score=40.0, velocity_3s=1.5, velocity_9s=2.0, tier="BUILDING")
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert not ok
    assert reason == "tier_BUILDING_not_tradeable"


def test_neutral_breadth_allowed_when_sure_shot_off():
    event = _event(explosion_score=60.0, velocity_3s=3.0, velocity_9s=4.0)
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="NEUTRAL", aligned=False), False)
    assert ok
    assert reason == "explosion_confirmed"


def test_elite_bypasses_score_floor():
    event = _event(explosion_score=40.0, velocity_3s=3.0, velocity_9s=4.0, tier="ELITE")
    ok, reason = check_explosion_entry(event, _trade(), Breadth(score=50, bias="BULLISH", aligned=True), False)
    assert ok
    assert reason == "elite_explosion"


def test_expiry_psychology_caution_blocks_explosion():
    from datetime import datetime
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    from app.models.schemas import MarketPhase, SymbolSnapshot

    IST = ZoneInfo("Asia/Kolkata")
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-07-07",
        psychology={"label": "CAUTION"},
    )
    event = _event(explosion_score=60.0, velocity_3s=3.0, velocity_9s=4.0)
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-07"):
        ok, reason = check_explosion_entry(
            event, _trade(), Breadth(score=50, bias="NEUTRAL", aligned=False), False, snap=snap,
        )
    assert not ok
    assert reason == "expiry_psychology_block_caution"
