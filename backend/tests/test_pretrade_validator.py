"""Pre-trade validator — controlled entries, index backtest selection."""

from unittest.mock import MagicMock, patch

from app.engines.pretrade_validator import (
    TradeRecord,
    backtest_session_summary,
    check_min_entry_interval,
    collect_session_trades,
    compute_symbol_stats,
    index_rank_from_backtest,
    validate_candidate,
)
from app.engines.trade_selector import EntryCandidate
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    PaperTrade,
    Regime,
    Side,
    StrategyType,
    SymbolSnapshot,
)
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.controlled_trading_enabled = True
    s.controlled_max_trades_per_day = 10
    s.controlled_rally_trade_cap_bonus = 4
    s.daily_18pct_strategy_enabled = False
    s.daily_18pct_chop_max_trades = 10
    s.day_adaptive_enabled = False
    s.min_seconds_between_entries = 180
    s.pretrade_min_rank_score = 65.0
    s.pretrade_min_symbol_trades_for_stats = 3
    s.pretrade_block_symbol_pf_below = 0.5
    s.pretrade_block_symbol_net_inr_below = -15_000.0
    s.pretrade_similar_side_lookback = 5
    s.pretrade_similar_side_min_trades = 3
    s.pretrade_block_similar_pf_below = 0.4
    s.index_selection_pf_bonus = 12.0
    s.counter_breadth_min_score = 70
    s.last_n_trades_gate_enabled = True
    s.last_n_trades_lookback = 5
    s.last_n_trades_min_count = 3
    s.last_n_pause_after_losses = 4
    s.last_n_elevate_after_losses = 3
    s.last_n_elevated_min_rank_score = 72.0
    s.last_n_block_pf_below = 0.35
    s.last_n_block_net_inr_below = -25_000.0
    s.best_trades_only_enabled = True
    s.best_trades_min_rank_score = 68.0
    s.best_trades_explosion_only_after_losses = 3
    s.chart_alignment_enabled = False
    s.whipsaw_guards_enabled = False
    s.post_exit_min_seconds = 120
    s.post_loss_exit_min_seconds = 300
    s.chop_session_entry_interval_seconds = 300
    s.high_confidence_hold_enabled = False
    s.moneyness_selection_enabled = False
    return s


def _snap(symbol: str, bias: str = "BEARISH") -> SymbolSnapshot:
    put_aligned = bias == "BEARISH"
    call_aligned = bias == "BULLISH"
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=45,
        regime=Regime.TREND_EXPANSION,
        breadth=Breadth(
            bias=bias,
            score=45,
            aligned=put_aligned if bias == "BEARISH" else call_aligned,
        ),
        suggestedTrades=[],
        explosionAlerts=[],
    )


def _candidate(symbol: str, side: Side, score: float = 60.0) -> EntryCandidate:
    return EntryCandidate(
        symbol=symbol,
        snap=_snap(symbol),
        mode="scalp",
        score=score,
        side=side,
        strike=23900.0,
        premium=80.0,
        strategy_type=StrategyType.SCALP,
        confidence=62.0,
        tqs=40.0,
    )


def test_index_rank_prefers_better_session_pf():
    stats = compute_symbol_stats([
        TradeRecord("NIFTY", "CALL", -10000, "simple_stop_loss"),
        TradeRecord("NIFTY", "CALL", -8000, "simple_stop_loss"),
        TradeRecord("NIFTY", "CALL", -5000, "simple_stop_loss"),
        TradeRecord("SENSEX", "PUT", 4000, "simple_micro_profit_lock"),
        TradeRecord("SENSEX", "PUT", 3500, "simple_micro_profit_lock"),
        TradeRecord("SENSEX", "PUT", 5000, "simple_profit_target_hit"),
    ])
    with patch("app.engines.pretrade_validator.get_settings", return_value=_settings()):
        adj = index_rank_from_backtest(stats)
    assert adj["SENSEX"] == 12.0
    assert adj.get("NIFTY", 0) < 0


