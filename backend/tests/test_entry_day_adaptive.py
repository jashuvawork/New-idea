"""Day-adaptive entry policy — coil-top and cold-base thresholds per day type."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.engines.entry_day_adaptive import resolve_entry_day_policy


def _settings(**overrides):
    s = MagicMock()
    s.entry_day_adaptive_enabled = True
    s.entry_day_worst_coil_top_max_position_frac = 0.35
    s.entry_day_worst_coil_top_min_run_pct = 0.05
    s.entry_day_worst_coil_top_max_run_pct = 0.22
    s.entry_day_worst_building_cold_min_velocity_3s = 2.0
    s.entry_day_worst_cold_base_lot_cap = 2
    s.entry_day_worst_block_building_watch_cold_base = True
    s.entry_day_chop_coil_top_max_position_frac = 0.40
    s.entry_day_chop_coil_top_min_run_pct = 0.06
    s.entry_day_chop_coil_top_max_run_pct = 0.25
    s.entry_day_chop_building_cold_min_velocity_3s = 1.5
    s.entry_day_chop_cold_base_lot_cap = 3
    s.entry_day_chop_block_building_watch_cold_base = True
    s.entry_day_chop_rally_coil_top_max_position_frac = 0.40
    s.entry_day_chop_rally_building_cold_min_velocity_3s = 1.5
    s.entry_day_normal_coil_top_max_position_frac = 0.50
    s.entry_day_normal_coil_top_min_run_pct = 0.06
    s.entry_day_normal_coil_top_max_run_pct = 0.28
    s.entry_day_normal_building_cold_min_velocity_3s = 1.2
    s.entry_day_normal_cold_base_lot_cap = 3
    s.entry_day_good_coil_top_max_position_frac = 0.50
    s.entry_day_good_coil_top_min_run_pct = 0.06
    s.entry_day_good_coil_top_max_run_pct = 0.30
    s.entry_day_good_building_cold_min_velocity_3s = 1.0
    s.entry_day_good_cold_base_lot_cap = 3
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@patch("app.engines.entry_day_adaptive.get_settings")
@patch("app.engines.day_adaptive_engine.classify_day_type")
def test_chop_rally_day_stricter_coil_top(mock_classify, mock_settings):
    mock_settings.return_value = _settings()
    mock_classify.return_value = "CHOP"
    policy = resolve_entry_day_policy(
        day_mode="CHOP + RALLY",
        confidence_tier="ELITE",
    )
    assert policy.day_type == "CHOP"
    assert policy.coil_top_max_position_frac == 0.40
    assert policy.building_cold_base_min_velocity_3s == 1.5
    assert policy.block_building_watch_cold_base is True


@patch("app.engines.entry_day_adaptive.get_settings")
@patch("app.engines.day_adaptive_engine.classify_day_type")
def test_worst_day_tightest_floors(mock_classify, mock_settings):
    mock_settings.return_value = _settings()
    mock_classify.return_value = "WORST"
    policy = resolve_entry_day_policy(day_mode="EXPIRY WORST", confidence_tier="LOW")
    assert policy.coil_top_max_position_frac == 0.35
    assert policy.cold_base_lot_cap == 2
    assert policy.block_building_watch_cold_base is True
    assert policy.building_cold_base_min_velocity_3s == 2.0


@patch("app.engines.entry_day_adaptive.get_settings")
@patch("app.engines.day_adaptive_engine.classify_day_type")
def test_good_day_relaxes_building_cold_velocity(mock_classify, mock_settings):
    mock_settings.return_value = _settings()
    mock_classify.return_value = "GOOD"
    policy = resolve_entry_day_policy(
        day_mode="BULLISH MOMENTUM",
        confidence_tier="HIGH",
    )
    assert policy.coil_top_max_position_frac == 0.50
    assert policy.building_cold_base_min_velocity_3s == 1.0
    assert policy.block_building_watch_cold_base is False


@patch("app.engines.entry_day_adaptive.get_settings")
@patch("app.engines.day_adaptive_engine.classify_day_type")
def test_normal_day_defaults(mock_classify, mock_settings):
    mock_settings.return_value = _settings()
    mock_classify.return_value = "NORMAL"
    policy = resolve_entry_day_policy(day_mode="NORMAL", confidence_tier="MEDIUM")
    assert policy.coil_top_max_position_frac == 0.50
    assert policy.building_cold_base_min_velocity_3s == 1.2
