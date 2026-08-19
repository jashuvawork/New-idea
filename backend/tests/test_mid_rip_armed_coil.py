"""Aug19 SENSEX 76900 PE — mid-rip coil must not look like a fresh base.

Chart base ~80–100 ripped toward ~240. After horizon expiry a tight coil near
~162 re-armed; elite_base_ready fired at pad 2.6% while session was already
~42% off the true trough. Entry @168 was after the moment.
"""

from collections import deque
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

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
from app.engines.ict_breakout_monitor import analyze_ict_breakout
from app.engines.trade_ranking import rank_trade_evidence
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def test_mid_rip_coil_detector_flags_aug19_shape():
    assert mid_rip_armed_coil(
        session_low=90.0,
        armed_base=162.35,
        premium=168.15,
        session_peak=240.0,
    )
    # Deep pullback after a completed rip can form a genuine higher base.
    assert not mid_rip_armed_coil(
        session_low=90.0,
        armed_base=155.0,
        premium=156.0,
        session_peak=240.0,  # ~35%+ pullback from peak
    )
    # True base lift stays clean.
    assert not mid_rip_armed_coil(
        session_low=90.0,
        armed_base=90.0,
        premium=95.0,
        session_peak=95.0,
    )


def test_armed_base_refuses_mid_rip_rearm_above_session_trough():
    reset_detector_state_for_tests()
    settings = Settings(ict_armed_base_horizon_seconds=60.0)
    side = Side.PUT
    key = _open_key("SENSEX", 76900.0, side)
    start = datetime(2026, 8, 19, 10, 0, tzinfo=IST)

    # True trough coil around 90.
    _local_base_hist[key] = deque(
        [(start + timedelta(seconds=i * 3), 89.5 + (i % 2) * 0.4) for i in range(8)],
        maxlen=1200,
    )
    _session_low[key] = 89.5
    _session_peak[key] = 95.0
    first = armed_base_anchor("SENSEX", 76900.0, side, 92.0, settings=settings)
    assert first["armed"] is True
    assert first["basePremium"] == 89.5

    # Horizon expires; mid-rip pause coil near 162 while still expanded.
    expiry = datetime.fromisoformat(first["expiresAt"])
    new_start = expiry + timedelta(seconds=1)
    _session_peak[key] = 240.0
    _local_base_hist[key].extend(
        (new_start + timedelta(seconds=i * 3), 161.5 + (i % 2) * 0.4)
        for i in range(10)
    )
    second = armed_base_anchor("SENSEX", 76900.0, side, 168.15, settings=settings)
    assert second.get("armed") is False
    assert second.get("midRipCoil") is True


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_ict_rejects_mid_rip_elite_base_ready(mock_settings):
    reset_detector_state_for_tests()
    mock_settings.return_value = Settings()
    side = Side.PUT
    key = _open_key("SENSEX", 76900.0, side)
    now = datetime(2026, 8, 19, 12, 45, tzinfo=IST)
    # Recent mid-rip coil only — no true trough samples in lookback.
    _local_base_hist[key] = deque(
        [(now - timedelta(seconds=(10 - i) * 3), 161.5 + (i % 2) * 0.3) for i in range(10)],
        maxlen=1200,
    )
    _session_low[key] = 90.0
    _session_peak[key] = 240.0

    ict = analyze_ict_breakout(
        symbol="SENSEX",
        strike=76900.0,
        side=side,
        premium=168.15,
        session_move_pct=42.0,
        peak_move_pct=42.0,
        velocity_3s=2.6,
        velocity_9s=2.0,
        volume=2_000_000,
        volume_surge=2.5,
        tier="EXPLODING",
        reason="volAwaken",
    )
    assert ict.elite_base_ready is False
    assert ict.armed_base_launch is False
    assert ict.base_premium == 90.0
    assert ict.base_relative_move_pct >= 80.0
    assert any(
        isinstance(r, str)
        and (
            r == "mid_rip_coil_rejected"
            or r.startswith("mid_rip_coil_rejected_")
            or r.startswith("session_low_base_")
        )
        for r in ict.reasons
    )


def test_rank_rejects_mid_rip_false_early_s_preauth():
    ranking = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": "EXPLODING",
            "explosionScore": 100.0,
            "tqs": 60.0,
            "chartConfidence": 50.0,
            "velocity3s": 2.59,
            "velocity9s": 2.0,
            "localBaseMovePct": 2.6,
            "offLowMovePct": 42.1,
            "eliteBaseReady": True,
            "flatThenVertical": True,
            "activeBreakout": True,
            "orderflowPositive": True,
            "volumeAwaken": True,
            "flatVerticalQuality": 60.5,
        }
    )
    assert ranking["grade"] != "S"
    assert ranking["executionAuthorization"] is None
    assert ranking["topRankEligible"] is False
    codes = {p["code"] for p in ranking["penalties"]}
    assert "mid_rip_false_early_pad" in codes or ranking["grade"] == "REJECT"


def test_rank_rejects_explicit_mid_rip_flag():
    ranking = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": "EXPLODING",
            "explosionScore": 100.0,
            "tqs": 60.0,
            "chartConfidence": 50.0,
            "velocity3s": 2.59,
            "velocity9s": 2.0,
            "localBaseMovePct": 2.6,
            "offLowMovePct": 42.1,
            "eliteBaseReady": True,
            "midRipCoil": True,
            "flatThenVertical": True,
            "activeBreakout": True,
            "orderflowPositive": True,
            "volumeAwaken": True,
            "flatVerticalQuality": 60.5,
        }
    )
    assert ranking["grade"] == "REJECT"
    assert any(p["code"] == "mid_rip_armed_coil" for p in ranking["penalties"])
