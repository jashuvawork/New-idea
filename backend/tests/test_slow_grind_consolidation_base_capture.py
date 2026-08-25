"""Mid-day consolidation slow-grind — Aug25 NIFTY 24250 PE base capture."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.ict_breakout_monitor import (
    SLOW_GRIND_CONSOLIDATION_BASE_READY,
    _slow_grind_consolidation_base_readiness,
    _slow_grind_sudden_lift_readiness,
)
from app.engines.top_moment_gate import explosion_alert_is_top_moment
from app.engines.trade_ranking import ftv_authorization_policy, ftv_policy_settings, rank_trade_evidence
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap(*, spot: float = 24180.0, atm: float = 24200.0):
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 8, 25, 12, 30, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=61.0,
        spot=spot,
        atmStrike=atm,
        spotChart=SpotChart(
            direction="BEARISH",
            rsi=55.0,
            macdBias="BEARISH",
            macdHistogram=-0.05,
            macd=-0.02,
            macdSignal=0.01,
            momentum5Pct=-0.01,
            momentum15Pct=-0.02,
        ),
    )


def _base_alert() -> dict:
    return {
        "tier": "BUILDING",
        "side": "PUT",
        "strike": 24250.0,
        "premium": 75.0,
        "offLowMovePct": 15.0,
        "peakMovePct": 18.0,
        "ictBaseArmed": True,
        "ictVRipReady": False,
        "ictFlatThenVertical": True,
        "ictBreakout": False,
        "ictBaseRelativeMovePct": 8.0,
        "flatVerticalQuality": 42.0,
        "ictArmedBaseSamples": 12,
        "velocity3s": 0.05,
        "velocity9s": 0.08,
        "volumeSurge": 1.1,
        "explosionScore": 26.0,
        "volumeAwaken": False,
    }


@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_consolidation_base_authorizes_aug25_24250_pe(mock_settings, _afternoon):
    mock_settings.return_value = Settings()
    snap = _snap()
    ict = MagicMock(
        base_armed=True,
        v_rip_ready=False,
        base_relative_move_pct=8.0,
        flat_vertical_quality=42.0,
        armed_base_samples=12,
        velocity_3s=0.05,
        flat_then_vertical=True,
        active=True,
    )
    alert = _base_alert()
    ok, reason = _slow_grind_consolidation_base_readiness(
        snap=snap,
        event=MagicMock(
            side=Side.PUT,
            premium=75.0,
            velocity_3s=0.05,
            strike=24250.0,
            tier="BUILDING",
            peak_move_pct=18.0,
        ),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == SLOW_GRIND_CONSOLIDATION_BASE_READY
    assert alert["slowGrindConsolidationBase"] is True
    assert alert["slowGrindSuddenLiftReady"] is True


@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_consolidation_rejects_session_trough_shape(mock_settings, _afternoon):
    mock_settings.return_value = Settings()
    snap = _snap()
    ict = MagicMock(
        base_armed=True,
        base_relative_move_pct=4.0,
        flat_vertical_quality=40.0,
        armed_base_samples=8,
        velocity_3s=0.1,
    )
    alert = {
        **_base_alert(),
        "tier": "BUILDING",
        "offLowMovePct": 1.0,
        "premium": 33.0,
        "ictVRipReady": True,
        "ictBaseRelativeMovePct": 4.0,
    }
    ok, reason = _slow_grind_consolidation_base_readiness(
        snap=snap,
        event=MagicMock(
            side=Side.CALL,
            premium=33.0,
            velocity_3s=0.1,
            strike=24150.0,
            tier="BUILDING",
            peak_move_pct=5.0,
        ),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is False
    assert reason in {
        "slow_grind_consolidation_at_session_trough",
        "slow_grind_consolidation_pad_outside_2_22",
    }


@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_consolidation_rejects_extended_peak(mock_settings, _afternoon):
    mock_settings.return_value = Settings()
    snap = _snap()
    ict = MagicMock(
        base_armed=True,
        base_relative_move_pct=12.0,
        flat_vertical_quality=55.0,
        armed_base_samples=10,
        velocity_3s=0.2,
        flat_then_vertical=True,
        active=True,
    )
    alert = {**_base_alert(), "peakMovePct": 28.0, "premium": 95.0, "explosionScore": 41.0}
    ok, reason = _slow_grind_consolidation_base_readiness(
        snap=snap,
        event=MagicMock(
            side=Side.PUT,
            premium=95.0,
            velocity_3s=0.2,
            strike=24250.0,
            tier="EXPLODING",
            peak_move_pct=28.0,
        ),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is False
    assert reason in {
        "slow_grind_consolidation_peak>24",
        "slow_grind_consolidation_tier_exploding",
    }


@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_consolidation_ftv_policy_authorizes_score_26_grade_b(mock_settings, _afternoon):
    mock_settings.return_value = Settings()
    evidence = {
        "mode": "explosion",
        "tier": "BUILDING",
        "explosionScore": 26.0,
        "tqs": 61.0,
        "slowGrindSuddenLift": True,
        "slowGrindConsolidationBase": True,
        "offLowMovePct": 15.0,
        "peakMovePct": 18.0,
        "velocity3s": 0.05,
        "velocity9s": 0.08,
        "localBaseMovePct": 8.0,
        "flatVerticalQuality": 42.0,
        "flatThenVertical": True,
        "activeBreakout": False,
        "orderflowPositive": True,
        "volumeAwaken": False,
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
    assert ranking["grade"] in {"B", "C"}
    assert decision.allowed is True
    assert decision.mode == "SLOW_GRIND_FTV"
    assert decision.max_capital_pct == pytest.approx(0.90)


@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_consolidation_routes_through_first_lift_readiness(mock_settings, _afternoon):
    mock_settings.return_value = Settings()
    snap = _snap()
    ict = MagicMock(
        base_armed=True,
        v_rip_ready=False,
        base_relative_move_pct=8.0,
        flat_vertical_quality=42.0,
        armed_base_samples=12,
        velocity_3s=0.05,
        flat_then_vertical=True,
        active=True,
    )
    alert = _base_alert()
    ready, reason = _slow_grind_sudden_lift_readiness(
        snap=snap,
        event=MagicMock(
            side=Side.PUT,
            premium=75.0,
            velocity_3s=0.05,
            strike=24250.0,
            tier="BUILDING",
            peak_move_pct=18.0,
        ),
        ict=ict,
        alert=alert,
    )
    assert ready is True
    assert reason == SLOW_GRIND_CONSOLIDATION_BASE_READY
    assert explosion_alert_is_top_moment(alert) is True


def _sensex_afternoon_snap(*, spot: float = 77226.0, atm: float = 77200.0):
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 8, 25, 14, 1, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=58.0,
        spot=spot,
        atmStrike=atm,
        spotChart=SpotChart(
            direction="BULLISH",
            rsi=52.0,
            macdBias="BULLISH",
            macdHistogram=0.04,
            macd=0.03,
            macdSignal=-0.01,
            momentum5Pct=0.02,
            momentum15Pct=0.01,
        ),
    )


def _sensex_consolidation_alert() -> dict:
    return {
        "tier": "BUILDING",
        "side": "CALL",
        "strike": 77100.0,
        "premium": 396.75,
        "offLowMovePct": 12.0,
        "peakMovePct": 14.0,
        "ictBaseArmed": True,
        "ictVRipReady": False,
        "ictFlatThenVertical": True,
        "ictBreakout": False,
        "ictBaseRelativeMovePct": 8.0,
        "flatVerticalQuality": 40.0,
        "ictArmedBaseSamples": 10,
        "velocity3s": 0.15,
        "velocity9s": 0.12,
        "volumeSurge": 1.2,
        "explosionScore": 28.0,
        "volumeAwaken": False,
    }


@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_consolidation_authorizes_sensex_itm_afternoon_base(mock_settings, _afternoon):
    """Aug25 SENSEX CALL 77100 — ₹397 ITM base before 53% vertical (L1 miss)."""
    mock_settings.return_value = Settings()
    snap = _sensex_afternoon_snap()
    ict = MagicMock(
        base_armed=True,
        v_rip_ready=False,
        base_relative_move_pct=8.0,
        flat_vertical_quality=40.0,
        armed_base_samples=10,
        velocity_3s=0.15,
        flat_then_vertical=True,
        active=True,
    )
    alert = _sensex_consolidation_alert()
    ok, reason = _slow_grind_consolidation_base_readiness(
        snap=snap,
        event=MagicMock(
            side=Side.CALL,
            premium=396.75,
            velocity_3s=0.15,
            strike=77100.0,
            tier="BUILDING",
            peak_move_pct=14.0,
        ),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == SLOW_GRIND_CONSOLIDATION_BASE_READY


@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_consolidation_rejects_premium_above_800(mock_settings, _afternoon):
    mock_settings.return_value = Settings()
    snap = _sensex_afternoon_snap()
    ict = MagicMock(
        base_armed=True,
        base_relative_move_pct=8.0,
        flat_vertical_quality=40.0,
        armed_base_samples=10,
        velocity_3s=0.15,
        flat_then_vertical=True,
        active=True,
    )
    alert = {**_sensex_consolidation_alert(), "premium": 850.0}
    ok, reason = _slow_grind_consolidation_base_readiness(
        snap=snap,
        event=MagicMock(
            side=Side.CALL,
            premium=850.0,
            velocity_3s=0.15,
            strike=77100.0,
            tier="BUILDING",
            peak_move_pct=14.0,
        ),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is False
    assert reason == "slow_grind_consolidation_premium_above_800"


@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_sudden_lift_routes_sensex_itm_through_consolidation(mock_settings, _afternoon):
    """Live first_lift path delegates to consolidation before the ₹220 sudden-lift cap."""
    mock_settings.return_value = Settings()
    snap = _sensex_afternoon_snap()
    ict = MagicMock(
        base_armed=True,
        base_relative_move_pct=8.0,
        flat_vertical_quality=40.0,
        armed_base_samples=10,
        velocity_3s=0.15,
        flat_then_vertical=True,
        active=True,
    )
    alert = _sensex_consolidation_alert()
    ok, reason = _slow_grind_sudden_lift_readiness(
        snap=snap,
        event=MagicMock(
            side=Side.CALL,
            premium=396.75,
            velocity_3s=0.15,
            strike=77100.0,
            tier="BUILDING",
            peak_move_pct=14.0,
        ),
        ict=ict,
        alert=alert,
    )
    assert ok is True
    assert reason == SLOW_GRIND_CONSOLIDATION_BASE_READY


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_armed_trough_still_caps_premium_at_220(mock_settings):
    """Armed-trough pad lane stays on ₹220 — consolidation widening is isolated."""
    from app.engines.ict_breakout_monitor import _slow_grind_armed_trough_readiness

    mock_settings.return_value = Settings()
    snap = _sensex_afternoon_snap()
    ict = MagicMock(
        base_armed=True,
        v_rip_ready=True,
        base_relative_move_pct=0.0,
        flat_vertical_quality=12.0,
        armed_base_samples=3,
        velocity_3s=0.1,
    )
    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 77100.0,
        "premium": 396.75,
        "offLowMovePct": 0.5,
        "ictBaseArmed": True,
        "ictVRipReady": True,
        "ictBaseRelativeMovePct": 0.0,
        "explosionScore": 8.0,
        "velocity3s": 0.1,
    }
    ok, reason = _slow_grind_armed_trough_readiness(
        snap=snap,
        event=MagicMock(side=Side.CALL, premium=396.75, velocity_3s=0.1, strike=77100.0),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is False
    assert reason == "slow_grind_armed_trough_premium_above_220"
