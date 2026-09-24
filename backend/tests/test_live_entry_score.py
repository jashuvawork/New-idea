"""Live entry score — tick stamp and pre-entry gate."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.live_entry_score import (
    compute_live_entry_score,
    live_entry_score_blocks_entry,
    stamp_alert_live_entry_scores,
)
from app.models.schemas import Side


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
