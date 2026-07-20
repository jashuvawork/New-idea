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
    s.whipsaw_momentum_rally_bypass_enabled = True
    s.whipsaw_dual_retrigger_cooldown_seconds = 300
    s.whipsaw_single_side_surge_bypass_enabled = True
    s.whipsaw_dominant_velocity_min = 2.5
    s.whipsaw_dominant_velocity_ratio = 1.6
    s.quick_sideways_allow_bearish_chop = True
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
    s.whipsaw_guards_enabled = True
    s.moneyness_selection_enabled = False
    s.momentum_rally_start_hour = 10
    s.momentum_rally_start_minute = 0
    s.momentum_rally_end_hour = 13
    s.momentum_rally_end_minute = 45
    s.daily_18pct_strategy_enabled = False
    s.daily_18pct_chop_max_trades = 10
    s.controlled_rally_trade_cap_bonus = 4
    s.day_adaptive_enabled = False
    s.whipsaw_elite_momentum_flip_bypass_enabled = False
    s.whipsaw_elite_momentum_flip_min_score = 85.0
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
def test_quick_sideways_allowed_in_bearish_chop(mock_settings):
    from app.engines.whipsaw_guards import check_bearish_sideways_entry

    cand = _candidate(side=Side.CALL, score=62.0, mode="quick_sideways")
    blocked, reason = check_bearish_sideways_entry(cand, {"NIFTY": _snap()})
    assert not blocked
    assert reason == "ok"


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


@patch("app.engines.whipsaw_guards.get_settings")
def test_elite_momentum_bypasses_flip_after_put_loss(mock_settings):
    """Jul20 NIFTY 24200 CE → ~102: ELITE flat→vertical must flip after PUT loss."""
    s = _settings()
    s.whipsaw_elite_momentum_flip_bypass_enabled = True
    s.bearish_sideways_block_scalps = False
    mock_settings.return_value = s
    state = AutoTraderState()
    trades = [TradeRecord("NIFTY", "PUT", -1096.9, "adaptive_stop_loss", 23950, "a")]
    snap = _snap()
    snap.explosiveRunnerWatchlist = []
    from app.engines.explosion_detector import ExplosionEvent

    cand = _candidate(side=Side.CALL, score=100.0, mode="explosion")
    cand.tier = "ELITE"
    cand.explosion_event = ExplosionEvent(
        symbol="NIFTY", side=Side.CALL, strike=24200, premium=102.0,
        velocity_3s=5.3, velocity_9s=4.0, velocity_15s=3.0,
        volume_surge=2.5, explosion_score=100, tier="ELITE", reason="flat_then_vertical",
        daily_move_pct=55.0, peak_move_pct=57.0,
    )
    cand.alert = {
        "ictFlatThenVertical": True,
        "dailyMovePct": 55.0,
        "peakMovePct": 57.0,
        "tier": "ELITE",
    }
    with patch("app.engines.whipsaw_guards.collect_session_trades", return_value=trades), patch(
        "app.engines.whipsaw_guards.detect_ce_pe_whipsaw", return_value=(False, {}),
    ), patch(
        "app.engines.whipsaw_guards.check_bearish_sideways_entry", return_value=(False, "ok"),
    ), patch(
        "app.engines.whipsaw_guards.check_opposite_side_cooldown", return_value=(False, "ok"),
    ):
        ok, reason, meta = check_whipsaw_candidate(cand, state, {"NIFTY": snap})
    assert ok, reason
    assert meta.get("eliteMomentumFlipBypass") is True


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


@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
@patch("app.engines.chop_day_guards.in_momentum_rally_window", return_value=True)
@patch("app.engines.chop_day_guards.is_momentum_surge", return_value=True)
def test_momentum_rally_bypasses_whipsaw_pause(mock_surge, mock_window, mock_settings):
    from app.engines.whipsaw_guards import trigger_whipsaw_pause, whipsaw_pause_active

    trigger_whipsaw_pause(900, "flip_flop_churn")
    paused, reason = whipsaw_pause_active({"NIFTY": _snap()})
    assert not paused
    assert reason == "momentum_rally_bypass"


@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
def test_whipsaw_summary_does_not_trigger_pause(mock_settings):
    from app.engines.whipsaw_guards import whipsaw_guard_summary, whipsaw_pause_active

    state = AutoTraderState()
    snapshots = {"NIFTY": _snap("NIFTY")}
    assert not whipsaw_pause_active(snapshots)[0]
    whipsaw_guard_summary(state, snapshots)
    assert not whipsaw_pause_active(snapshots)[0]
    paused, reason, _ = check_session_whipsaw_pause(state, snapshots)
    assert paused
    assert "ce_pe_whipsaw" in reason or "flip_flop" in reason


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


@patch("app.engines.worst_day_guard.worst_day_allows_candidate", return_value=(True, "ok", {}))
@patch("app.engines.bad_day_routing.check_bad_day_candidate", return_value=(True, "ok", {}))
@patch("app.engines.pretrade_validator.get_settings", return_value=_settings())
@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
@patch("app.engines.chop_day_guards.get_settings")
def test_validate_allows_entry_after_long_gap(mock_chop, mock_ws, mock_pre, mock_bad_day, mock_worst_day):
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


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
def test_dominant_call_surge_not_dual_whipsaw(mock_settings, mock_morning):
    snap = _snap()
    snap.explosiveRunnerWatchlist = [
        {"side": "CALL", "premiumVelocityPct": 3.5, "score": 72},
        {"side": "PUT", "premiumVelocityPct": 1.1, "score": 50},
    ]
    active, detail = detect_ce_pe_whipsaw(snap)
    assert active is False
    assert detail.get("dominantSurge") is True


@patch("app.engines.whipsaw_guards.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.single_side_surge_session_bypass", return_value=True)
def test_single_side_surge_bypasses_session_pause(mock_bypass, mock_window, mock_settings):
    from app.engines.whipsaw_guards import trigger_whipsaw_pause, whipsaw_pause_active

    trigger_whipsaw_pause(900, "dual_leg_whipsaw")
    paused, reason = whipsaw_pause_active({"NIFTY": _snap()})
    assert not paused
    assert reason == "single_side_surge_bypass"
