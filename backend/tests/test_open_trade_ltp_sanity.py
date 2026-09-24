"""Open-trade LTP sanity — reject spike glitches vs entry / REST / tape."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.ltp_sanity import (
    apply_open_trade_mark,
    reconcile_max_ltp,
    sanitize_open_trade_ltp,
)
from app.engines.replay_clock import install_replay_minutes, restore_replay_minutes
from app.models.schemas import (
    Breadth,
    HeatmapStrike,
    MarketPhase,
    PaperTrade,
    Side,
    StrategyType,
    SymbolSnapshot,
)
from app.services.tick_store import clear, record_tick

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.open_trade_ltp_sanity_enabled = True
    s.open_trade_ltp_max_dev_from_entry_mult = 2.75
    s.open_trade_ltp_max_step_ratio = 1.32
    s.open_trade_ltp_ws_over_rest_ratio = 1.18
    s.open_trade_ltp_median_confirm_ratio = 0.92
    s.open_trade_ltp_median_confirm_max_ratio = 1.12
    s.open_trade_ltp_recent_window_seconds = 12.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(put_ltp: float = 200.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        breadth=Breadth(score=50, bias="NEUTRAL", aligned=False),
        heatmap=[
            HeatmapStrike(
                strike=73800,
                callLtp=100.0,
                putLtp=put_ltp,
                callInstrumentKey="BSE_FO|1",
                putInstrumentKey="BSE_FO|839636",
            ),
        ],
    )


def _trade(**ctx) -> PaperTrade:
    base = {
        "instrumentKey": "BSE_FO|839636",
        "lastSanitizedLtp": 200.0,
    }
    base.update(ctx)
    return PaperTrade(
        id="sanity-1",
        symbol="SENSEX",
        side=Side.PUT,
        strike=73800,
        entryPremium=146.82,
        currentPremium=200.0,
        lots=61,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        maxLtp=535.95,
        bestPnlPoints=389.13,
        entryContext=base,
    )


@patch("app.engines.ltp_sanity.get_settings")
def test_rejects_sep24_style_spike_vs_entry_and_rest(mock_gs):
    mock_gs.return_value = _settings()
    trade = _trade()
    clear()
    record_tick("BSE_FO|839636", 198.0)
    record_tick("BSE_FO|839636", 201.0)

    assert sanitize_open_trade_ltp(trade, 535.95, snap=_snap(200.0)) is None


@patch("app.engines.ltp_sanity.get_settings")
def test_accepts_realistic_mark_near_rest(mock_gs):
    mock_gs.return_value = _settings()
    trade = _trade(lastSanitizedLtp=190.0)
    clear()
    for px in (190.0, 195.0, 200.0, 205.0):
        record_tick("BSE_FO|839636", px)

    out = sanitize_open_trade_ltp(trade, 205.0, snap=_snap(200.0))
    assert out == 205.0


@patch("app.engines.ltp_sanity.get_settings")
def test_reconcile_max_ltp_clamps_phantom_peak(mock_gs):
    mock_gs.return_value = _settings()
    trade = _trade()
    trade.currentPremium = 219.0
    trade.entryContext["lastSanitizedLtp"] = 219.0

    reconcile_max_ltp(trade)

    assert trade.maxLtp <= 219.0
    assert trade.maxLtp > 200.0
    assert trade.entryContext.get("maxLtpRepaired") is True


@patch("app.engines.ltp_sanity.get_settings")
@patch("app.engines.auto_trader.get_settings")
@patch("app.engines.auto_trader._risk_engine")
def test_process_open_trades_ignores_spike_mark(mock_risk, mock_at_settings, mock_gs):
    import asyncio

    from app.engines.auto_trader import _process_open_trades
    from app.models.schemas import AutoTraderState

    mock_gs.return_value = _settings()
    settings = MagicMock()
    settings.adaptive_exits_enabled = False
    settings.explosion_capture_mode = True
    settings.swing_trading_enabled = False
    settings.enable_live_trading = False
    settings.paper_live_parity_enabled = True
    settings.auto_trading_enabled = True
    settings.edge_engine_enabled = False
    settings.live_session_close_force_exit_enabled = False
    settings.open_trade_ltp_sanity_enabled = True
    settings.open_trade_ltp_max_dev_from_entry_mult = 2.75
    settings.open_trade_ltp_max_step_ratio = 1.32
    settings.open_trade_ltp_ws_over_rest_ratio = 1.18
    settings.open_trade_ltp_median_confirm_ratio = 0.88
    settings.open_trade_ltp_recent_window_seconds = 12.0
    mock_at_settings.return_value = settings

    trade = _trade()
    state = AutoTraderState(openPaperTrades=[trade])
    clear()
    record_tick("BSE_FO|839636", 200.0)
    record_tick("BSE_FO|839636", 205.0)

    token = install_replay_minutes(lambda: 15 * 60 + 20)
    try:
        with patch(
            "app.engines.snapshot_fast.get_ltp",
            return_value=529.0,
        ):
            asyncio.run(_process_open_trades(state, {"SENSEX": _snap(205.0)}, None))
    finally:
        restore_replay_minutes(token)

    assert trade.currentPremium is not None
    assert trade.currentPremium < 400.0
    assert trade.maxLtp < 400.0


@patch("app.engines.ltp_sanity.get_settings")
def test_apply_open_trade_mark_keeps_last_on_spike(mock_gs):
    mock_gs.return_value = _settings()
    trade = _trade()
    trade.currentPremium = 205.0
    trade.entryContext["lastSanitizedLtp"] = 205.0

    out = apply_open_trade_mark(trade, 535.0, snap=_snap(205.0))
    assert out == 205.0
