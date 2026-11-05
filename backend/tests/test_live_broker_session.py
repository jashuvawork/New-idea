"""Broker session helpers — paper book gates live in shared engines."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime.now(IST)


def test_live_session_loss_count_ignores_paper_and_phantom():
    from app.engines.live_broker_session import live_session_loss_count

    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="p1",
            symbol="NIFTY",
            side=Side.CALL,
            strike=24500,
            entryPremium=50,
            currentPremium=40,
            lots=1,
            pnlInr=-650,
            status="CLOSED",
            strategyType=StrategyType.EXPLOSIVE,
            openedAt=NOW,
            entryContext={"executionMode": "PAPER"},
        ),
        PaperTrade(
            id="l1",
            symbol="NIFTY",
            side=Side.CALL,
            strike=24500,
            entryPremium=50,
            currentPremium=40,
            lots=1,
            pnlInr=-650,
            status="CLOSED",
            strategyType=StrategyType.EXPLOSIVE,
            openedAt=NOW,
            entryContext={"executionMode": "LIVE"},
        ),
    ]
    assert live_session_loss_count(state) == 1
