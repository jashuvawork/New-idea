"""Tests for extended pre-lift pad capture lanes."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.pad_lane_capture import (
    INDEX_LED_OPTION_LAG_READY,
    MICRO_PULLBACK_RETEST_READY,
    PREMIUM_FVG_PAD_READY,
    SQUEEZE_RELEASE_READY,
    STEALTH_CVD_COIL_READY,
    extended_pad_lane_readiness,
    index_led_option_lag_readiness,
    micro_pullback_retest_readiness,
    pad_lane_cold_velocity_ok,
    premium_fvg_pad_readiness,
    squeeze_release_readiness,
    stealth_cvd_coil_readiness,
)
from app.engines.ict_breakout_monitor import first_lift_entry_readiness
from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap(spot: float = 24200.0) -> SymbolSnapshot:
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=spot,
        atmStrike=spot,
        spotChart=SpotChart(
            direction="BEARISH",
            rsi=42.0,
            macdBias="BEARISH",
            macdHistogram=-0.1,
            macd=-0.05,
            macdSignal=0.02,
            momentum5Pct=-0.02,
            momentum15Pct=0.01,
        ),
    )
    snap.chartAnalysis = type(
        "CA",
        (),
        {"squeeze": {"bars_on": 5, "bars_since_fired": 1, "direction": "BEARISH"}},
    )()
    return snap


def _ict(**kwargs):
    base = dict(
        flat_then_vertical=True,
        active=True,
        base_armed=True,
        base_relative_move_pct=10.0,
        flat_vertical_quality=58.0,
        velocity_3s=0.2,
    )
    base.update(kwargs)
    return MagicMock(**base)


def _alert(**kwargs):
    base = {
        "side": "PUT",
        "strike": 24200.0,
        "premium": 22.0,
        "tier": "BUILDING",
        "ictBaseArmed": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictBaseRelativeMovePct": 10.0,
        "velocity3s": 0.2,
    }
    base.update(kwargs)
    return base


@patch("app.engines.pad_lane_capture.get_settings")
def test_squeeze_release_authorizes_compressed_coil(mock_settings):
    mock_settings.return_value = Settings()
    alert = _alert()
    ok, reason = squeeze_release_readiness(
        snap=_snap(),
        event=MagicMock(side=Side.PUT, premium=22.0, velocity_3s=0.2, strike=24200.0),
        ict=_ict(),
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == SQUEEZE_RELEASE_READY
    assert alert["squeezeReleaseReady"] is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_index_led_option_lag_authorizes_flat_option(mock_settings):
    mock_settings.return_value = Settings()
    alert = _alert(
        indexHelpersConfirm=True,
        indexSpotMove3s=-0.05,
        velocity3s=0.4,
    )
    ok, reason = index_led_option_lag_readiness(
        snap=_snap(),
        event=MagicMock(side=Side.PUT, premium=22.0, velocity_3s=0.4, strike=24200.0),
        ict=_ict(velocity_3s=0.4),
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == INDEX_LED_OPTION_LAG_READY
    assert alert["indexLedOptionLagReady"] is True


@patch("app.engines.pad_lane_capture.get_settings")
@patch("app.engines.advanced_indicators.option_cvd_acceleration_confirms_buying")
@patch("app.engines.advanced_indicators.option_cvd_confirms_buying")
def test_stealth_cvd_coil_authorizes_flat_cvd(mock_cvd, mock_accel, mock_settings):
    mock_settings.return_value = Settings()
    mock_cvd.return_value = True
    mock_accel.return_value = True
    alert = _alert(velocity3s=0.1)
    ok, reason = stealth_cvd_coil_readiness(
        snap=_snap(),
        event=MagicMock(side=Side.PUT, premium=22.0, velocity_3s=0.1, strike=24200.0),
        ict=_ict(velocity_3s=0.1, volume_awakening=False, volume_surge=1.1),
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == STEALTH_CVD_COIL_READY
    assert alert["stealthCvdCoilReady"] is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_micro_pullback_retest_authorizes_shallow_dip(mock_settings):
    mock_settings.return_value = Settings()
    alert = _alert(
        velocity3s=-0.4,
        velocity9s=0.1,
        ictFirstLift=True,
        volumeAwaken=True,
        ictBaseRelativeMovePct=12.0,
    )
    ok, reason = micro_pullback_retest_readiness(
        snap=_snap(),
        event=MagicMock(side=Side.PUT, premium=22.0, velocity_3s=-0.4, strike=24200.0),
        ict=_ict(
            velocity_3s=-0.4,
            velocity_9s=0.1,
            base_relative_move_pct=12.0,
            first_lift=True,
            volume_awakening=True,
        ),
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == MICRO_PULLBACK_RETEST_READY
    assert alert["microPullbackRetestReady"] is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_premium_fvg_pad_authorizes_at_base(mock_settings):
    mock_settings.return_value = Settings()
    alert = _alert(ictPremiumFvg=True, velocity3s=1.5)
    ok, reason = premium_fvg_pad_readiness(
        snap=_snap(),
        event=MagicMock(side=Side.PUT, premium=22.0, velocity_3s=1.5, strike=24200.0),
        ict=_ict(premium_fvg=True, velocity_3s=1.5),
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == PREMIUM_FVG_PAD_READY
    assert alert["premiumFvgPadReady"] is True


@pytest.mark.parametrize(
    "flag,mode",
    [
        ("squeezeRelease", "SQUEEZE_RELEASE_FTV"),
        ("indexLedOptionLag", "INDEX_LED_OPTION_LAG_FTV"),
        ("stealthCvdCoil", "STEALTH_CVD_COIL_FTV"),
        ("microPullbackRetest", "MICRO_PULLBACK_RETEST_FTV"),
        ("premiumFvgPad", "PREMIUM_FVG_PAD_FTV"),
    ],
)
def test_pad_lane_ftv_policies_authorize_building(flag, mode):
    evidence = {
        "mode": "explosion",
        "tier": "BUILDING",
        "explosionScore": 88.0,
        "tqs": 68.0,
        "velocity3s": 0.2,
        "velocity9s": 0.1,
        "localBaseMovePct": 10.0,
        flag: True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "flatVerticalQuality": 58.0,
        "orderflowPositive": True,
        "volumeAwaken": True,
        "timingAssessment": "GOOD",
    }
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] == "A"
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
    )
    assert decision.allowed is True
    assert decision.mode == mode
    assert decision.max_capital_pct == 0.90


@pytest.mark.parametrize(
    "flag,v3,v9,expected",
    [
        ("slowGrindSuddenLift", -0.3, 0.1, True),
        ("slowGrindSuddenLift", -1.0, 0.1, False),
        ("squeezeRelease", -0.4, 0.0, True),
        ("indexLedOptionLag", -0.2, 0.0, True),
        ("stealthCvdCoil", -0.3, 0.0, True),
        ("stealthCvdCoil", -0.8, 0.0, False),
        ("microPullbackRetest", -0.8, 0.0, True),
        ("microPullbackRetest", -0.8, -0.8, False),
        ("premiumFvgPad", -0.5, 0.0, True),
        ("fastBullishLocalBase", -0.1, 0.0, False),
    ],
)
def test_pad_lane_cold_velocity_ok(flag, v3, v9, expected):
    evidence = {flag: True}
    assert pad_lane_cold_velocity_ok(evidence, v3, v9) is expected


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_extended_pad_lane_wins_first_lift_chain(mock_settings):
    """Squeeze release routes through first_lift_entry_readiness before slow-grind."""
    mock_settings.return_value = Settings()
    alert = _alert()
    snap = _snap()
    ict = _ict()
    ready, reason = first_lift_entry_readiness(
        snap=snap,
        event=MagicMock(side=Side.PUT, premium=22.0, velocity_3s=0.2, strike=24200.0),
        ict=ict,
        alert=alert,
    )
    assert ready is True
    assert reason == SQUEEZE_RELEASE_READY

@patch("app.engines.pad_lane_capture.get_settings")
def test_extended_pad_lane_readiness_orchestrator(mock_settings):
    mock_settings.return_value = Settings()
    alert = _alert()
    ok, reason = extended_pad_lane_readiness(
        snap=_snap(),
        event=MagicMock(side=Side.PUT, premium=22.0, velocity_3s=0.2, strike=24200.0),
        ict=_ict(),
        alert=alert,
    )
    assert ok is True
    assert reason == SQUEEZE_RELEASE_READY
