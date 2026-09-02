"""Tests for phantom session trade filtering."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.engines.capital_allocator import compute_session_pnl
from app.engines.chop_day_guards import trades_cap_reached
from app.engines.session_trade_integrity import (
    is_phantom_session_trade,
    is_phantom_trade_row,
    purge_phantom_trades_from_state,
    real_session_closed_count,
)
from app.models.schemas import (
    AutoTraderState,
    MarketPhase,
    PaperTrade,
    Regime,
    Side,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")
_NOW = datetime.now(IST)


def _snap():
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=_NOW,
        marketPhase=MarketPhase.LIVE_MARKET,
        regime=Regime.CHOP,
    )


def test_phantom_by_insane_strike():
    trade = PaperTrade(
        id="p1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=2690124050.0,
        entryPremium=0.0,
        currentPremium=64.0,
        lots=1,
        pnlInr=4000.0,
        strategyType=StrategyType.EXPLOSIVE,
        status="CLOSED",
        openedAt=_NOW,
        entryContext={"brokerAdopted": True},
    )
    assert is_phantom_session_trade(trade) is True


def test_real_trade_not_phantom():
    trade = PaperTrade(
        id="r1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23950.0,
        entryPremium=37.6,
        currentPremium=29.0,
        lots=2,
        pnlInr=-1059.0,
        strategyType=StrategyType.EXPLOSIVE,
        status="CLOSED",
        openedAt=_NOW,
    )
    assert is_phantom_session_trade(trade) is False


def test_purge_phantoms_and_session_pnl():
    state = AutoTraderState(
        closedPaperTrades=[
            PaperTrade(
                id="p1",
                symbol="NIFTY",
                side=Side.PUT,
                strike=2690124050.0,
                entryPremium=0.0,
                currentPremium=64.0,
                lots=1,
                pnlInr=4000.0,
                strategyType=StrategyType.EXPLOSIVE,
                status="CLOSED",
                openedAt=_NOW,
            ),
            PaperTrade(
                id="r1",
                symbol="NIFTY",
                side=Side.PUT,
                strike=23950.0,
                entryPremium=37.6,
                currentPremium=29.0,
                lots=2,
                pnlInr=-1059.0,
                strategyType=StrategyType.EXPLOSIVE,
                status="CLOSED",
                openedAt=_NOW,
            ),
        ]
    )
    assert real_session_closed_count(state) == 1
    purged = purge_phantom_trades_from_state(state)
    assert purged == 1
    assert len(state.closedPaperTrades) == 1
    assert compute_session_pnl(state) == -1059.0


def test_trade_cap_ignores_phantoms():
    state = AutoTraderState(
        closedPaperTrades=[
            PaperTrade(
                id=f"p{i}",
                symbol="NIFTY",
                side=Side.PUT,
                strike=2690124050.0,
                entryPremium=0.0,
                currentPremium=64.0,
                lots=1,
                pnlInr=4000.0,
                strategyType=StrategyType.EXPLOSIVE,
                status="CLOSED",
                openedAt=_NOW,
            )
            for i in range(25)
        ]
    )
    hit, reason = trades_cap_reached(state, {"NIFTY": _snap()})
    assert hit is False
    assert reason == "ok"


def test_phantom_trade_row_from_disk():
    row = {
        "id": "x",
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 2690124050.0,
        "entryPremium": 0,
        "pnlInr": 4000,
        "status": "CLOSED",
    }
    assert is_phantom_trade_row(row) is True


def test_momentum_rally_armed_coil_config_defaults():
    from app.config import get_settings

    s = get_settings()
    assert bool(getattr(s, "momentum_rally_armed_coil_radar_enabled", True)) is True
    assert float(getattr(s, "momentum_rally_armed_coil_min_premium", 18.0)) == 18.0
