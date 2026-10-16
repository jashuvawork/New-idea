"""Session close force-flat for live and paper-live parity."""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.replay_clock import install_replay_minutes, restore_replay_minutes
from app.engines.session_close_guard import (
    live_session_close_force_exit,
    live_session_close_force_exit_applies,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    HeatmapStrike,
    MarketPhase,
    PaperTrade,
    Side,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        breadth=Breadth(score=50, bias="NEUTRAL", aligned=False),
        heatmap=[
            HeatmapStrike(
                strike=24000,
                callLtp=120.0,
                putLtp=95.0,
                callInstrumentKey="NSE_FO|12345",
                putInstrumentKey="NSE_FO|67890",
            ),
        ],
    )


def _trade() -> PaperTrade:
    return PaperTrade(
        id="close-test",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24000,
        entryPremium=100.0,
        lots=2,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"explosionTier": "ELITE", "instrumentKey": "NSE_FO|12345"},
    )


def test_applies_at_1530_with_live_parity():
    settings = MagicMock()
    settings.live_session_close_force_exit_enabled = True
    settings.auto_trading_enabled = True
    settings.enable_live_trading = False
    settings.paper_live_parity_enabled = True
    settings.power_hour_end_hour = 15
    settings.power_hour_end_minute = 30
    token = install_replay_minutes(lambda: 15 * 60 + 30)
    try:
        with patch("app.engines.session_close_guard.get_market_phase", return_value="LIVE_MARKET"):
            with patch("app.engines.session_close_guard.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 9, 24, 15, 30, tzinfo=IST)
                assert live_session_close_force_exit_applies(settings) is True
    finally:
        restore_replay_minutes(token)


def test_does_not_apply_before_close():
    settings = MagicMock()
    settings.live_session_close_force_exit_enabled = True
    settings.auto_trading_enabled = True
    settings.enable_live_trading = True
    settings.paper_live_parity_enabled = True
    settings.power_hour_end_hour = 15
    settings.power_hour_end_minute = 30
    token = install_replay_minutes(lambda: 15 * 60 + 29)
    try:
        with patch("app.engines.session_close_guard.get_market_phase", return_value="LIVE_MARKET"):
            with patch("app.engines.session_close_guard.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 9, 24, 15, 29, tzinfo=IST)
                assert live_session_close_force_exit_applies(settings) is False
    finally:
        restore_replay_minutes(token)


def test_skips_when_parity_off_and_not_live():
    settings = MagicMock()
    settings.live_session_close_force_exit_enabled = True
    settings.auto_trading_enabled = True
    settings.enable_live_trading = False
    settings.paper_live_parity_enabled = False
    settings.power_hour_end_hour = 15
    settings.power_hour_end_minute = 30
    token = install_replay_minutes(lambda: 15 * 60 + 30)
    try:
        with patch("app.engines.session_close_guard.get_market_phase", return_value="LIVE_MARKET"):
            with patch("app.engines.session_close_guard.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 9, 24, 15, 30, tzinfo=IST)
                assert live_session_close_force_exit_applies(settings) is False
    finally:
        restore_replay_minutes(token)


@patch("app.engines.session_close_guard.get_settings")
def test_force_exit_pnl(mock_get_settings):
    settings = MagicMock()
    settings.live_session_close_force_exit_enabled = True
    settings.auto_trading_enabled = True
    settings.enable_live_trading = True
    settings.paper_live_parity_enabled = True
    settings.power_hour_end_hour = 15
    settings.power_hour_end_minute = 30
    mock_get_settings.return_value = settings
    token = install_replay_minutes(lambda: 15 * 60 + 30)
    try:
        with patch("app.engines.session_close_guard.get_market_phase", return_value="LIVE_MARKET"):
            with patch("app.engines.session_close_guard.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 9, 24, 15, 30, tzinfo=IST)
                trade = _trade()
                result = live_session_close_force_exit(trade, 120.0, lot_mult=25)
                assert result is not None
                reason, pnl = result
                assert reason == "live_session_market_close"
                assert pnl == 20.0 * 2 * 25
    finally:
        restore_replay_minutes(token)


@patch("app.engines.auto_trader.get_settings")
@patch("app.engines.auto_trader._risk_engine")
def test_process_open_trades_closes_at_session_end(mock_risk, mock_settings):
    from app.engines.auto_trader import _process_open_trades

    settings = MagicMock()
    settings.adaptive_exits_enabled = False
    settings.explosion_capture_mode = True
    settings.swing_trading_enabled = False
    settings.enable_live_trading = False
    settings.paper_live_parity_enabled = True
    settings.auto_trading_enabled = True
    settings.edge_engine_enabled = False
    settings.live_session_close_force_exit_enabled = True
    settings.power_hour_end_hour = 15
    settings.power_hour_end_minute = 30
    mock_settings.return_value = settings

    trade = _trade()
    state = AutoTraderState(openPaperTrades=[trade])
    token = install_replay_minutes(lambda: 15 * 60 + 30)
    try:
        with patch("app.engines.session_close_guard.get_market_phase", return_value="LIVE_MARKET"):
            with patch("app.engines.session_close_guard.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 9, 24, 15, 30, tzinfo=IST)
                asyncio.run(_process_open_trades(state, {"NIFTY": _snap()}, None))
        assert trade.status == "CLOSED"
        assert trade.exitReason == "live_session_market_close"
    finally:
        restore_replay_minutes(token)
