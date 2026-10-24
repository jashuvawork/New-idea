"""Live broker mode must survive daily loss stop (entries pause only)."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.capital_allocator import update_daily_profit_gate
from app.engines.execution_mode import (
    execution_mode_label,
    paper_execution_active,
    sync_autotrader_execution_flags,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _loss_state() -> AutoTraderState:
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="t1",
            symbol="NIFTY",
            side=Side.CALL,
            strike=24000,
            entryPremium=50,
            lots=40,
            pnlInr=-35_000,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.SCALP,
        ),
    ]
    return state


def test_daily_loss_stop_does_not_imply_paper_execution():
    settings = Settings(
        enable_live_trading=True,
        auto_trading_enabled=True,
        paper_trading=True,
        daily_loss_stop_from_capital=False,
        daily_loss_stop_inr=30_000,
        daily_profit_stage_locks_enabled=True,
        daily_profit_target_inr=44_000,
        daily_profit_trail_inr=5_000,
        fallback_capital_inr=200_000,
        max_sizing_capital_inr=200_000,
    )
    with patch("app.engines.capital_allocator.get_settings", return_value=settings):
        gate = update_daily_profit_gate(_loss_state())
    assert gate.status == "DAILY_LOSS_STOP"
    assert not gate.newEntriesAllowed
    assert execution_mode_label(settings) == "LIVE"
    assert not paper_execution_active(settings)


def test_live_armed_stays_live_when_auto_trader_loop_disabled_in_env():
    settings = Settings(
        enable_live_trading=True,
        auto_trading_enabled=False,
        paper_trading=True,
    )
    assert execution_mode_label(settings) == "LIVE"
    assert not paper_execution_active(settings)


def test_sync_autotrader_flags_live_wins_over_stale_paper_env():
    settings = Settings(
        enable_live_trading=True,
        auto_trading_enabled=True,
        paper_trading=True,
    )
    state = AutoTraderState(paperTrading=True, liveTradingEnabled=False)
    sync_autotrader_execution_flags(state, settings)
    assert state.liveTradingEnabled is True
    assert state.autoTradingEnabled is True
    assert state.paperTrading is False


def test_sync_autotrader_live_armed_keeps_paper_false_when_auto_disabled():
    settings = Settings(
        enable_live_trading=True,
        auto_trading_enabled=False,
        paper_trading=True,
    )
    state = AutoTraderState(paperTrading=True, liveTradingEnabled=False)
    sync_autotrader_execution_flags(state, settings)
    assert state.liveTradingEnabled is True
    assert state.autoTradingEnabled is False
    assert state.paperTrading is False
