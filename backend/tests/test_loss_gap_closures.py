"""Close remaining loss gaps: EXPIRY WORST policy, hold clip, failed-launch nearby."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.session_mode_feedback import failed_launch_reentry_blocked
from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence
from app.models.schemas import AutoTraderState, Side

IST = ZoneInfo("Asia/Kolkata")


def _winner_evidence(**overrides):
    evidence = {
        "mode": "explosion",
        "tier": "EXPLODING",
        "explosionScore": 76.0,
        "tqs": 55.0,
        "velocity3s": 2.3,
        "velocity9s": 1.8,
        "localBaseMovePct": 14.0,
        "firstLift": False,
        "armedBaseLaunch": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "orderflowPositive": True,
        "cvdBuying": False,
        "cvdAcceleration": False,
        "flatVerticalQuality": 71.0,
        "timingAssessment": "GOOD",
    }
    evidence.update(overrides)
    return evidence


def test_expiry_worst_blocks_mid_exploding_winner_sleeve():
    """Afternoon EXPIRY WORST mid-EXPLODING must not clear WINNER via soft floors."""
    evidence = _winner_evidence(cvdBuying=True)
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
        day_mode="EXPIRY WORST",
    )
    assert decision.allowed is False
    assert "expiry_worst" in decision.reason


def test_expiry_worst_allows_true_elite_with_raised_floors():
    evidence = _winner_evidence(
        tier="ELITE",
        explosionScore=92.0,
        flatVerticalQuality=88.0,
        velocity3s=3.2,
        velocity9s=2.5,
        cvdBuying=True,
        cvdAcceleration=True,
    )
    ranking = rank_trade_evidence(evidence)
    # May land S / TOP_FTV_A / WINNER depending on grade — must be allowed.
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
        day_mode="EXPIRY WORST",
    )
    assert decision.allowed is True


def test_worst_day_winner_requires_cvd_buying():
    evidence = _winner_evidence(
        tier="ELITE",
        explosionScore=82.0,
        flatVerticalQuality=78.0,
        velocity3s=2.4,
        cvdBuying=False,
    )
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
        day_mode="WORST",
    )
    assert decision.allowed is False
    assert decision.reason == "winner_local_base_worst_requires_cvd_buying"


def test_normal_day_winner_still_admits_without_cvd():
    evidence = _winner_evidence(
        tier="ELITE",
        explosionScore=82.0,
        flatVerticalQuality=78.0,
        velocity3s=2.4,
        cvdBuying=False,
    )
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
        day_mode="NORMAL",
    )
    assert decision.mode == "WINNER_LOCAL_BASE"


def _closed(*, exit_reason: str, strike: float = 24250.0, minutes_ago: float = 10.0):
    t = MagicMock()
    t.id = "fail-1"
    t.symbol = "NIFTY"
    t.side = Side.PUT
    t.strike = strike
    t.strategyType = "EXPLOSIVE"
    t.exitReason = exit_reason
    t.pnlInr = -900.0
    t.bestPnlPoints = 0.0
    t.closedAt = datetime.now(IST) - timedelta(minutes=minutes_ago)
    t.openedAt = t.closedAt - timedelta(seconds=25)
    t.entryContext = {"selectionMode": "explosion"}
    return t


@patch("app.engines.session_mode_feedback.get_settings")
def test_never_green_stop_arms_failed_launch_cooldown(mock_settings):
    s = MagicMock()
    s.explosion_failed_launch_reentry_block_enabled = True
    s.explosion_failed_launch_reentry_cooldown_seconds = 1800
    s.explosion_failed_launch_reentry_strike_steps = 1
    s.explosion_failed_launch_reentry_exit_reasons_csv = (
        "explosion_failed_launch,explosion_never_green_stop,adaptive_stop_loss"
    )
    s.explosion_failed_launch_max_best_points = 1.0
    mock_settings.return_value = s
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed(exit_reason="explosion_never_green_stop", strike=24250.0)
    ]
    blocked, meta = failed_launch_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT, strike=24250.0,
    )
    assert blocked is True
    assert meta["priorExitReason"] == "explosion_never_green_stop"


@patch("app.engines.session_mode_feedback.get_settings")
def test_failed_launch_blocks_adjacent_atm_strike(mock_settings):
    s = MagicMock()
    s.explosion_failed_launch_reentry_block_enabled = True
    s.explosion_failed_launch_reentry_cooldown_seconds = 1800
    s.explosion_failed_launch_reentry_strike_steps = 1
    s.explosion_failed_launch_reentry_exit_reasons_csv = (
        "explosion_failed_launch,explosion_never_green_stop,adaptive_stop_loss"
    )
    s.explosion_failed_launch_max_best_points = 1.0
    mock_settings.return_value = s
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed(exit_reason="explosion_failed_launch", strike=24250.0)
    ]
    # NIFTY step=50 → 24300 is one step away.
    blocked, meta = failed_launch_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT, strike=24300.0,
    )
    assert blocked is True
    assert meta["priorStrike"] == 24250.0
