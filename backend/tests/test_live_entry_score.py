"""Live entry score — tick stamp and pre-entry gate."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.live_entry_score import (
    compute_live_entry_score,
    live_entry_score_blocks_entry,
    stamp_alert_live_entry_scores,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


@patch("app.engines.live_entry_score.get_settings")
def test_stamp_alert_adds_live_entry_score(mock_settings):
    s = MagicMock()
    s.live_entry_score_stamp_on_alerts = True
    s.live_execution_trade_score_enabled = True
    s.live_execution_trade_score_dump_penalty = 45.0
    s.live_execution_trade_score_mom_factor = 8.0
    s.live_entry_score_negative_v3_penalty_per_point = 3.0
    s.live_entry_score_dump_cap = 42.0
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s

    alert = {
        "explosionScore": 100.0,
        "premium": 150.0,
        "sessionPeakPremium": 240.0,
        "sessionLowPremium": 45.0,
        "velocity3s": -0.8,
        "velocity9s": -1.0,
        "tier": "ELITE",
    }
    out = stamp_alert_live_entry_scores(dict(alert))
    assert out["radarExplosionScore"] == 100.0
    assert out["liveEntryScore"] < 55.0


@patch("app.engines.live_entry_score.get_settings")
def test_compute_live_penalizes_negative_velocity(mock_settings):
    s = MagicMock()
    s.live_execution_trade_score_enabled = True
    s.live_execution_trade_score_dump_penalty = 45.0
    s.live_execution_trade_score_mom_factor = 8.0
    s.live_entry_score_negative_v3_penalty_per_point = 3.0
    s.live_entry_score_dump_cap = 42.0
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s

    live, meta = compute_live_entry_score(
        {"explosionScore": 96.0, "velocity3s": -2.0, "velocity9s": 0.5, "premium": 80.0},
        radar_score=96.0,
        settings=s,
    )
    assert live < 96.0
    assert meta["velocity3Penalty"] > 0


@patch("app.engines.live_entry_score.get_settings")
@patch("app.engines.explosion_detector.get_session_peak_premium")
@patch("app.engines.explosion_detector.get_session_low_premium")
def test_live_entry_gate_blocks_sep24_style(mock_low, mock_peak, mock_settings):
    s = MagicMock()
    s.live_entry_score_gate_enabled = True
    s.live_entry_score_replace_candidate_score = True
    s.live_entry_score_min_elite = 52.0
    s.live_entry_score_min_exploding = 48.0
    s.live_entry_score_min_default = 44.0
    s.live_execution_trade_score_enabled = True
    s.live_execution_trade_score_dump_penalty = 45.0
    s.live_execution_trade_score_mom_factor = 8.0
    s.live_entry_score_negative_v3_penalty_per_point = 3.0
    s.live_entry_score_dump_cap = 42.0
    s.live_entry_score_chase_max_range_position = 0.45
    s.live_entry_score_chase_max_velocity_3s = 1.0
    s.live_entry_score_chase_range_penalty_scale = 120.0
    s.premium_post_spike_dump_guard_enabled = True
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s
    mock_peak.return_value = 260.0
    mock_low.return_value = 45.0

    from app.engines.explosion_detector import ExplosionEvent

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=73900.0,
        premium=234.0,
        velocity_3s=-0.5,
        velocity_9s=-0.8,
        velocity_15s=0.0,
        volume_surge=2.0,
        explosion_score=100.0,
        tier="ELITE",
        reason="test",
        daily_move_pct=80.0,
    )
    candidate = SimpleNamespace(
        symbol="SENSEX",
        side=Side.PUT,
        strike=73900.0,
        score=100.0,
        confidence=100.0,
        tier="ELITE",
        mode="explosion",
        explosion_event=event,
        alert={
            "explosionScore": 100.0,
            "premium": 234.0,
            "sessionPeakPremium": 260.0,
            "sessionLowPremium": 45.0,
            "velocity3s": -0.5,
            "velocity9s": -0.8,
            "tier": "ELITE",
        },
    )
    blocked, reason, _ = live_entry_score_blocks_entry(candidate, None)
    assert blocked
    assert "live_entry_score" in reason or reason == "premium_post_spike_dump"


@patch("app.engines.live_entry_score.get_settings")
def test_high_radar_softens_mild_negative_v3(mock_settings):
    s = MagicMock()
    s.live_execution_trade_score_enabled = True
    s.live_execution_trade_score_dump_penalty = 45.0
    s.live_execution_trade_score_mom_factor = 8.0
    s.live_entry_score_negative_v3_penalty_per_point = 2.0
    s.live_entry_score_negative_v3_deadband = 0.55
    s.live_entry_score_high_radar_soft_penalty_min = 94.0
    s.live_entry_score_high_radar_penalty_scale = 0.45
    s.live_entry_score_dump_cap = 42.0
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s

    live, meta = compute_live_entry_score(
        {"explosionScore": 100.0, "velocity3s": -0.77, "velocity9s": -0.5, "premium": 120.0},
        radar_score=100.0,
        settings=s,
    )
    assert live >= 97.0
    assert meta.get("highRadarSoftPenalty") is True


@patch("app.engines.live_entry_score.get_settings")
def test_compute_live_penalizes_hot_v3_near_peak_extended_spike(mock_settings):
    s = MagicMock()
    s.live_execution_trade_score_enabled = True
    s.live_execution_trade_score_dump_penalty = 45.0
    s.live_execution_trade_score_mom_factor = 8.0
    s.live_entry_score_negative_v3_penalty_per_point = 3.0
    s.live_entry_score_negative_v3_deadband = 0.55
    s.live_entry_score_dump_cap = 42.0
    s.live_entry_score_chase_max_range_position = 0.45
    s.live_entry_score_chase_max_velocity_3s = 1.0
    s.live_entry_score_chase_range_penalty_scale = 90.0
    s.live_entry_score_chase_hot_v3_extended_spike_enabled = True
    s.live_entry_score_chase_hot_v3_min_spike_run_pct = 18.0
    s.live_entry_score_chase_hot_v3_min_range_position = 0.72
    s.live_entry_score_chase_hot_v3_penalty_scale = 120.0
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s

    live, meta = compute_live_entry_score(
        {
            "explosionScore": 100.0,
            "premium": 84.15,
            "sessionPeakPremium": 86.2,
            "sessionLowPremium": 71.6,
            "velocity3s": 2.0,
            "spikeRunPct": 20.39,
        },
        radar_score=100.0,
        settings=s,
    )
    assert meta.get("hotV3ExtendedSpikeChasePenalty", 0) > 0
    assert live < 100.0


def _seed_score_tape(prems, *, step_s=1.0):
    import app.engines.explosion_detector as ed
    from app.engines.explosion_detector import _open_key
    from collections import deque

    key = _open_key("NIFTY", 24500.0, Side.CALL)
    t0 = datetime(2026, 10, 24, 10, 0, tzinfo=IST)
    ed._local_base_hist[key] = deque(
        (t0 + timedelta(seconds=step_s * i), float(p)) for i, p in enumerate(prems)
    )


def _hot_spike_alert(**extra):
    row = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 24500,
        "explosionScore": 100.0,
        "premium": 84.15,
        "sessionPeakPremium": 86.2,
        "sessionLowPremium": 71.6,
        "velocity3s": 2.0,
        "spikeRunPct": 20.39,
    }
    row.update(extra)
    return row


@patch("app.engines.live_entry_score.get_settings")
def test_fresh_lift_skips_chase_range_penalty(mock_settings):
    """Cold v3 at session high is normal on the lift tick — not a range chase."""
    import app.engines.explosion_detector as ed

    s = MagicMock()
    s.live_execution_trade_score_enabled = True
    s.live_execution_trade_score_dump_penalty = 45.0
    s.live_execution_trade_score_mom_factor = 8.0
    s.live_entry_score_negative_v3_penalty_per_point = 3.0
    s.live_entry_score_negative_v3_deadband = 0.55
    s.live_entry_score_dump_cap = 42.0
    s.live_entry_score_chase_max_range_position = 0.45
    s.live_entry_score_chase_max_velocity_3s = 1.0
    s.live_entry_score_chase_range_penalty_scale = 90.0
    s.live_entry_score_chase_hot_v3_extended_spike_enabled = False
    s.explosion_post_peak_chase_min_peak_age_seconds = 45.0
    s.explosion_post_peak_chase_lookback_seconds = 900.0
    s.explosion_post_peak_chase_near_top_frac = 0.12
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s
    ed._local_base_hist.clear()
    try:
        _seed_score_tape([100.0] * 20 + [140.0], step_s=1.0)
        alert = {
            "symbol": "NIFTY",
            "side": "CALL",
            "strike": 24500,
            "explosionScore": 95.0,
            "premium": 140.0,
            "sessionPeakPremium": 140.0,
            "sessionLowPremium": 100.0,
            "velocity3s": 0.3,
        }
        live, meta = compute_live_entry_score(alert, radar_score=95.0, settings=s)
    finally:
        ed._local_base_hist.clear()
    assert meta.get("chaseRangePenalty", 0) == 0
    assert live > 80.0


@patch("app.engines.live_entry_score.get_settings")
def test_fresh_session_high_skips_hot_v3_chase_penalty(mock_settings):
    """The print that just became the high is the lift, not an extended chase."""
    import app.engines.explosion_detector as ed

    s = MagicMock()
    s.live_execution_trade_score_enabled = True
    s.live_execution_trade_score_dump_penalty = 45.0
    s.live_execution_trade_score_mom_factor = 8.0
    s.live_entry_score_negative_v3_penalty_per_point = 3.0
    s.live_entry_score_negative_v3_deadband = 0.55
    s.live_entry_score_dump_cap = 42.0
    s.live_entry_score_chase_max_range_position = 0.45
    s.live_entry_score_chase_max_velocity_3s = 1.0
    s.live_entry_score_chase_range_penalty_scale = 90.0
    s.live_entry_score_chase_hot_v3_extended_spike_enabled = True
    s.live_entry_score_chase_hot_v3_min_spike_run_pct = 18.0
    s.live_entry_score_chase_hot_v3_min_range_position = 0.72
    s.live_entry_score_chase_hot_v3_penalty_scale = 120.0
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s
    ed._local_base_hist.clear()
    try:
        _seed_score_tape([60.0] * 15 + [84.15])
        _, meta = compute_live_entry_score(_hot_spike_alert(), radar_score=100.0, settings=s)
    finally:
        ed._local_base_hist.clear()
    assert meta.get("hotV3ExtendedSpikeChasePenalty", 0) == 0


@patch("app.engines.live_entry_score.get_settings")
def test_aged_session_high_still_takes_hot_v3_chase_penalty(mock_settings):
    import app.engines.explosion_detector as ed

    s = MagicMock()
    s.live_execution_trade_score_enabled = True
    s.live_execution_trade_score_dump_penalty = 45.0
    s.live_execution_trade_score_mom_factor = 8.0
    s.live_entry_score_negative_v3_penalty_per_point = 3.0
    s.live_entry_score_negative_v3_deadband = 0.55
    s.live_entry_score_dump_cap = 42.0
    s.live_entry_score_chase_max_range_position = 0.45
    s.live_entry_score_chase_max_velocity_3s = 1.0
    s.live_entry_score_chase_range_penalty_scale = 90.0
    s.live_entry_score_chase_hot_v3_extended_spike_enabled = True
    s.live_entry_score_chase_hot_v3_min_spike_run_pct = 18.0
    s.live_entry_score_chase_hot_v3_min_range_position = 0.72
    s.live_entry_score_chase_hot_v3_penalty_scale = 120.0
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s
    ed._local_base_hist.clear()
    try:
        _seed_score_tape([60.0] * 8 + [84.15] * 5, step_s=20.0)
        _, meta = compute_live_entry_score(_hot_spike_alert(), radar_score=100.0, settings=s)
    finally:
        ed._local_base_hist.clear()
    assert meta.get("hotV3ExtendedSpikeChasePenalty", 0) > 0


def test_live_entry_moment_active():
    from app.engines.live_entry_score import live_entry_moment_active

    evidence = {"liveEntryScore": 97.0, "explosionScore": 100.0, "tier": "EXPLODING"}
    assert live_entry_moment_active(evidence)


@patch("app.engines.live_entry_score.get_settings")
def test_moment_waives_exploding_tier_for_top_trades(mock_settings):
    from app.engines.live_entry_score import live_entry_moment_waives_exploding_tier

    s = MagicMock()
    s.live_entry_moment_waiver_enabled = True
    s.live_entry_moment_min_live = 86.0
    s.live_entry_moment_min_radar = 92.0
    s.live_entry_moment_waives_exploding_tier = True
    mock_settings.return_value = s
    evidence = {"tier": "EXPLODING", "liveEntryScore": 96.0, "explosionScore": 100.0}
    assert live_entry_moment_waives_exploding_tier(evidence, settings=s)


def test_live_entry_best_trade_capture_active():
    from app.engines.live_entry_score import live_entry_best_trade_capture_active

    assert live_entry_best_trade_capture_active(
        {"liveEntryScore": 97.0, "explosionScore": 100.0, "tier": "EXPLODING"},
        require_explicit_live=True,
    )
    assert not live_entry_best_trade_capture_active(
        {"liveEntryScore": 80.0, "explosionScore": 100.0, "tier": "EXPLODING"},
        require_explicit_live=True,
    )
    assert not live_entry_best_trade_capture_active(
        {"explosionScore": 100.0, "tier": "EXPLODING"},
        require_explicit_live=True,
    )


def test_ftv_live_best_moment_authorization():
    from app.engines.trade_ranking import ftv_authorization_policy

    evidence = {
        "mode": "explosion",
        "tier": "EXPLODING",
        "explosionScore": 100.0,
        "liveEntryScore": 97.0,
        "flatVerticalQuality": 50.0,
        "tqs": 40.0,
        "velocity3s": 0.5,
        "velocity9s": 0.3,
        "localBaseMovePct": 12.0,
        "timingAssessment": "CHASE",
        "flatThenVertical": True,
        "activeBreakout": True,
    }
    ranking = {"grade": "B"}
    auth = ftv_authorization_policy(evidence, ranking, top_ftv_a_enabled=True)
    assert auth.mode == "LIVE_BEST_MOMENT"
    assert auth.reason == "ok"
