"""FTV direct-trade link — pad-lane BUILDING at base must execute, not chase."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.elite_never_block import elite_never_block_active
from app.engines.pad_lane_capture import (
    ftv_direct_trade_active,
    pad_lane_turnaround_chart_bypass,
    stamp_ftv_direct_trade_on_alert,
)
from app.models.schemas import Breadth, MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

# Aug26 SENSEX 77700 PE chart anchors
SESSION_LOW = 95.0
BASE_PREMIUM = 120.0
POST_RIP_PREMIUM = 200.0
STRIKE = 77700.0


def _settings(**kwargs):
    s = MagicMock()
    s.ftv_direct_trade_enabled = True
    s.ftv_direct_trade_max_off_low_pct = 35.0
    s.ftv_direct_trade_max_local_move_pct = 45.0
    s.ftv_direct_trade_max_peak_move_pct = 50.0
    s.ftv_direct_trade_min_off_low_pct = 2.0
    s.ftv_direct_trade_require_atm_itm = True
    s.ftv_direct_trade_selector_rank_bonus = 55.0
    s.explosion_top_must_take_enabled = True
    s.explosion_top_must_take_tiers_csv = "ELITE,EXPLODING"
    s.explosion_elite_never_block_enabled = True
    s.entry_timing_elite_bypass_requires_hot = True
    s.min_option_premium_inr = 18.0
    s.pad_lane_chart_bypass_enabled = True
    s.pad_lane_chart_bypass_min_velocity_3s = 0.5
    s.pad_lane_chart_bypass_volume_awaken_min_velocity_3s = 0.2
    s.pad_lane_chart_bypass_max_off_low_pct = 30.0
    s.pad_lane_chart_bypass_max_peak_move_pct = 38.0
    s.pad_lane_chart_bypass_min_premium_velocity_9s = -0.3
    s.pad_lane_chart_bypass_max_adverse_index_mom5_pct = 0.25
    s.moneyness_atm_tolerance_points = 50.0
    s.sensex_strike_step = 100.0
    s.nifty_strike_step = 50.0
    s.banknifty_strike_step = 100.0
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _sensex_snap(*, spot: float = 77750.0):
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 8, 26, 11, 50, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=spot,
        atmStrike=77700.0,
        regime=Regime.CHOP,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.08,
            macdBias="BULLISH",
        ),
    )


def _alert(
    *,
    premium: float,
    off_low: float,
    local_move: float = 0.0,
    peak: float = 0.0,
    tier: str = "BUILDING",
    readiness: str = "v_rip_session_low_ready",
    v3: float = 0.1,
    v9: float = -0.1,
):
    return {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": STRIKE,
        "premium": premium,
        "tier": tier,
        "explosionScore": 72.0,
        "offLowMovePct": off_low,
        "localBaseMovePct": local_move or off_low,
        "ictBaseRelativeMovePct": local_move or off_low,
        "peakMovePct": peak,
        "velocity3s": v3,
        "velocity9s": v9,
        "ictBaseReadinessReason": readiness,
        "ictVRipReady": True,
        "vRipReady": True,
        "tradeable": True,
    }


@patch("app.engines.pad_lane_capture.get_settings")
def test_ftv_direct_active_at_77700_pe_base(mock_gs):
    """EARLY at ~₹120 off session low — must link to trade."""
    mock_gs.return_value = _settings()
    off_low = (BASE_PREMIUM - SESSION_LOW) / SESSION_LOW * 100.0  # ~26%
    alert = _alert(premium=BASE_PREMIUM, off_low=off_low, peak=off_low)
    snap = _sensex_snap()

    assert ftv_direct_trade_active(alert=alert, snap=snap) is True
    assert elite_never_block_active(alert=alert, snap=snap, tier="BUILDING") is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_ftv_direct_blocks_post_rip_chase_at_200(mock_gs):
    """After ₹120→₹200 vertical — must NOT authorize chase."""
    mock_gs.return_value = _settings()
    off_low = (POST_RIP_PREMIUM - SESSION_LOW) / SESSION_LOW * 100.0  # ~110%
    peak = off_low
    alert = _alert(premium=POST_RIP_PREMIUM, off_low=off_low, peak=peak, v3=2.5, v9=1.8)

    assert ftv_direct_trade_active(alert=alert, snap=_sensex_snap()) is False
    assert elite_never_block_active(alert=alert, snap=_sensex_snap(), tier="BUILDING") is False


@patch("app.engines.pad_lane_capture.get_settings")
def test_ftv_direct_blocks_mid_rip_coil(mock_gs):
    mock_gs.return_value = _settings()
    alert = _alert(premium=140.0, off_low=30.0, peak=55.0)
    alert["midRipCoil"] = True

    assert ftv_direct_trade_active(alert=alert, snap=_sensex_snap()) is False


@patch("app.engines.pad_lane_capture.get_settings")
def test_ftv_direct_armed_trough_at_flat_base(mock_gs):
    """Armed trough at flat ₹120 — off-low may be near zero."""
    mock_gs.return_value = _settings()
    alert = _alert(
        premium=120.0,
        off_low=0.5,
        local_move=0.5,
        readiness="slow_grind_armed_trough_ready",
        v3=-0.2,
        v9=-0.1,
    )
    alert.pop("ictVRipReady", None)
    alert.pop("vRipReady", None)
    alert["slowGrindArmedTroughReady"] = True

    assert ftv_direct_trade_active(alert=alert, snap=_sensex_snap()) is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_ftv_direct_chart_bypass_cold_velocity(mock_gs):
    """Counter-trend chart with cold velocity at trough still bypasses."""
    mock_gs.return_value = _settings()
    off_low = (BASE_PREMIUM - SESSION_LOW) / SESSION_LOW * 100.0
    alert = _alert(premium=BASE_PREMIUM, off_low=off_low, v3=0.1, v9=-0.1)
    snap = _sensex_snap()
    snap.spotChart = SpotChart(
        direction="BULLISH",
        momentum5Pct=0.12,
        macdBias="BULLISH",
    )

    assert pad_lane_turnaround_chart_bypass(
        Side.PUT,
        snap,
        alert=alert,
        readiness_reason="v_rip_session_low_ready",
    )


@patch("app.engines.pad_lane_capture.get_settings")
def test_stamp_ftv_direct_on_alert(mock_gs):
    mock_gs.return_value = _settings()
    off_low = (BASE_PREMIUM - SESSION_LOW) / SESSION_LOW * 100.0
    alert = _alert(premium=BASE_PREMIUM, off_low=off_low)

    assert stamp_ftv_direct_trade_on_alert(
        alert,
        snap=_sensex_snap(),
        readiness_reason="v_rip_session_low_ready",
    )
    assert alert.get("ictFtvDirectTrade") is True
    assert alert.get("ftvDirectTrade") is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_ftv_direct_rejects_otm(mock_gs):
    mock_gs.return_value = _settings()
    off_low = (BASE_PREMIUM - SESSION_LOW) / SESSION_LOW * 100.0
    alert = _alert(premium=BASE_PREMIUM, off_low=off_low)
    alert["strike"] = 77000.0  # deep OTM put when spot ~77750

    assert ftv_direct_trade_active(alert=alert, snap=_sensex_snap()) is False
