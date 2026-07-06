"""Index pin guard — block PE fades at day high with bullish stocks."""

from app.engines.explosion_detector import ExplosionEvent
from app.engines.rally_capture import index_pin_blocks_put_explosion
from app.models.schemas import Breadth, ConstituentHeatmap, MarketProfile, Side, SpotChart, SymbolSnapshot


def _snap(*, spot: float = 24435.0, stock_breadth: float = 72.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-07-06T12:12:59+05:30",
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        spot=spot,
        spotChart=SpotChart(
            direction="NEUTRAL",
            spot=spot,
        ),
        marketProfile=MarketProfile(openingRangeHigh=24430.0, openingRangeLow=24300.0),
        constituentHeatmap=ConstituentHeatmap(
            symbol="NIFTY",
            dataAvailable=True,
            breadthPct=stock_breadth,
            bias="BULLISH",
        ),
        breadth=Breadth(score=78, bias="BEARISH", aligned=True, stockScore=stock_breadth),
    )


def test_blocks_put_at_day_high_with_bullish_stocks():
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24400.0,
        premium=62.0,
        velocity_3s=3.8,
        velocity_9s=2.5,
        velocity_15s=1.2,
        volume_surge=1.0,
        explosion_score=47.0,
        tier="EXPLODING",
        reason="+3.8%/3s",
    )
    blocked, reason = index_pin_blocks_put_explosion(event, _snap())
    assert blocked is True
    assert "pin" in reason


def test_allows_put_when_stocks_not_bullish():
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24400.0,
        premium=62.0,
        velocity_3s=3.8,
        velocity_9s=2.5,
        velocity_15s=1.2,
        volume_surge=1.0,
        explosion_score=47.0,
        tier="EXPLODING",
        reason="+3.8%/3s",
    )
    snap = _snap(stock_breadth=52.0)
    blocked, _ = index_pin_blocks_put_explosion(event, snap)
    assert blocked is False


def test_allows_call_at_pin():
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24450.0,
        premium=62.0,
        velocity_3s=3.8,
        velocity_9s=2.5,
        velocity_15s=1.2,
        volume_surge=1.0,
        explosion_score=47.0,
        tier="EXPLODING",
        reason="+3.8%/3s",
    )
    blocked, _ = index_pin_blocks_put_explosion(event, _snap())
    assert blocked is False