@patch("app.engines.pretrade_validator.get_settings")
def test_blocks_symbol_with_bad_session_pf(mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="1", symbol="NIFTY", side=Side.CALL, strike=23900,
            entryPremium=50, lots=10, openedAt=datetime.now(IST),
            pnlInr=-10000, strategyType=StrategyType.SCALP,
        ),
        PaperTrade(
            id="2", symbol="NIFTY", side=Side.CALL, strike=23900,
            entryPremium=50, lots=10, openedAt=datetime.now(IST),
            pnlInr=-8000, strategyType=StrategyType.SCALP,
        ),
        PaperTrade(
            id="3", symbol="NIFTY", side=Side.CALL, strike=23900,
            entryPremium=50, lots=10, openedAt=datetime.now(IST),
            pnlInr=-5000, strategyType=StrategyType.SCALP,
        ),
    ]
    ok, reason, _ = validate_candidate(_candidate("NIFTY", Side.PUT, score=72.0), state)
    assert not ok
    assert "pretrade_symbol_pf" in reason or "last_n" in reason


@patch("app.engines.pretrade_validator.get_settings")
def test_blocks_rapid_reentry_interval(mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    state.lastExit = {"at": datetime.now(IST).isoformat(), "pnlInr": -1000}
    ok, reason = check_min_entry_interval(state)
    assert not ok
    assert "pretrade_entry_interval" in reason


@patch("app.engines.pretrade_validator.get_settings")
def test_blocks_counter_breadth_low_score(mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    cand = _candidate("NIFTY", Side.CALL, score=66.0)
    cand.confidence = 62.0
    ok, reason, _ = validate_candidate(cand, state)
    assert not ok
    assert reason.startswith("directional_") or reason == "pretrade_counter_breadth"


def test_backtest_summary_recommends_index():
    trades = [
        TradeRecord("NIFTY", "CALL", -5000),
        TradeRecord("NIFTY", "CALL", -4000),
        TradeRecord("NIFTY", "CALL", -3000),
        TradeRecord("SENSEX", "PUT", 3000),
        TradeRecord("SENSEX", "PUT", 2500),
        TradeRecord("SENSEX", "PUT", 2000),
    ]
    with patch("app.engines.pretrade_validator.get_settings", return_value=_settings()):
        summary = backtest_session_summary(trades)
    assert summary["recommendedIndex"] == "SENSEX"
    assert summary["symbolStats"]["NIFTY"]["profit_factor"] == 0.0


@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.worst_day_guard.get_settings")
@patch("app.engines.pretrade_validator.get_settings")
def test_filter_drops_nifty_after_bad_session(mock_settings, mock_wd_settings, mock_bd_settings):
    from app.engines.pretrade_validator import filter_candidates_pretrade

    s = _settings()
    s.worst_day_pause_enabled = False
    s.bad_day_routing_enabled = False
    s.expiry_day_guards_enabled = False
    mock_settings.return_value = s
    mock_wd_settings.return_value = s
    mock_bd_settings.return_value = s
    state = AutoTraderState()
    for i, pnl in enumerate([-10000, -8000, -5000]):
        state.closedPaperTrades.append(PaperTrade(
            id=f"n{i}", symbol="NIFTY", side=Side.CALL, strike=23900,
            entryPremium=50, lots=10, openedAt=datetime.now(IST),
            pnlInr=pnl, strategyType=StrategyType.SCALP,
        ))
    from datetime import timedelta
    state.lastExit = {
        "at": (datetime.now(IST) - timedelta(seconds=400)).isoformat(),
        "pnlInr": -5000,
    }
    nifty = _candidate("NIFTY", Side.PUT, score=72.0)
    sensex = _candidate("SENSEX", Side.PUT, score=75.0)
    sensex.mode = "explosion"
    viable = filter_candidates_pretrade([nifty, sensex], state, {})
    symbols = {c.symbol for c in viable}
    assert "NIFTY" not in symbols
    assert "SENSEX" in symbols


@patch("app.engines.pretrade_validator.get_settings")
def test_last_five_all_losses_pauses_session(mock_settings):
    from app.engines.pretrade_validator import check_last_n_trades_pause

    mock_settings.return_value = _settings()
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id=str(i), symbol="NIFTY", side=Side.PUT, strike=23900,
            entryPremium=80, currentPremium=70, lots=1,
            openedAt=datetime.now(IST), strategyType=StrategyType.SCALP,
            pnlInr=-10_000, exitReason="simple_stop_loss",
        )
        for i in range(5)
    ]
    paused, reason, summary = check_last_n_trades_pause(state)
    assert paused
    assert "last_n_pause" in reason
    assert summary["losses"] == 5
    assert summary["wins"] == 0


