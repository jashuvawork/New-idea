"""Pad-lane gate waivers — allocation rank, premium fade, selector priority."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.engines.pad_lane_capture import (
    pad_lane_expiry_worst_waive,
    pad_lane_ftv_waives_allocation_rank_one,
)
from app.engines.trade_ranking import ftv_authorization_policy, ftv_policy_settings
from app.engines.winner_entry_guards import premium_fading_blocks_entry
from app.config import Settings


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
