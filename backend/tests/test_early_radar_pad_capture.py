"""Early radar pad capture — FTV/V/ELITE/EXPLODING at session trough."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.early_radar_pad_capture import (
    EARLY_RADAR_PAD_READY,
    cold_trough_pad_lift_signal,
    early_radar_pad_capture_active,
    early_radar_pad_entry_readiness,
    stamp_early_radar_pad_capture,
    watch_local_base_pad_lift_signal,
    watch_local_base_pad_structure,
)
from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence, ftv_policy_settings
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap(*, spot: float = 24180.0, atm: float = 24150.0, direction: str = "BEARISH"):
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=spot,
        atmStrike=atm,
        spotChart=SpotChart(
            direction=direction,
            rsi=42.0,
            macdBias="BEARISH",
            macdHistogram=-0.1,
            macd=-0.05,
            macdSignal=0.02,
            momentum5Pct=-0.02,
            momentum15Pct=0.01,
        ),
    )


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_early_pad_active_at_session_trough_ftv_building(mock_settings):
    mock_settings.return_value = Settings()
    alert = {
        "tier": "BUILDING",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 33.0,
        "offLowMovePct": 0.0,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "volumeAwaken": True,
        "explosionScore": 58.0,
        "peakMovePct": 12.0,
    }
    snap = _snap()
    assert early_radar_pad_capture_active(alert, snap) is True
    stamped = dict(alert)
    assert stamp_early_radar_pad_capture(stamped, snap) is True
    assert stamped["earlyRadarPadCapture"] is True


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_early_pad_blocks_when_off_low_too_extended(mock_settings):
    mock_settings.return_value = Settings()
    alert = {
        "tier": "BUILDING",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 48.0,
        "offLowMovePct": 45.0,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "volumeAwaken": True,
        "explosionScore": 60.0,
    }
    assert early_radar_pad_capture_active(alert, _snap()) is False


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_early_pad_stamps_on_watch_flat_vertical_at_trough(mock_settings):
    mock_settings.return_value = Settings()
    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 33.0,
        "offLowMovePct": 0.0,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "volumeAwaken": True,
        "explosionScore": 8.0,
        "peakMovePct": 4.0,
    }
    snap = _snap()
    assert early_radar_pad_capture_active(alert, snap) is True
    stamped = dict(alert)
    assert stamp_early_radar_pad_capture(stamped, snap) is True
    assert stamped["earlyRadarPadCapture"] is True


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_early_pad_ftv_policy_authorizes_low_watch_score(mock_settings):
    mock_settings.return_value = Settings()
    evidence = {
        "mode": "explosion",
        "tier": "WATCH",
        "explosionScore": 8.0,
        "tqs": 55.0,
        "earlyRadarPadCapture": True,
        "offLowMovePct": 0.0,
        "velocity3s": 0.2,
        "velocity9s": 0.1,
        "localBaseMovePct": 4.0,
        "flatThenVertical": False,
        "activeBreakout": False,
        "orderflowPositive": True,
        "volumeAwaken": True,
        "timingAssessment": "GOOD",
        "timingAction": "allow",
    }
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
        **ftv_policy_settings(Settings()),
    )
    assert decision.allowed is True
    assert decision.mode == "EARLY_RADAR_PAD_FTV"


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_early_pad_entry_readiness_authorizes_bearish_chart_call(mock_settings):
    mock_settings.return_value = Settings()
    alert = {
        "tier": "BUILDING",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 33.0,
        "offLowMovePct": 2.0,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "volumeAwaken": True,
        "explosionScore": 55.0,
        "peakMovePct": 8.0,
    }
    snap = _snap(direction="BEARISH")
    ok, reason = early_radar_pad_entry_readiness(snap=snap, alert=alert)
    assert ok is True
    assert reason == EARLY_RADAR_PAD_READY


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_early_pad_ftv_policy_authorizes_max_capital(mock_settings):
    mock_settings.return_value = Settings()
    evidence = {
        "mode": "explosion",
        "tier": "BUILDING",
        "explosionScore": 78.0,
        "tqs": 72.0,
        "earlyRadarPadCapture": True,
        "velocity3s": 0.4,
        "velocity9s": 0.6,
        "localBaseMovePct": 8.0,
        "flatThenVertical": True,
        "activeBreakout": True,
        "orderflowPositive": True,
        "volumeAwaken": True,
        "timingAssessment": "GOOD",
        "timingAction": "allow",
    }
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
    )
    assert decision.allowed is True
    assert decision.mode == "EARLY_RADAR_PAD_FTV"
    assert decision.max_capital_pct == pytest.approx(0.90)


@patch("app.engines.trade_selector.get_settings")
@patch("app.engines.early_radar_pad_capture.get_settings")
def test_explosion_selector_allows_early_pad_despite_bearish_chart(
    mock_early_settings,
    mock_selector_settings,
):
    settings = Settings()
    mock_early_settings.return_value = settings
    mock_selector_settings.return_value = settings
    from app.engines.auto_trader import AutoTraderState
    from app.engines.trade_selector import _explosion_candidates

    alert = {
        "tradeable": False,
        "tier": "BUILDING",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 33.0,
        "offLowMovePct": 0.0,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "volumeAwaken": True,
        "explosionScore": 58.0,
        "peakMovePct": 10.0,
        "velocity3s": 0.5,
        "velocity9s": 0.4,
        "earlyRadarPadCapture": True,
        "ictEarlyRadarPadCapture": True,
        "ictBaseReadinessReason": EARLY_RADAR_PAD_READY,
    }
    snap = _snap(direction="BEARISH")
    snap.explosionAlerts = [alert]
    snap.tradeQualityScore = 55.0
    state = AutoTraderState()
    with patch(
        "app.engines.top_moment_gate.explosion_alert_is_top_moment",
        return_value=True,
    ):
        candidates = _explosion_candidates("NIFTY", snap, state, settings)
    assert len(candidates) == 1
    assert candidates[0].strike == 24150.0


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.early_radar_pad_capture.get_settings")
def test_check_explosion_entry_allows_watch_base_armed_early_pad(
    mock_early_settings,
    mock_entry_settings,
):
    settings = Settings()
    mock_early_settings.return_value = settings
    mock_entry_settings.return_value = settings
    from app.engines.explosion_detector import ExplosionEvent
    from app.engines.explosion_profit import check_explosion_entry
    from app.models.schemas import Breadth, Side, SuggestedTrade, StrategyType

    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 33.0,
        "offLowMovePct": 0.0,
        "ictBaseArmed": True,
        "earlyRadarPadCapture": True,
        "ictEarlyRadarPadCapture": True,
        "ictBaseReadinessReason": EARLY_RADAR_PAD_READY,
        "explosionScore": 8.0,
        "peakMovePct": 4.0,
        "velocity3s": 0.2,
        "velocity9s": 0.1,
    }
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        premium=33.0,
        velocity_3s=0.2,
        velocity_9s=0.1,
        velocity_15s=0.0,
        volume_surge=1.0,
        explosion_score=8.0,
        tier="WATCH",
        reason="ict_base_armed",
        daily_move_pct=4.0,
        peak_move_pct=4.0,
    )
    trade = SuggestedTrade(
        id="x",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        lastPremium=33.0,
        tqs=55.0,
        strategyType=StrategyType.EXPLOSIVE,
        confidence=8.0,
    )
    snap = _snap(direction="BEARISH")
    ok, reason = check_explosion_entry(
        event,
        trade,
        Breadth(score=50, bias="BEARISH", aligned=False),
        False,
        chart=snap.spotChart,
        snap=snap,
        alert=alert,
    )
    assert ok is True
    assert reason in {"early_radar_pad_ftv_confirmed", "first_lift_local_base_confirmed"}


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_watch_local_base_pad_active_without_flat_vertical(mock_settings):
    """WATCH at session trough with low score + velocity — no ictFlatThenVertical needed."""
    mock_settings.return_value = Settings()
    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 77600.0,
        "premium": 240.0,
        "offLowMovePct": 3.0,
        "localBaseMovePct": 5.0,
        "explosionScore": 12.8,
        "velocity3s": 0.15,
        "velocity9s": 0.08,
        "volumeAwaken": True,
        "peakMovePct": 8.0,
    }
    snap = _snap(spot=77600.0, atm=77600.0, direction="BEARISH")
    assert watch_local_base_pad_lift_signal(alert) is True
    assert watch_local_base_pad_structure(alert) is True
    assert early_radar_pad_capture_active(alert, snap) is True
    stamped = dict(alert)
    assert stamp_early_radar_pad_capture(stamped, snap) is True
    assert stamped["earlyRadarPadCapture"] is True


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_watch_local_base_pad_blocks_when_score_too_hot(mock_settings):
    mock_settings.return_value = Settings()
    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 77600.0,
        "premium": 280.0,
        "offLowMovePct": 5.0,
        "localBaseMovePct": 12.0,
        "explosionScore": 55.0,
        "velocity3s": 0.2,
        "velocity9s": 0.1,
        "volumeAwaken": True,
    }
    assert watch_local_base_pad_lift_signal(alert) is False


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_watch_local_base_first_lift_readiness_before_structure_gate(mock_settings):
    """first_lift_entry_readiness authorizes WATCH pad before structure_not_confirmed."""
    mock_settings.return_value = Settings()
    from app.engines.ict_breakout_monitor import first_lift_entry_readiness

    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 77600.0,
        "premium": 240.0,
        "offLowMovePct": 2.0,
        "localBaseMovePct": 4.0,
        "explosionScore": 12.8,
        "velocity3s": 0.12,
        "velocity9s": 0.06,
        "volumeAwaken": True,
        "peakMovePct": 6.0,
        "ictBaseArmed": True,
    }
    snap = _snap(spot=77600.0, atm=77600.0, direction="BEARISH")
    ok, reason = first_lift_entry_readiness(snap=snap, alert=alert)
    assert ok is True
    assert reason == EARLY_RADAR_PAD_READY
    assert alert.get("earlyRadarPadCapture") is True


@patch("app.engines.trade_selector.get_settings")
@patch("app.engines.early_radar_pad_capture.get_settings")
def test_explosion_selector_allows_watch_local_base_low_score(
    mock_early_settings,
    mock_selector_settings,
):
    settings = Settings()
    mock_early_settings.return_value = settings
    mock_selector_settings.return_value = settings
    from app.engines.auto_trader import AutoTraderState
    from app.engines.trade_selector import _explosion_candidates

    alert = {
        "tradeable": True,
        "tier": "WATCH",
        "side": "CALL",
        "strike": 77600.0,
        "premium": 240.0,
        "offLowMovePct": 2.0,
        "localBaseMovePct": 4.0,
        "explosionScore": 12.8,
        "peakMovePct": 6.0,
        "velocity3s": 0.12,
        "velocity9s": 0.06,
        "volumeAwaken": True,
        "ictBaseArmed": True,
        "earlyRadarPadCapture": True,
        "ictEarlyRadarPadCapture": True,
        "ictBaseReadinessReason": EARLY_RADAR_PAD_READY,
    }
    snap = _snap(spot=77600.0, atm=77600.0, direction="BEARISH")
    snap.explosionAlerts = [alert]
    snap.tradeQualityScore = 55.0
    state = AutoTraderState()
    candidates = _explosion_candidates("SENSEX", snap, state, settings)
    assert len(candidates) == 1
    assert candidates[0].strike == 77600.0
    assert candidates[0].tier == "WATCH"


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_cold_trough_pad_v3_zero_base_armed(mock_settings):
    """Aug28 NIFTY 24150 CE 15:05 — WATCH v3=0 at armed session trough."""
    mock_settings.return_value = Settings()
    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 107.35,
        "offLowMovePct": 5.0,
        "localBaseMovePct": 5.0,
        "ictBaseArmed": True,
        "ictArmedBaseSamples": 8,
        "explosionScore": 20.1,
        "velocity3s": 0.0,
        "velocity9s": 0.0,
        "peakMovePct": 5.0,
    }
    assert cold_trough_pad_lift_signal(alert) is True
    assert watch_local_base_pad_structure(alert) is True
    snap = _snap()
    assert early_radar_pad_capture_active(alert, snap) is True
    stamped = dict(alert)
    assert stamp_early_radar_pad_capture(stamped, snap) is True
    assert stamped.get("coldTroughPad") is True


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_cold_trough_pad_blocks_when_local_move_extended(mock_settings):
    mock_settings.return_value = Settings()
    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 115.0,
        "offLowMovePct": 12.5,
        "localBaseMovePct": 12.5,
        "ictBaseArmed": True,
        "explosionScore": 20.0,
        "velocity3s": 0.0,
    }
    assert cold_trough_pad_lift_signal(alert) is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_tier_promotion_pad_chase_blocks_elite_without_stamp(mock_settings):
    from app.engines.explosion_detector import ExplosionEvent
    from app.engines.explosion_entry_guards import tier_promotion_pad_chase_blocked

    mock_settings.return_value = Settings()
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24250.0,
        premium=104.55,
        velocity_3s=0.87,
        velocity_9s=0.5,
        velocity_15s=0.0,
        volume_surge=1.0,
        explosion_score=100.0,
        tier="ELITE",
        reason="test",
        daily_move_pct=8.4,
        peak_move_pct=8.4,
    )
    ict = MagicMock(base_relative_move_pct=8.4, base_armed=True, active=True)
    blocked, reason = tier_promotion_pad_chase_blocked(event, ict=ict, alert={})
    assert blocked is True
    assert "tier_promotion_pad_chase_blocked" in reason


@patch("app.engines.elite_never_block.elite_never_block_active", return_value=True)
@patch("app.engines.explosion_entry_guards.get_settings")
def test_tier_promotion_pad_chase_blocks_elite_even_when_must_take(
    mock_settings, _must_take,
):
    from app.engines.explosion_detector import ExplosionEvent
    from app.engines.explosion_entry_guards import tier_promotion_pad_chase_blocked

    mock_settings.return_value = Settings()
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24250.0,
        premium=104.55,
        velocity_3s=0.87,
        velocity_9s=0.5,
        velocity_15s=0.0,
        volume_surge=1.0,
        explosion_score=100.0,
        tier="ELITE",
        reason="test",
        daily_move_pct=8.4,
        peak_move_pct=8.4,
    )
    ict = MagicMock(base_relative_move_pct=8.4, base_armed=True, active=True)
    blocked, reason = tier_promotion_pad_chase_blocked(event, ict=ict, alert={})
    assert blocked is True
    assert "tier_promotion_pad_chase_blocked" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_tier_promotion_pad_chase_allows_pad_stamp(mock_settings):
    from app.engines.explosion_detector import ExplosionEvent
    from app.engines.explosion_entry_guards import tier_promotion_pad_chase_blocked

    mock_settings.return_value = Settings()
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24250.0,
        premium=104.55,
        velocity_3s=0.87,
        velocity_9s=0.5,
        velocity_15s=0.0,
        volume_surge=1.0,
        explosion_score=100.0,
        tier="ELITE",
        reason="test",
        daily_move_pct=8.4,
        peak_move_pct=8.4,
    )
    alert = {"earlyRadarPadCapture": True, "ictEarlyRadarPadCapture": True}
    blocked, _ = tier_promotion_pad_chase_blocked(event, ict=None, alert=alert)
    assert blocked is False
