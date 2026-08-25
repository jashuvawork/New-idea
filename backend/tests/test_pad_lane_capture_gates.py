"""Pad-lane gate waivers — allocation rank, premium fade, selector priority."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.auto_trader import AutoTraderState
from app.engines.pad_lane_capture import (
    pad_lane_early_near_miss_waive,
    pad_lane_expiry_worst_waive,
    pad_lane_ftv_waives_allocation_rank_one,
)
from app.engines.trade_ranking import ftv_authorization_policy, ftv_policy_settings
from app.engines.trade_selector import diagnose_missed_entries
from app.engines.winner_entry_guards import premium_fading_blocks_entry
from app.models.schemas import MarketPhase, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = Settings()
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_waives_allocation_rank_on_v_rip(mock_settings):
    mock_settings.return_value = _settings()
    evidence = {
        "mode": "explosion",
        "vRipReady": True,
        "offLowMovePct": 24.9,
        "localBaseMovePct": 24.9,
    }
    assert pad_lane_ftv_waives_allocation_rank_one(evidence) is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_does_not_waive_extended_chase(mock_settings):
    mock_settings.return_value = _settings()
    evidence = {
        "mode": "explosion",
        "slowGrindSuddenLift": True,
        "offLowMovePct": 45.0,
    }
    assert pad_lane_ftv_waives_allocation_rank_one(evidence) is False


@patch("app.engines.pad_lane_capture.get_settings")
def test_early_radar_pad_ftv_allows_rank_two(mock_pad):
    settings = _settings()
    mock_pad.return_value = settings
    evidence = {
        "mode": "explosion",
        "tier": "EXPLODING",
        "explosionScore": 72.0,
        "earlyRadarPadCapture": True,
        "offLowMovePct": 12.0,
        "velocity3s": 0.4,
        "velocity9s": 0.2,
        "volumeAwaken": True,
    }
    ranking = {
        "grade": "A",
        "timing": "EARLY",
        "quality": 70.0,
        "evidence": evidence,
    }
    kwargs = ftv_policy_settings(settings)
    kwargs.update(
        early_radar_pad_ftv_enabled=True,
        early_radar_pad_ftv_min_explosion_score=5.0,
        early_radar_pad_max_off_low_pct=15.0,
    )
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        atm_itm_allowed=True,
        allocation_rank=2,
        require_allocation_rank_one=True,
        **kwargs,
    )
    assert decision.allowed is True
    assert decision.mode == "EARLY_RADAR_PAD_FTV"


@patch("app.engines.winner_entry_guards.get_settings")
def test_pad_lane_premium_fade_fill_allows_shallow_dip(mock_settings):
    mock_settings.return_value = _settings()
    blocked, reason = premium_fading_blocks_entry(
        premium_momentum_3s=-0.4,
        premium_momentum_5s=-0.3,
        explosion_event=SimpleNamespace(tier="EXPLODING", daily_move_pct=12.0),
        pad_lane_bypass=True,
    )
    assert blocked is False
    assert reason == "pad_lane_shallow_fade_ok"


@patch("app.engines.winner_entry_guards.get_settings")
def test_pad_lane_premium_fade_still_blocks_deep_collapse(mock_settings):
    mock_settings.return_value = _settings()
    blocked, reason = premium_fading_blocks_entry(
        premium_momentum_3s=-2.5,
        premium_momentum_5s=-1.8,
        explosion_event=SimpleNamespace(tier="EXPLODING", daily_move_pct=12.0),
        pad_lane_bypass=True,
    )
    assert blocked is True
    assert reason == "premium_fading_at_execution"


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_expiry_worst_waive_on_v_rip(mock_settings):
    mock_settings.return_value = _settings()
    evidence = {
        "vRipReady": True,
        "offLowMovePct": 18.0,
        "localBaseMovePct": 18.0,
    }
    assert pad_lane_expiry_worst_waive(evidence) is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_early_near_miss_waive_on_stamped_v_rip(mock_settings):
    mock_settings.return_value = _settings()
    alert = {
        "tier": "BUILDING",
        "ictVRipReady": True,
        "ictBaseReadinessReason": "v_rip_session_low_ready",
    }
    assert pad_lane_early_near_miss_waive(
        alert, readiness_reason="first_lift_quality<65",
    ) is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_early_near_miss_waive_disabled(mock_settings):
    mock_settings.return_value = _settings(pad_lane_early_near_miss_waive_enabled=False)
    alert = {"ictBaseReadinessReason": "v_rip_session_low_ready"}
    assert pad_lane_early_near_miss_waive(alert) is False


def _aug25_building_v_rip_alert():
    return {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 33.0,
        "tier": "BUILDING",
        "tradeable": False,
        "explosionScore": 32.0,
        "peakMovePct": 15.0,
        "dailyMovePct": 5.0,
        "ictFirstLift": True,
        "ictVRipReady": True,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "volumeAwaken": True,
        "ictBaseRelativeMovePct": 15.0,
        "velocity3s": 0.6,
        "velocity9s": 0.5,
        "ictBaseReadinessReason": "v_rip_session_low_ready",
    }


@patch("app.engines.trade_selector.get_settings")
@patch("app.engines.ict_breakout_monitor.first_lift_entry_readiness")
def test_diagnose_skips_near_miss_when_pad_lane_waives_quality_lag(
    mock_first_lift,
    mock_selector_settings,
):
    settings = _settings()
    mock_selector_settings.return_value = settings
    mock_first_lift.return_value = (False, "first_lift_quality<65")
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=24180.0,
        atmStrike=24150.0,
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.02),
        explosionAlerts=[_aug25_building_v_rip_alert()],
    )
    notes = diagnose_missed_entries({"NIFTY": snap}, AutoTraderState())
    assert notes == []


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_ftv_waives_timing_block_on_v_rip(mock_settings):
    from app.engines.pad_lane_capture import pad_lane_ftv_waives_timing_block

    mock_settings.return_value = _settings()
    evidence = {
        "tier": "ELITE",
        "explosionScore": 50.0,
        "flatThenVertical": True,
        "activeBreakout": True,
        "localBaseMovePct": 18.0,
        "offLowMovePct": 18.0,
        "velocity3s": -0.4,
        "velocity9s": 0.1,
    }
    assert pad_lane_ftv_waives_timing_block(evidence) is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_grade_floor_applies_for_elite_ftv(mock_settings):
    from app.engines.pad_lane_capture import pad_lane_grade_floor_applies

    mock_settings.return_value = _settings()
    evidence = {
        "tier": "ELITE",
        "explosionScore": 50.0,
        "flatThenVertical": True,
        "activeBreakout": True,
        "localBaseMovePct": 18.0,
        "offLowMovePct": 18.0,
        "velocity3s": 0.3,
        "velocity9s": 0.2,
        "volumeAwaken": True,
    }
    assert pad_lane_grade_floor_applies(evidence) is True
