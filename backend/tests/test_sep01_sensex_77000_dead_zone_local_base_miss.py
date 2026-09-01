"""Sep01 SENSEX CALL 77000 — ELITE armed_base blocked by worst_day_dead_zone."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import ExplosionEvent
from app.engines.worst_day_itm_fade import dead_zone_allows_candidate
from app.models.schemas import Side


def _settings() -> MagicMock:
    s = MagicMock()
    s.worst_day_dead_zone_explosion_bypass_enabled = True
    s.worst_day_dead_zone_bypass_min_tier = "EXPLODING"
    s.worst_day_dead_zone_bypass_min_peak_pct = 30.0
    s.worst_day_dead_zone_bypass_min_velocity_3s = 2.0
    s.worst_day_dead_zone_bypass_min_session_move_pct = 35.0
    s.worst_day_dead_zone_local_base_bypass_enabled = True
    s.worst_day_dead_zone_local_base_bypass_min_tier = "EXPLODING"
    s.worst_day_dead_zone_local_base_min_peak_pct = 25.0
    s.worst_day_dead_zone_local_base_min_lb_pct = 2.0
    s.worst_day_dead_zone_local_base_max_lb_pct = 25.0
    return s


@dataclass
class _Cand:
    mode: str = "explosion"
    tier: str = "ELITE"
    explosion_event: object = None
    alert: dict | None = None


def _sep01_sensex_77000_event() -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77000.0,
        premium=393.05,
        velocity_3s=-0.37,
        velocity_9s=0.5,
        velocity_15s=1.0,
        volume_surge=2.0,
        explosion_score=100.0,
        tier="ELITE",
        reason="armed_base_launch",
        daily_move_pct=24.34,
        peak_move_pct=25.06,
    )


@patch("app.engines.worst_day_itm_fade.in_worst_day_dead_zone", return_value=True)
@patch("app.config.get_settings")
def test_dead_zone_allows_elite_local_base_armed_at_winner_floor(mock_settings, _dz):
    mock_settings.return_value = _settings()
    event = _sep01_sensex_77000_event()
    alert = {
        "momentType": "armed_base_launch",
        "ictFirstLift": True,
        "localBaseMovePct": 24.3,
        "ictPattern": "flat_then_vertical",
    }
    ok, reason = dead_zone_allows_candidate(_Cand(explosion_event=event, alert=alert))
    assert ok is True
    assert reason == "ok"


@patch("app.engines.worst_day_itm_fade.in_worst_day_dead_zone", return_value=True)
@patch("app.config.get_settings")
def test_dead_zone_still_blocks_immature_peak_under_floor(mock_settings, _dz):
    mock_settings.return_value = _settings()
    event = _sep01_sensex_77000_event()
    event.peak_move_pct = 22.0
    event.daily_move_pct = 22.0
    alert = {
        "momentType": "armed_base_launch",
        "ictFirstLift": True,
        "localBaseMovePct": 12.0,
    }
    ok, reason = dead_zone_allows_candidate(_Cand(explosion_event=event, alert=alert))
    assert ok is False
    assert reason == "worst_day_dead_zone"


@patch("app.engines.worst_day_itm_fade.in_worst_day_dead_zone", return_value=True)
@patch("app.config.get_settings")
def test_dead_zone_still_blocks_late_chase_high_daily_low_lb(mock_settings, _dz):
    mock_settings.return_value = _settings()
    event = _sep01_sensex_77000_event()
    event.peak_move_pct = 24.0
    event.daily_move_pct = 28.0
    alert = {
        "momentType": "armed_base_launch",
        "localBaseMovePct": 3.0,
    }
    ok, reason = dead_zone_allows_candidate(_Cand(explosion_event=event, alert=alert))
    assert ok is False
    assert reason == "worst_day_dead_zone"
