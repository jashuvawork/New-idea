"""PUT slide pad — cold velocity waiver (Oct 8 SENSEX negative_velocity miss)."""

from app.engines.explosion_detector import (
    _open_key,
    _session_peak,
    reset_detector_state_for_tests,
    session_high_relative_move_pct,
)
from app.engines.pad_lane_capture import pad_lane_cold_velocity_ok
from app.engines.put_slide_ce_mirror import put_slide_cold_velocity_ok, put_slide_pad_context
from app.engines.trade_ranking import rank_trade_evidence
from app.models.schemas import Side


def test_session_high_relative_move_pct_from_peak():
    reset_detector_state_for_tests()
    key = _open_key("SENSEX", 72400.0, Side.PUT)
    _session_peak[key] = 200.0
    off = session_high_relative_move_pct("SENSEX", 72400.0, Side.PUT, 180.0)
    assert 9.5 <= off <= 10.5


def test_put_slide_pad_context_v_rip_session_high():
    evidence = {
        "side": "PUT",
        "momentType": "v_rip_session_high",
        "localBaseMovePct": 8.0,
    }
    assert put_slide_pad_context(evidence) is True


def test_put_slide_cold_velocity_ok_allows_slide_pause():
    evidence = {
        "side": "PUT",
        "tier": "ELITE",
        "momentType": "v_rip_session_high",
        "localBaseMovePct": 10.0,
        "offHighMovePct": 4.0,
    }
    assert put_slide_cold_velocity_ok(evidence, -1.8, -0.4) is True
    assert put_slide_cold_velocity_ok(evidence, -3.0, -0.4) is False


def test_put_slide_cold_velocity_blocks_extended_chase():
    evidence = {
        "side": "PUT",
        "tier": "ELITE",
        "momentType": "v_rip_session_high",
        "localBaseMovePct": 35.0,
    }
    assert put_slide_cold_velocity_ok(evidence, -1.0, 0.0) is False


def test_pad_lane_delegates_put_slide_cold_velocity():
    evidence = {
        "side": "PUT",
        "tier": "ELITE",
        "reason": "v_rip_session_high_ready",
        "localBaseMovePct": 12.0,
        "offHighMovePct": 3.0,
    }
    assert pad_lane_cold_velocity_ok(evidence, -2.0, -0.8) is True


def test_rank_trade_evidence_put_slide_not_reject_on_cold_velocity():
    ranking = rank_trade_evidence(
        {
            "mode": "explosion",
            "side": "PUT",
            "tier": "ELITE",
            "explosionScore": 120.0,
            "tqs": 55.0,
            "velocity3s": -1.9,
            "velocity9s": -0.3,
            "localBaseMovePct": 11.0,
            "offHighMovePct": 5.0,
            "momentType": "v_rip_session_high",
            "timingAssessment": "GOOD",
            "flatThenVertical": True,
            "activeBreakout": True,
            "orderflowPositive": True,
        }
    )
    assert ranking["grade"] != "REJECT"
