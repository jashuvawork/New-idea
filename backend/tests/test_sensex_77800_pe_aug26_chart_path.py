"""Aug26 SENSEX 77800 PE — trough → V → post-peak slow chop must not re-enter.

Chart (1m, ~11:49 IST):
  • Session trough ~90–100 (armed trough / FTV base)
  • V-rip to ~190
  • Post-peak slow consolidation ~140–160, RSI ~44, MACD bearish

Product rule: enter at the trough or on the V; do not treat mid-rip chop after
a completed rip as a fresh FTV/V base.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_detector import (
    _local_base_hist,
    _open_key,
    _session_low,
    _session_peak,
    armed_base_anchor,
    mid_rip_armed_coil,
    reset_detector_state_for_tests,
)
from app.engines.ict_breakout_monitor import (
    SLOW_GRIND_ARMED_TROUGH_READY,
    SLOW_GRIND_CONSOLIDATION_BASE_READY,
    _slow_grind_armed_trough_readiness,
    _slow_grind_consolidation_base_readiness,
    analyze_ict_breakout,
)
from app.engines.top_moment_gate import (
    building_has_causal_ftv_v_structure,
    classify_top_moment_type,
    explosion_alert_is_top_moment,
    top_moment_entry_allowed,
)
from app.engines.trade_ranking import rank_trade_evidence
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

# Observed chart anchors (Aug 26 SENSEX 77800 PE)
SESSION_LOW = 95.0
SESSION_PEAK = 190.0
TROUGH_PREMIUM = 95.0
V_RIP_PREMIUM = 165.0
POST_PEAK_PREMIUM = 140.15
POST_PEAK_COIL_BASE = 145.0
STRIKE = 77800.0


def _sensex_snap(*, spot: float = 77850.0, rsi: float = 44.0, hist: float = -3.34):
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 8, 26, 11, 49, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=spot,
        atmStrike=77800.0,
        spotChart=SpotChart(
            direction="NEUTRAL",
            rsi=rsi,
            rsiBias="NEUTRAL",
            macdBias="BEARISH",
            macdHistogram=hist,
            macd=0.41,
            macdSignal=3.75,
            momentum5Pct=-0.01,
            momentum15Pct=-0.02,
        ),
    )


def _off_low_pct(premium: float, low: float = SESSION_LOW) -> float:
    return (premium - low) / low * 100.0


def _peak_move_pct(peak: float = SESSION_PEAK, low: float = SESSION_LOW) -> float:
    return (peak - low) / low * 100.0


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_trough_phase_authorizes_armed_trough_at_session_low(mock_settings):
    """~₹95 at session trough — pad before the V-rip."""
    mock_settings.return_value = Settings()
    snap = _sensex_snap(spot=77920.0, rsi=38.0, hist=-1.2)
    ict = MagicMock(
        base_armed=True,
        v_rip_ready=True,
        base_relative_move_pct=0.0,
        flat_vertical_quality=12.0,
        armed_base_samples=4,
        velocity_3s=0.08,
    )
    alert = {
        "tier": "WATCH",
        "side": "PUT",
        "strike": STRIKE,
        "premium": TROUGH_PREMIUM,
        "offLowMovePct": 0.0,
        "ictBaseArmed": True,
        "ictVRipReady": True,
        "ictBaseRelativeMovePct": 0.0,
        "explosionScore": 9.0,
        "velocity3s": 0.08,
    }
    ok, reason = _slow_grind_armed_trough_readiness(
        snap=snap,
        event=MagicMock(
            side=Side.PUT,
            premium=TROUGH_PREMIUM,
            velocity_3s=0.08,
            strike=STRIKE,
        ),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is True
    assert reason == SLOW_GRIND_ARMED_TROUGH_READY
    assert alert["slowGrindArmedTrough"] is True


def test_v_rip_phase_classifies_as_top_moment_v():
    evidence = {
        "mode": "explosion",
        "tier": "BUILDING",
        "vRipReady": True,
        "midRipCoil": False,
        "velocity3s": 4.2,
        "velocity9s": 3.1,
        "offLowMovePct": _off_low_pct(V_RIP_PREMIUM),
        "peakMovePct": _off_low_pct(V_RIP_PREMIUM),
        "orderflowPositive": True,
    }
    assert classify_top_moment_type(evidence) == "V"
    ok, reason, moment = top_moment_entry_allowed(
        evidence,
        {"grade": "A", "gradePriority": 3},
        top_moments_only_enabled=True,
    )
    assert ok is True
    assert moment == "V"
    assert reason == "ok"


def test_mid_rip_coil_flags_post_peak_coil_at_140():
    assert mid_rip_armed_coil(
        session_low=SESSION_LOW,
        armed_base=POST_PEAK_COIL_BASE,
        premium=POST_PEAK_PREMIUM,
        session_peak=SESSION_PEAK,
    )


@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_post_peak_consolidation_rejected_peak_and_off_low(mock_settings, _afternoon):
    """11:49 slow chop ~₹140 — peak already +100%, off-low ~47%."""
    mock_settings.return_value = Settings()
    snap = _sensex_snap()
    ict = MagicMock(
        base_armed=True,
        base_relative_move_pct=8.0,
        flat_vertical_quality=40.0,
        armed_base_samples=10,
        velocity_3s=0.05,
        flat_then_vertical=True,
        active=True,
    )
    alert = {
        "tier": "BUILDING",
        "side": "PUT",
        "strike": STRIKE,
        "premium": POST_PEAK_PREMIUM,
        "offLowMovePct": _off_low_pct(POST_PEAK_PREMIUM),
        "peakMovePct": _peak_move_pct(),
        "ictBaseArmed": True,
        "ictFlatThenVertical": True,
        "ictBaseRelativeMovePct": 8.0,
        "flatVerticalQuality": 40.0,
        "ictArmedBaseSamples": 10,
        "velocity3s": 0.05,
        "explosionScore": 28.0,
        "midRipCoil": True,
        "ictMidRipCoil": True,
    }
    ok, reason = _slow_grind_consolidation_base_readiness(
        snap=snap,
        event=MagicMock(
            side=Side.PUT,
            premium=POST_PEAK_PREMIUM,
            velocity_3s=0.05,
            strike=STRIKE,
            tier="BUILDING",
            peak_move_pct=_peak_move_pct(),
        ),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is False
    assert reason in {
        "slow_grind_consolidation_mid_rip_coil",
        f"slow_grind_consolidation_peak>{24.0:g}",
        "slow_grind_consolidation_off_low_outside_3_30",
    }


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_armed_trough_rejects_post_peak_extended_off_low(mock_settings):
    mock_settings.return_value = Settings()
    snap = _sensex_snap()
    ict = MagicMock(
        base_armed=True,
        v_rip_ready=False,
        base_relative_move_pct=6.0,
        velocity_3s=0.05,
    )
    alert = {
        "side": "PUT",
        "strike": STRIKE,
        "premium": POST_PEAK_PREMIUM,
        "offLowMovePct": _off_low_pct(POST_PEAK_PREMIUM),
        "ictBaseArmed": True,
        "ictBaseRelativeMovePct": 6.0,
        "velocity3s": 0.05,
        "midRipCoil": True,
    }
    ok, reason = _slow_grind_armed_trough_readiness(
        snap=snap,
        event=MagicMock(
            side=Side.PUT,
            premium=POST_PEAK_PREMIUM,
            velocity_3s=0.05,
            strike=STRIKE,
        ),
        ict=ict,
        alert=alert,
        settings=mock_settings.return_value,
    )
    assert ok is False
    assert reason in {
        "slow_grind_armed_trough_mid_rip_coil",
        "slow_grind_armed_trough_not_at_trough",
    }


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_ict_rejects_post_peak_elite_base_rearm(mock_settings):
    """Mid-rip coil near ₹145 after peak ₹190 must not elite_base_ready."""
    reset_detector_state_for_tests()
    mock_settings.return_value = Settings(ict_armed_base_horizon_seconds=60.0)
    side = Side.PUT
    key = _open_key("SENSEX", STRIKE, side)
    now = datetime(2026, 8, 26, 11, 49, tzinfo=IST)

    _session_low[key] = SESSION_LOW
    _session_peak[key] = SESSION_PEAK
    _local_base_hist[key] = deque(
        [
            (now - timedelta(seconds=(10 - i) * 3), POST_PEAK_COIL_BASE + (i % 2) * 0.3)
            for i in range(10)
        ],
        maxlen=1200,
    )

    ict = analyze_ict_breakout(
        symbol="SENSEX",
        strike=STRIKE,
        side=side,
        premium=POST_PEAK_PREMIUM,
        session_move_pct=_off_low_pct(POST_PEAK_PREMIUM),
        peak_move_pct=_peak_move_pct(),
        velocity_3s=0.4,
        velocity_9s=0.2,
        volume=396_320,
        volume_surge=1.1,
        tier="BUILDING",
        reason="coil",
    )
    assert ict.elite_base_ready is False
    assert ict.armed_base_launch is False
    assert ict.base_premium == SESSION_LOW
    assert any(
        isinstance(r, str)
        and (
            r == "mid_rip_coil_rejected"
            or r.startswith("mid_rip_coil_rejected_")
            or r.startswith("session_low_base_")
        )
        for r in ict.reasons
    )


def test_top_moment_blocks_post_peak_slow_grind_without_causal_structure():
    evidence = {
        "mode": "explosion",
        "tier": "BUILDING",
        "slowGrindSuddenLift": True,
        "slowGrindConsolidationBase": True,
        "midRipCoil": True,
        "flatThenVertical": False,
        "activeBreakout": False,
        "offLowMovePct": _off_low_pct(POST_PEAK_PREMIUM),
        "peakMovePct": _peak_move_pct(),
        "velocity3s": 0.05,
        "velocity9s": 0.03,
        "explosionScore": 28.0,
        "orderflowPositive": True,
    }
    assert building_has_causal_ftv_v_structure(evidence) is False
    assert classify_top_moment_type(evidence) is None
    alert = {
        "tier": "BUILDING",
        "slowGrindSuddenLiftReady": True,
        "slowGrindConsolidationBase": True,
        "ictMidRipCoil": True,
        "ictFlatThenVertical": False,
        "ictBreakout": False,
        "offLowMovePct": _off_low_pct(POST_PEAK_PREMIUM),
    }
    assert explosion_alert_is_top_moment(alert) is False


def test_rank_penalizes_post_peak_mid_rip_false_pad():
    ranking = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": "BUILDING",
            "explosionScore": 28.0,
            "tqs": 55.0,
            "chartConfidence": 44.0,
            "velocity3s": 0.4,
            "velocity9s": 0.2,
            "localBaseMovePct": 8.0,
            "offLowMovePct": _off_low_pct(POST_PEAK_PREMIUM),
            "peakMovePct": _peak_move_pct(),
            "midRipCoil": True,
            "slowGrindConsolidationBase": True,
            "flatThenVertical": True,
            "activeBreakout": False,
            "orderflowPositive": True,
        }
    )
    penalty_codes = {p["code"] for p in ranking["penalties"]}
    assert "mid_rip_armed_coil" in penalty_codes or ranking["grade"] == "REJECT"


def test_valid_afternoon_consolidation_still_distinct_from_post_peak_rip():
    """Pre-rip afternoon base (peak <24%, off-low 3–30%) stays authorized."""
    off_low = 15.0
    peak_move = 18.0
    premium = SESSION_LOW * (1.0 + off_low / 100.0)
    snap = _sensex_snap(spot=77800.0, rsi=52.0, hist=0.04)
    ict = MagicMock(
        base_armed=True,
        base_relative_move_pct=8.0,
        flat_vertical_quality=42.0,
        armed_base_samples=12,
        velocity_3s=0.05,
        flat_then_vertical=True,
        active=True,
    )
    alert = {
        "tier": "BUILDING",
        "side": "PUT",
        "strike": STRIKE,
        "premium": premium,
        "offLowMovePct": off_low,
        "peakMovePct": peak_move,
        "ictBaseArmed": True,
        "ictFlatThenVertical": True,
        "ictBaseRelativeMovePct": 8.0,
        "flatVerticalQuality": 42.0,
        "ictArmedBaseSamples": 12,
        "velocity3s": 0.05,
        "explosionScore": 26.0,
    }
    with (
        patch(
            "app.engines.morning_premium_capture.in_afternoon_premium_capture_window",
            return_value=True,
        ),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=Settings()),
    ):
        ok, reason = _slow_grind_consolidation_base_readiness(
            snap=snap,
            event=MagicMock(
                side=Side.PUT,
                premium=premium,
                velocity_3s=0.05,
                strike=STRIKE,
                tier="BUILDING",
                peak_move_pct=peak_move,
            ),
            ict=ict,
            alert=alert,
            settings=Settings(),
        )
    assert ok is True
    assert reason == SLOW_GRIND_CONSOLIDATION_BASE_READY
    assert not mid_rip_armed_coil(
        session_low=SESSION_LOW,
        armed_base=premium,
        premium=premium,
        session_peak=SESSION_LOW * (1.0 + peak_move / 100.0),
    )
