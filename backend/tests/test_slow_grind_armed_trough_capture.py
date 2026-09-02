"""Slow-grind armed-trough capture — Aug25 NIFTY 24150 CE at session pad."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.ict_breakout_monitor import (
    SLOW_GRIND_ARMED_TROUGH_READY,
    _slow_grind_armed_trough_readiness,
    _slow_grind_sudden_lift_readiness,
    first_lift_entry_readiness,
)
from app.engines.trade_ranking import ftv_authorization_policy, ftv_policy_settings, rank_trade_evidence
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


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_slow_grind_armed_trough_authorizes_aug25_24150_watch_trough(mock_settings):
    """WATCH score 8 at ₹33 armed base — before flat-quality coil confirms."""
    mock_settings.return_value = Settings()
    snap = _snap()
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
        "strike": 24150.0,
        "premium": 33.0,
        "offLowMovePct": 0.0,
        "ictBaseArmed": True,
        "ictVRipReady": True,
        "ictBaseRelativeMovePct": 0.0,
        "explosionScore": 8.0,
        "velocity3s": 0.1,
    }
    ok, reason = _slow_grind_armed_trough_readiness(
        snap=snap,
        event=MagicMock(side=Side.CALL, premium=33.0, velocity_3s=0.1, strike=24150.0),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == SLOW_GRIND_ARMED_TROUGH_READY
    assert alert["slowGrindSuddenLiftReady"] is True
    assert alert["slowGrindArmedTrough"] is True


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_slow_grind_armed_trough_index_trough_without_base_armed(mock_settings):
    """Sep1-style slow V: index 5m turning at option session low before premium coil arms."""
    mock_settings.return_value = Settings(
        slow_grind_armed_trough_index_trough_enabled=True,
        slow_grind_armed_trough_index_trough_max_off_low_pct=8.0,
    )
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=24020.0,
        atmStrike=24000.0,
        spotChart=SpotChart(
            direction="BEARISH",
            rsi=48.0,
            macdBias="BEARISH",
            macdHistogram=-0.2,
            momentum5Pct=0.05,
            momentum10Pct=0.02,
            momentum15Pct=-0.10,
        ),
    )
    ict = MagicMock(
        base_armed=False,
        local_swing_base=False,
        v_rip_ready=True,
        base_relative_move_pct=2.0,
        flat_vertical_quality=12.0,
        armed_base_samples=2,
        velocity_3s=0.1,
    )
    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 24000.0,
        "premium": 120.0,
        "offLowMovePct": 3.0,
        "ictVRipReady": True,
        "ictBaseRelativeMovePct": 2.0,
        "velocity3s": 0.1,
    }
    ok, reason = _slow_grind_armed_trough_readiness(
        snap=snap,
        event=MagicMock(side=Side.CALL, premium=120.0, velocity_3s=0.1, strike=24000.0),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == SLOW_GRIND_ARMED_TROUGH_READY
    assert alert["ictIndexTroughSlowV"] is True


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_slow_grind_index_trough_allows_wider_off_low_at_defaults(mock_settings):
    """Default 15% off-low window catches lifts that start before option coil arms."""
    mock_settings.return_value = Settings()
    snap = _snap(spot=24100.0, atm=24050.0, direction="BEARISH")
    snap.spotChart.momentum5Pct = 0.012
    snap.spotChart.momentum10Pct = 0.005
    snap.spotChart.momentum15Pct = -0.25
    ict = MagicMock(
        base_armed=False,
        local_swing_base=False,
        v_rip_ready=False,
        base_relative_move_pct=10.0,
        flat_vertical_quality=18.0,
        armed_base_samples=2,
        velocity_3s=0.2,
    )
    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 24050.0,
        "premium": 95.0,
        "offLowMovePct": 12.0,
        "ictBaseRelativeMovePct": 10.0,
        "velocity3s": 0.2,
    }
    ok, reason = _slow_grind_armed_trough_readiness(
        snap=snap,
        event=MagicMock(side=Side.CALL, premium=95.0, velocity_3s=0.2, strike=24050.0),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == SLOW_GRIND_ARMED_TROUGH_READY


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_slow_grind_standard_path_still_rejects_immature_coil(mock_settings):
    mock_settings.return_value = Settings()
    snap = _snap()
    ict = MagicMock(
        base_armed=True,
        v_rip_ready=True,
        base_relative_move_pct=5.0,
        flat_vertical_quality=12.0,
        armed_base_samples=3,
        velocity_3s=0.1,
        flat_then_vertical=False,
        active=False,
    )
    alert = {
        "tier": "WATCH",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 33.0,
        "offLowMovePct": 0.0,
        "ictBaseArmed": True,
        "ictVRipReady": True,
        "ictBaseRelativeMovePct": 5.0,
        "velocity3s": 0.1,
    }
    mock_settings.return_value = Settings(slow_grind_armed_trough_enabled=False)
    ok, reason = _slow_grind_sudden_lift_readiness(
        snap=snap,
        event=MagicMock(side=Side.CALL, premium=33.0, velocity_3s=0.1, strike=24150.0),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is False
    assert reason == "slow_grind_structure_missing"


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_slow_grind_armed_trough_routes_through_first_lift_readiness(mock_settings):
    mock_settings.return_value = Settings()
    snap = _snap(direction="BEARISH")
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
        "strike": 24150.0,
        "premium": 33.0,
        "offLowMovePct": 0.0,
        "ictBaseArmed": True,
        "ictVRipReady": True,
        "ictBaseRelativeMovePct": 0.0,
        "velocity3s": 0.1,
    }
    ready, reason = first_lift_entry_readiness(
        snap=snap,
        event=MagicMock(side=Side.CALL, premium=33.0, velocity_3s=0.1, strike=24150.0),
        ict=ict,
        alert=alert,
    )
    assert ready is True
    assert reason == SLOW_GRIND_ARMED_TROUGH_READY


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_slow_grind_armed_trough_ftv_policy_authorizes_watch_score(mock_settings):
    mock_settings.return_value = Settings()
    evidence = {
        "mode": "explosion",
        "tier": "WATCH",
        "explosionScore": 8.0,
        "tqs": 55.0,
        "slowGrindSuddenLift": True,
        "slowGrindArmedTrough": True,
        "offLowMovePct": 0.0,
        "velocity3s": 0.1,
        "velocity9s": 0.05,
        "localBaseMovePct": 0.0,
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
    assert decision.mode == "SLOW_GRIND_FTV"
    assert decision.max_capital_pct == pytest.approx(0.90)


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_slow_grind_armed_trough_rejects_off_low_extended(mock_settings):
    mock_settings.return_value = Settings()
    snap = _snap()
    ict = MagicMock(
        base_armed=True,
        v_rip_ready=False,
        base_relative_move_pct=18.0,
        velocity_3s=0.1,
    )
    alert = {
        "side": "CALL",
        "strike": 24150.0,
        "premium": 48.0,
        "offLowMovePct": 45.0,
        "ictBaseArmed": True,
        "ictBaseRelativeMovePct": 18.0,
        "velocity3s": 0.1,
    }
    ok, reason = _slow_grind_armed_trough_readiness(
        snap=snap,
        event=MagicMock(side=Side.CALL, premium=48.0, velocity_3s=0.1, strike=24150.0),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is False
    assert reason == "slow_grind_armed_trough_not_at_trough"
