"""Bullish-aligned hold logic."""

from app.engines.bullish_hold import direction_aligned_with_breadth
from app.models.schemas import PaperTrade, Side, StrategyType
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _trade(side: Side, breadth: str) -> PaperTrade:
    return PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=side,
        strike=24000,
        entryPremium=50,
        lots=30,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.SCALP,
        entryContext={"breadth": breadth},
    )


def test_call_bullish_aligned():
    assert direction_aligned_with_breadth(_trade(Side.CALL, "BULLISH"))


def test_put_bearish_aligned():
    assert direction_aligned_with_breadth(_trade(Side.PUT, "BEARISH"))


def test_call_neutral_not_aligned():
    assert not direction_aligned_with_breadth(_trade(Side.CALL, "NEUTRAL"))
