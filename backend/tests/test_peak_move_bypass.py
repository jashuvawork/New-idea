"""Peak-move explosion bypass — faded vertical rips still qualify."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import (
    ExplosionEvent,
    apply_peak_move_score_boost,
    effective_explosion_min_score,
    scan_chain_explosions,
    _history,
    _peak_velocity,
    _session_low,
    _session_open,
    _session_peak,
    _tier_sticky,
)
from app.models.schemas import Side


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
    return s


def _chain(strike: float, put_ltp: float) -> list[dict]:
    return [{
        "strike_price": strike,
        "put_options": {"ltp": put_ltp, "volume": 8000},
    }]


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_peak_move_boosts_faded_elite_score(mock_settings, _open):
    mock_settings.return_value = _settings()
    boosted = apply_peak_move_score_boost(16.9, 100.0, "ELITE")
    assert boosted >= 38.0


@patch("app.config.get_settings")
def test_effective_min_score_lowers_for_peak_elite(mock_settings):
    mock_settings.return_value = _settings()
    assert effective_explosion_min_score(tier="ELITE", peak_move_pct=80.0) == 38.0
    assert effective_explosion_min_score(tier="ELITE", peak_move_pct=30.0) == 45.0
    assert effective_explosion_min_score(tier="ELITE", peak_move_pct=35.0) == 38.0
    assert effective_explosion_min_score(tier="EXPLODING", peak_move_pct=80.0) == 45.0


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_scan_chain_boosts_score_after_vertical_fade(mock_settings, _open):
    mock_settings.return_value = _settings()
    _history.clear()
    _session_open.clear()
    _session_low.clear()
    _session_peak.clear()
    _tier_sticky.clear()
    _peak_velocity.clear()

    chain = _chain(24000.0, 80.0)
    scan_chain_explosions("NIFTY", chain, spot=24070.0, atm=24100.0)
    chain[0]["put_options"]["ltp"] = 133.0
    events = scan_chain_explosions("NIFTY", chain, spot=24070.0, atm=24100.0)
    puts = [e for e in events if e.side == Side.PUT and e.strike == 24000.0]
    assert puts
    assert puts[0].peak_move_pct >= 35.0
    assert puts[0].explosion_score >= 45.0
