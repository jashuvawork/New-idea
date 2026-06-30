"""Whipsaw / churn guard tests."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.pretrade_validator import TradeRecord, validate_candidate
from app.engines.trade_selector import EntryCandidate
from app.engines.whipsaw_guards import (
    check_opposite_side_cooldown,
    check_session_whipsaw_pause,
    check_whipsaw_candidate,
    count_flip_flops,
    detect_ce_pe_whipsaw,
    is_bearish_sideways,
    record_trade_close,
    reset_whipsaw_guards,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.whipsaw_guards_enabled = True
    s.opposite_side_cooldown_seconds = 420
    s.opposite_side_cooldown_after_loss_seconds = 600
    s.ce_pe_whipsaw_velocity_threshold = 1.2
    s.ce_pe_whipsaw_pause_seconds = 900
    s.flip_flop_lookback_trades = 6
    s.flip_flop_max_opposites = 2
    s.bearish_sideways_halt_enabled = True
    s.bearish_sideways_block_scalps = True
    s.bearish_sideways_explosion_min_score = 78.0
    s.controlled_trading_enabled = True
    s.controlled_max_trades_per_day = 6
    s.min_seconds_between_entries = 240
    s.post_exit_min_seconds = 120
    s.post_loss_exit_min_seconds = 300
    s.chop_session_entry_interval_seconds = 300
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
    s.chop_day_guards_enabled = True
    return s


def _snap(symbol: str = "NIFTY", bias: str = "BEARISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=34.0,
        regime=Regime.RANGE_BOUND,
        breadth=Breadth(bias=bias, score=40, aligned=bias == "BEARISH"),
        explosiveRunnerWatchlist=[
            {"side": "CALL", "premiumVelocityPct": 2.0, "score": 70},
            {"side": "PUT", "premiumVelocityPct": 1.8, "score": 68},
        ],
    )


def _candidate(symbol: str = "NIFTY", side: Side = Side.CALL, score: float = 70.0, mode: str = "scalp") -> EntryCandidate:
    return EntryCandidate(
        symbol=symbol,
        snap=_snap(symbol),
        mode=mode,
        score=score,
        side=side,
        strike=23950.0,
        premium=35.0,
        strategy_type=StrategyType.SCALP,
        confidence=62.0,
        tqs=34.0,
    )


def setup_function():
    reset_whipsaw_guards()


@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
def test_detect_ce_pe_whipsaw_in_bearish_sideways(mock_settings):
    active, detail = detect_ce_pe_whipsaw(_snap())
    assert active is True
    assert detail["callVel"] >= 1.2
    assert detail["putVel"] >= 1.2


@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
def test_opposite_side_blocked_after_put_loss(mock_settings):
    record_trade_close("NIFTY", Side.PUT, -10_000, "simple_stop_loss")
    blocked, reason = check_opposite_side_cooldown("NIFTY", Side.CALL, _snap())
    assert blocked is True
    assert "opposite_side_cooldown" in reason


@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
def test_blocks_scalp_in_bearish_sideways(mock_settings):
    state = AutoTraderState()
    snap = _snap()
    snap.explosiveRunnerWatchlist = [{"side": "PUT", "premiumVelocityPct": 0.5, "score": 50}]
    snapshots = {"NIFTY": snap}
    ok, reason, _ = check_whipsaw_candidate(_candidate(side=Side.PUT), state, snapshots)
    assert not ok
    assert reason in ("bearish_sideways_no_scalps", "ce_pe_dual_velocity_NIFTY")


@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
def test_blocks_flip_after_put_loss(mock_settings):
    state = AutoTraderState()
    trades = [TradeRecord("NIFTY", "PUT", -18_968, "simple_stop_loss", 23950, "a")]
    snap = _snap()
    snap.explosiveRunnerWatchlist = []
    with patch("app.engines.whipsaw_guards.collect_session_trades", return_value=trades):
        ok, reason, _ = check_whipsaw_candidate(_candidate(side=Side.CALL), state, {"NIFTY": snap})
    assert not ok
    assert reason == "no_flip_after_PUT_loss"


@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
def test_flip_flop_pause(mock_settings):
    state = AutoTraderState()
    trades = [
        TradeRecord("NIFTY", "PUT", -1000, "", 23950, "1"),
        TradeRecord("NIFTY", "CALL", -2000, "", 23950, "2"),
        TradeRecord("SENSEX", "PUT", -3000, "", 76100, "3"),
        TradeRecord("SENSEX", "CALL", -4000, "", 77500, "4"),
    ]
    snapshots = {"NIFTY": _snap("NIFTY"), "SENSEX": _snap("SENSEX")}
    with patch("app.engines.whipsaw_guards.collect_session_trades", return_value=trades):
        assert count_flip_flops(trades, 6) == 2
        paused, reason, _ = check_session_whipsaw_pause(state, snapshots)
    assert paused is True
    assert "flip_flop" in reason


@patch("app.engines.pretrade_validator.get_settings", return_value=_settings())
@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
@patch("app.engines.chop_day_guards.get_settings")
def test_validate_blocks_rapid_reentry_after_loss(mock_chop, mock_ws, mock_pre):
    mock_chop.return_value = _settings()
    state = AutoTraderState()
    state.lastExit = {
        "at": datetime.now(IST).isoformat(),
        "pnlInr": -5000,
        "side": "PUT",
    }
    cand = _candidate(side=Side.PUT, score=72.0)
    ok, reason, _ = validate_candidate(cand, state, snapshots={"NIFTY": _snap()})
    assert not ok
    assert "pretrade_entry_interval_after_loss" in reason


@patch("app.engines.pretrade_validator.get_settings", return_value=_settings())
@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
@patch("app.engines.chop_day_guards.get_settings")
def test_validate_allows_entry_after_long_gap(mock_chop, mock_ws, mock_pre):
    mock_chop.return_value = _settings()
    state = AutoTraderState()
    state.lastExit = {
        "at": (datetime.now(IST) - timedelta(seconds=400)).isoformat(),
        "pnlInr": -5000,
        "side": "PUT",
    }
    cand = _candidate(side=Side.PUT, score=72.0, mode="explosion")
    cand.tier = "EXPLODING"
    with patch("app.engines.whipsaw_guards.check_bearish_sideways_entry", return_value=(False, "ok")):
        with patch("app.engines.whipsaw_guards.detect_ce_pe_whipsaw", return_value=(False, {})):
            ok, reason, _ = validate_candidate(cand, state, snapshots={"NIFTY": _snap()})
    assert ok or "last_n" in reason or "best_trades" in reason
