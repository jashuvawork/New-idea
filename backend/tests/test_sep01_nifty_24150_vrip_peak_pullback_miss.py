"""Sep01 NIFTY CALL 24150/24100 — v_rip_session_low peak-confirmed pad micro-pullback miss."""

from types import SimpleNamespace
from unittest.mock import patch

from app.config import Settings
from app.engines.explosion_entry_guards import immature_explosion_blocked
from app.engines.ict_breakout_monitor import ICTBreakoutSignal, merge_alert_ict_stamps
from app.engines.pad_lane_capture import pad_lane_cold_velocity_ok, pad_lane_ftv_waives_timing_block


def _sep01_alert(**overrides):
    base = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "momentType": "v_rip_session_low",
        "localBaseMovePct": 6.7,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "volumeAwaken": True,
        "velocity3s": -1.73,
        "velocity9s": -0.5,
        "peakMovePct": 35.0,
        "dailyMovePct": 35.0,
    }
    base.update(overrides)
    return base


@patch("app.engines.explosion_entry_guards.get_settings", return_value=Settings())
def test_immature_admits_v_rip_peak_pad_without_volume_awakening(_mock_settings):
    """24100-style: v_rip_ready + peak ≥25% at 6.6% pad must not block immature_local_base."""
    event = SimpleNamespace(
        tier="EXPLODING",
        daily_move_pct=25.5,
        peak_move_pct=25.5,
        explosion_score=91.5,
    )
    ict = ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=40.0,
        reasons=[],
        flat_then_vertical=True,
        volume_awakening=False,
        v_rip_ready=True,
        base_relative_move_pct=6.6,
    )
    blocked, reason = immature_explosion_blocked(event, ict=ict)
    assert blocked is False
    assert reason == ""


@patch("app.engines.pad_lane_capture.get_settings", return_value=Settings())
def test_peak_confirmed_pad_waives_ftv_timing_on_micro_pullback(_mock_settings):
    """24150-style: ELITE flat→vertical at 6.7% lb, peak 35%, v3=-1.73 after vertical."""
    evidence = {
        "tier": "ELITE",
        "flatThenVertical": True,
        "activeBreakout": True,
        "localBaseMovePct": 6.7,
        "peakMovePct": 35.0,
        "velocity3s": -1.73,
        "velocity9s": -0.5,
        "volumeAwaken": True,
    }
    assert pad_lane_cold_velocity_ok(evidence, -1.73, -0.5) is True
    assert pad_lane_ftv_waives_timing_block(evidence) is True


@patch("app.engines.pad_lane_capture.get_settings", return_value=Settings())
def test_peak_confirmed_pad_still_blocks_deep_negative_velocity(_mock_settings):
    evidence = {
        "tier": "ELITE",
        "flatThenVertical": True,
        "activeBreakout": True,
        "localBaseMovePct": 6.7,
        "peakMovePct": 35.0,
        "velocity3s": -3.5,
        "velocity9s": -2.0,
    }
    assert pad_lane_cold_velocity_ok(evidence, -3.5, -2.0) is False


@patch("app.engines.pad_lane_capture.get_settings", return_value=Settings())
def test_sub_peak_pad_keeps_tight_cold_velocity_floor(_mock_settings):
    """Peaks <25% must keep the -1.2 v3 floor — no late-chase loosening."""
    evidence = {
        "tier": "ELITE",
        "flatThenVertical": True,
        "activeBreakout": True,
        "localBaseMovePct": 6.7,
        "peakMovePct": 18.0,
        "velocity3s": -1.73,
        "velocity9s": -0.5,
    }
    assert pad_lane_cold_velocity_ok(evidence, -1.73, -0.5) is False


@patch("app.engines.explosion_entry_guards.get_settings", return_value=Settings())
def test_merge_alert_v_rip_moment_stamps_ready_for_immature(_mock_settings):
    alert = _sep01_alert(tier="EXPLODING", peakMovePct=25.5, dailyMovePct=25.5, localBaseMovePct=6.6)
    event = SimpleNamespace(
        tier="EXPLODING",
        daily_move_pct=25.5,
        peak_move_pct=25.5,
        explosion_score=91.5,
    )
    ict = merge_alert_ict_stamps(
        ICTBreakoutSignal(
            active=True,
            pattern="flat_then_vertical",
            score=40.0,
            reasons=[],
            flat_then_vertical=True,
            base_relative_move_pct=6.6,
        ),
        alert,
    )
    assert ict.v_rip_ready is True
    blocked, reason = immature_explosion_blocked(event, ict=ict)
    assert blocked is False
    assert reason == ""
