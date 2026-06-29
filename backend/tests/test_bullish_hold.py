"""Bullish-aligned hold logic (disabled in Jun 25 profile by default)."""

from unittest.mock import patch

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


@patch("app.engines.bullish_hold.get_settings")
def test_call_bullish_aligned(mock_settings):
    mock_settings.return_value.bullish_hold_enabled = True
    assert direction_aligned_with_breadth(_trade(Side.CALL, "BULLISH"))


@patch("app.engines.bullish_hold.get_settings")
def test_put_bearish_aligned(mock_settings):
    mock_settings.return_value.bullish_hold_enabled = True
    assert direction_aligned_with_breadth(_trade(Side.PUT, "BEARISH"))


def test_disabled_by_default():
    assert not direction_aligned_with_breadth(_trade(Side.CALL, "BULLISH"))
