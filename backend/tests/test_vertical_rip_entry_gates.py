"""Vertical rip entry gates — dead zone bypass, session low baseline, velocity peak."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import (
    _effective_session_baseline,
    _history,
    _open_key,
    _peak_velocity,
    _roll_session,
    _session_low,
    _session_open,
    _session_peak,
    _session_peak_move_pct,
    _tier_sticky,
    _update_peak_velocity,
    apply_velocity_peak_score_boost,
    scan_chain_explosions,
)
from app.engines.worst_day_itm_fade import dead_zone_allows_candidate
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _settings() -> MagicMock:
    s = MagicMock()
    s.explosion_scan_range = 800
    s.explosion_sensex_scan_range = 1500
    s.explosion_worst_day_scan_range = 500
    s.explosion_sensex_worst_day_scan_range = 500
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 400.0
    s.explosion_max_premium_inr = 400.0
    s.open_premium_explosion_enabled = True
    s.open_premium_min_move_pct = 15.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_min_score = 38.0
    s.aggressive_min_explosion_score = 45
    s.expiry_atm_tier_velocity_mult = 1.0
    s.explosion_atm_proximity_bonus_max = 8.0
    s.explosion_otm_depth_penalty_per_step = 3.0
    s.peak_move_explosion_bypass_enabled = True
    s.peak_move_explosion_min_pct = 35.0
    s.peak_move_explosion_min_tier = "ELITE"
    s.peak_move_explosion_score_floor = 38.0
    s.peak_move_explosion_score_boost_per_pct = 0.12
    s.session_open_use_intraday_low = True
    s.session_open_low_backfill_pct = 8.0
    s.velocity_peak_score_boost_enabled = True
    s.velocity_peak_min_3s = 2.5
    s.velocity_peak_score_floor = 42.0
    s.velocity_peak_decay_seconds = 180
    s.velocity_peak_score_blend = 0.55
    s.explosion_volume_awaken_min = 25000
    s.explosion_volume_awaken_min_velocity_3s = 1.0
    return s


def _chain(strike: float, call_ltp: float) -> list[dict]:
    return [{
        "strike_price": strike,
        "call_options": {"ltp": call_ltp, "volume": 12000},
    }]


@dataclass
class _Cand:
    mode: str = "explosion"
    tier: str = "ELITE"
    explosion_event: object = None


@patch("app.config.get_settings")
def test_session_low_backfill_raises_peak_move(mock_settings):
    mock_settings.return_value = _settings()
    _roll_session()
    _session_open.clear()
    _session_low.clear()
    _session_peak.clear()

    key = _open_key("NIFTY", 24150.0, Side.CALL)
    _session_open[key] = 130.0
    _session_low[key] = 130.0
    _session_peak[key] = 165.0

    _session_low[key] = 118.0
    baseline = _effective_session_baseline(key, 137.0, None)
    assert baseline == 118.0
    peak_pct = _session_peak_move_pct("NIFTY", 24150.0, Side.CALL, 137.0, None)
    assert peak_pct >= 39.0


@patch("app.config.get_settings")
def test_peak_velocity_retained_after_fade(mock_settings):
    mock_settings.return_value = _settings()
    _peak_velocity.clear()
    key = "NIFTY:CALL:24150"
    now = datetime.now(IST)
    _peak_velocity[key] = (5.2, now - timedelta(seconds=30))
    retained = _update_peak_velocity(key, -1.0)
    assert retained >= 5.0


@patch("app.config.get_settings")
def test_velocity_peak_boost_raises_faded_score(mock_settings):
    mock_settings.return_value = _settings()
    boosted = apply_velocity_peak_score_boost(
        23.0, v3=-1.0, peak_v3=5.2, tier="ELITE", peak_move=40.0,
    )
    assert boosted >= 42.0


@patch("app.engines.worst_day_itm_fade.in_worst_day_dead_zone", return_value=True)
@patch("app.config.get_settings")
def test_dead_zone_allows_elite_vertical_rip(mock_settings, _dz):
    mock_settings.return_value = _settings()
    mock_settings.return_value.worst_day_dead_zone_explosion_bypass_enabled = True
    mock_settings.return_value.worst_day_dead_zone_bypass_min_tier = "EXPLODING"
    mock_settings.return_value.worst_day_dead_zone_bypass_min_peak_pct = 30.0
    mock_settings.return_value.worst_day_dead_zone_bypass_min_velocity_3s = 2.0
    mock_settings.return_value.worst_day_dead_zone_bypass_min_session_move_pct = 35.0

    from app.engines.explosion_detector import ExplosionEvent

    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        premium=137.0,
        velocity_3s=-1.0,
        velocity_9s=0.5,
        velocity_15s=1.0,
        volume_surge=2.0,
        explosion_score=42.0,
        tier="ELITE",
        reason="peak rip",
        daily_move_pct=23.0,
        peak_move_pct=40.0,
    )
    ok, reason = dead_zone_allows_candidate(_Cand(explosion_event=event))
    assert ok is True
    assert reason == "ok"

    ok2, _ = dead_zone_allows_candidate(_Cand(mode="quick_sideways"))
    assert ok2 is False


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_faded_24150_style_rip_qualifies_after_boosts(mock_settings, _open):
    """Simulate 118→165 peak, fade to 137 — score should clear 38 floor."""
    mock_settings.return_value = _settings()
    _history.clear()
    _session_open.clear()
    _session_low.clear()
    _session_peak.clear()
    _tier_sticky.clear()
    _peak_velocity.clear()

    chain = _chain(24150.0, 118.0)
    scan_chain_explosions("NIFTY", chain, spot=24159.0, atm=24150.0)
    chain[0]["call_options"]["ltp"] = 165.0
    scan_chain_explosions("NIFTY", chain, spot=24159.0, atm=24150.0)
    chain[0]["call_options"]["ltp"] = 137.0
    events = scan_chain_explosions("NIFTY", chain, spot=24159.0, atm=24150.0)
    calls = [e for e in events if e.side == Side.CALL and e.strike == 24150.0]
    assert calls
    assert calls[0].peak_move_pct >= 35.0
    assert calls[0].explosion_score >= 38.0
