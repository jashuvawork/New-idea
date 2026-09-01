"""Index-confirmed local-base waives — Sep01 afternoon PUT / morning CALL patterns."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.index_confirmed_local_base import (
    index_confirmed_local_base,
    index_confirmed_near_miss_waive,
    index_confirmed_premium_fade_bypass,
    index_confirmed_waives_timing_block,
    stamp_index_confirmed_local_base,
)
from app.engines.pad_lane_capture import (
    local_base_premium_fade_bypass,
    pad_lane_early_near_miss_waive,
    pad_lane_ftv_waives_timing_block,
)
from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap(
    direction: str = "BULLISH",
    *,
    mom5: float = -0.02,
    mom15: float = 0.05,
    breadth: str = "NEUTRAL",
) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 1, 13, 45, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24_000,
        breadth=Breadth(bias=breadth),
        spotChart=SpotChart(
            direction=direction,
            momentum5Pct=mom5,
            momentum10Pct=mom5 * 0.8,
            momentum15Pct=mom15,
        ),
    )


def _put_alert(**extra) -> dict:
    base = {
        "side": "PUT",
        "strike": 23950,
        "tier": "ELITE",
        "explosionScore": 72,
        "localBaseMovePct": 12.0,
        "ictBaseRelativeMovePct": 12.0,
        "offLowMovePct": 8.0,
        "ictBaseArmed": True,
        "ictArmedBaseLaunch": True,
        "ictFirstLift": True,
        "tradeable": True,
    }
    base.update(extra)
    return base


@pytest.fixture
def mock_settings(monkeypatch):
    from types import SimpleNamespace

    settings = SimpleNamespace(
        index_confirmed_local_base_enabled=True,
        index_confirmed_local_base_max_off_low_pct=22.0,
        index_confirmed_local_base_min_explosion_score_floor=5.0,
        index_confirmed_local_base_waives_near_miss=True,
        index_confirmed_local_base_waives_timing=True,
        index_confirmed_local_base_premium_fade=True,
        index_confirmed_local_base_armed_pad_bypass=True,
        index_trough_chart_bypass_enabled=True,
        index_trough_chart_bypass_min_mom5_pct=0.008,
        index_trough_chart_bypass_min_mom_shift_pct=0.02,
        index_trough_chart_bypass_max_adverse_mom15_pct=-0.35,
        pad_lane_early_near_miss_waive_enabled=True,
        pad_lane_ftv_waives_timing_block_enabled=True,
        shallow_otm_local_base_min_move_pct=2.0,
        shallow_otm_local_base_max_move_pct=25.0,
    )
    monkeypatch.setattr(
        "app.engines.index_confirmed_local_base.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "app.engines.pad_lane_capture.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "app.engines.spot_direction.get_settings",
        lambda: settings,
    )
    return settings


def test_index_peak_put_turn_detected(mock_settings):
    snap = _snap("BULLISH", mom5=-0.015, mom15=0.08)
    alert = _put_alert()
    assert index_confirmed_local_base(Side.PUT, snap, alert) is True


def test_stamp_sets_peak_flags_for_put(mock_settings):
    snap = _snap("BULLISH", mom5=-0.015, mom15=0.08)
    alert = _put_alert()
    assert stamp_index_confirmed_local_base(alert, snap) is True
    assert alert["ictIndexPeakSlowV"] is True
    assert alert["ictIndexConfirmedLocalBase"] is True


def test_near_miss_waive_for_elite_at_index_peak(mock_settings):
    snap = _snap("BULLISH", mom5=-0.015, mom15=0.08)
    alert = _put_alert(explosionScore=18, tier="BUILDING")
    assert index_confirmed_near_miss_waive(alert, snap) is True
    assert pad_lane_early_near_miss_waive(alert, snap=snap) is True


def test_timing_block_waived_with_index_confirmed_evidence(mock_settings):
    evidence = {
        "tier": "ELITE",
        "indexConfirmedLocalBase": True,
        "localBaseMovePct": 12.0,
        "offLowMovePct": 8.0,
        "velocity3s": -0.4,
        "velocity9s": -0.2,
        "timingAssessment": "FAILED_LAUNCH",
    }
    assert index_confirmed_waives_timing_block(evidence) is True
    assert pad_lane_ftv_waives_timing_block(evidence) is True


def test_armed_pad_bypass_when_index_turn_lags(mock_settings):
    """Sep01 PUT 24050: bearish breadth + armed pad while mom5 shift lags mom15."""
    snap = _snap("BEARISH", mom5=-0.02, mom15=-0.133, breadth="BEARISH")
    alert = _put_alert(explosionScore=100, localBaseMovePct=20.0, offLowMovePct=20.0)
    assert index_confirmed_local_base(Side.PUT, snap, alert) is True
    assert stamp_index_confirmed_local_base(alert, snap) is True


def test_premium_fade_bypass_at_itm_put_base(mock_settings):
    snap = _snap("BULLISH", mom5=-0.015, mom15=0.08)
    alert = _put_alert(moneyness="ITM")
    assert index_confirmed_premium_fade_bypass(alert, snap) is True
    assert local_base_premium_fade_bypass(alert, snap=snap) is True