@patch("app.engines.pretrade_validator.get_settings")
def test_last_three_losses_elevates_rank(mock_settings):
    from app.engines.pretrade_validator import check_last_n_candidate_gate, last_n_elevated_min_rank

    mock_settings.return_value = _settings()
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id=str(i), symbol="NIFTY", side=Side.CALL, strike=23900,
            entryPremium=80, currentPremium=70, lots=1,
            openedAt=datetime.now(IST), strategyType=StrategyType.SCALP,
            pnlInr=-5000 if i < 3 else 3000,
            exitReason="simple_stop_loss" if i < 3 else "simple_micro_profit_lock",
        )
        for i in range(5)
    ]
    assert last_n_elevated_min_rank(state) == 72.0
    ok, reason, _ = check_last_n_candidate_gate(_candidate("NIFTY", Side.PUT, score=65), state)
    assert not ok
    assert "elevated_rank" in reason
    explosion = _candidate("NIFTY", Side.PUT, score=75.0)
    explosion.mode = "explosion"
    ok, reason, _ = check_last_n_candidate_gate(explosion, state)
    assert ok


@patch("app.engines.pretrade_validator.get_settings")
def test_best_trades_blocks_low_rank(mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    ok, reason, _ = validate_candidate(_candidate("NIFTY", Side.PUT, score=60), state)
    assert not ok
    assert "best_trades_rank" in reason or "pretrade_rank" in reason


@patch("app.engines.pretrade_validator.get_settings")
def test_session_reset_clears_last_n_gate(mock_settings, tmp_path):
    from app.engines.pretrade_validator import check_last_n_trades_pause, collect_session_trades
    from app.services import trade_store

    mock_settings.return_value = _settings()
    with patch.object(trade_store, "get_store_dir", return_value=tmp_path):
        state = AutoTraderState()
        state.closedPaperTrades = [
            PaperTrade(
                id="old", symbol="SENSEX", side=Side.CALL, strike=77500,
                entryPremium=100, currentPremium=90, lots=1,
                openedAt=datetime.now(IST), strategyType=StrategyType.EXPLOSIVE,
                pnlInr=-20_000, exitReason="adaptive_stop_loss",
            )
        ]
        trade_store.set_session_reset_at()
        paused, reason, _ = check_last_n_trades_pause(state)
        assert not paused
        assert collect_session_trades(state) == []


@patch("app.engines.pretrade_validator.get_settings")
@patch("app.engines.chop_day_guards.in_momentum_rally_window", return_value=True)
def test_momentum_rally_bypasses_last_n_pause(mock_rally, mock_settings):
    from app.engines.pretrade_validator import check_last_n_trades_pause
    from app.models.schemas import ExplosiveRunner, MarketPhase, RunnerSignal, SymbolSnapshot

    s = _settings()
    s.last_n_momentum_rally_bypass_enabled = True
    mock_settings.return_value = s
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id=str(i), symbol="SENSEX", side=Side.CALL, strike=77500,
            entryPremium=100, currentPremium=80, lots=1,
            openedAt=datetime.now(IST), strategyType=StrategyType.EXPLOSIVE,
            pnlInr=-12_000, exitReason="adaptive_stop_loss",
        )
        for i in range(3)
    ]
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        explosiveRunner=ExplosiveRunner(
            strike=77800,
            side=Side.CALL,
            score=55,
            signal=RunnerSignal(premiumVelocityPct=3.5, volumeSurge=1.6, score=55),
        ),
    )
    paused, reason, _ = check_last_n_trades_pause(state, {"SENSEX": snap})
    assert not paused
    assert reason == "momentum_rally_bypass"
