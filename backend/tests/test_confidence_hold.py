"""High-confidence hold and re-entry block tests."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.confidence_hold import (
    apply_confidence_hold_profile,
    high_confidence_reentry_blocked,
    is_high_confidence_trade,
    record_high_confidence_close,
    reset_confidence_hold_state,
    trade_entry_score,
)
from app.engines.simple_profit import evaluate_exit, get_session_targets
from app.models.schemas import OptimizedProfile, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.high_confidence_hold_enabled = True
    s.high_confidence_min_score = 72.0
    s.high_confidence_max_hold_multiplier = 1.8
    s.high_confidence_micro_min_best_points = 6.0
    s.high_confidence_min_hold_before_micro_seconds = 180
    s.high_confidence_micro_giveback_points = 4.5
    s.high_confidence_trail_keep_ratio = 0.55
    s.high_confidence_reentry_cooldown_seconds = 600
    s.high_confidence_reentry_score_uplift = 5.0
    s.bullish_hold_enabled = False
    s.scalp_trail_arm_points = 4.5
    s.scalp_trail_keep_ratio = 0.65
    s.scalp_trail_step_points = 2.0
    s.scalp_trail_tight_arm = 10.0
    s.scalp_trail_tight_points = 4.0
    s.scalp_stop_min_hold_seconds = 30
    s.scalp_micro_lock_min_best_points = 4.5
    s.scalp_min_hold_before_micro_lock_seconds = 90
    s.scalp_micro_giveback_points = 3.0
    s.runner_micro_giveback_points = 3.5
    s.runner_min_best_points = 8.0
    s.runner_trail_keep_ratio = 0.7
    s.scalp_no_progress_seconds = 120
    s.emergency_stop_enabled = False
    return s


def _trade(score: float = 75.0) -> PaperTrade:
    return PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23950,
        entryPremium=40.0,
        lots=30,
        openedAt=datetime.now(IST) - timedelta(seconds=60),
        strategyType=StrategyType.SCALP,
        bestPnlPoints=3.0,
        entryContext={"selectionScore": score, "breadth": "BEARISH"},
    )


def setup_function():
    reset_confidence_hold_state()


@patch("app.engines.confidence_hold.get_settings", return_value=_settings())
def test_high_confidence_detected(mock_settings):
    assert is_high_confidence_trade(_trade(75))
    assert not is_high_confidence_trade(_trade(65))


@patch("app.engines.confidence_hold.get_settings", return_value=_settings())
def test_extends_hold_profile(mock_settings):
    base = OptimizedProfile(
        targetPoints=8.0,
        stopPoints=3.0,
        microTargetPoints=2.5,
        maxHoldSeconds=300,
        sessionLabel="normal",
    )
    tuned = apply_confidence_hold_profile(_trade(78), base)
    assert tuned.maxHoldSeconds > base.maxHoldSeconds
    assert tuned.targetPoints > base.targetPoints


@patch("app.engines.simple_profit.get_settings", return_value=_settings())
@patch("app.engines.confidence_hold.get_settings", return_value=_settings())
@patch("app.engines.bullish_hold.get_settings")
def test_delays_micro_lock_for_high_confidence(mock_bh, mock_ch, mock_sp):
    mock_bh.return_value.bullish_hold_enabled = False
    trade = _trade(78)
    trade.bestPnlPoints = 5.0
    # Would micro-lock on low-conf profile; high-conf needs 6 best or 180s hold
    reason, _ = evaluate_exit(trade, 44.0, get_session_targets(), lot_multiplier=25)
    assert reason is None


@patch("app.engines.confidence_hold.get_settings", return_value=_settings())
def test_blocks_same_setup_reentry(mock_settings):
    record_high_confidence_close("NIFTY", Side.PUT, 23950, 75.0, 3000, "simple_micro_profit_lock")
    blocked, reason = high_confidence_reentry_blocked("NIFTY", Side.PUT, 23950, 74.0)
    assert blocked
    assert "high_conf_reentry" in reason
    blocked2, _ = high_confidence_reentry_blocked("NIFTY", Side.PUT, 23950, 81.0)
    assert not blocked2


@patch("app.engines.confidence_hold.get_settings", return_value=_settings())
def test_trade_entry_score_reads_context(mock_settings):
    assert trade_entry_score(_trade(73.5)) == 73.5
