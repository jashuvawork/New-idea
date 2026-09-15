"""Day-adaptive entry policy — unified PR #552–#558 levers per day type."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.engines.entry_day_adaptive import (
    probe_capital_pct_for_timing,
    resolve_entry_day_policy,
)


def _settings(**overrides):
    s = MagicMock()
    s.entry_day_adaptive_enabled = True
    s.bullish_day_floor_relief_enabled = True
    s.probe_entry_max_capital_pct = 0.40
    s.slow_grind_consolidation_base_max_peak_move_pct = 24.0
    s.top_score_per_trade_risk_bypass_min_score = 80.0
    s.entry_day_worst_coil_top_max_position_frac = 0.35
    s.entry_day_worst_coil_top_min_run_pct = 0.05
    s.entry_day_worst_coil_top_max_run_pct = 0.22
    s.entry_day_worst_building_cold_min_velocity_3s = 2.0
    s.entry_day_worst_cold_base_lot_cap = 2
    s.entry_day_worst_block_building_watch_cold_base = True
    s.entry_day_worst_probe_max_capital_pct = 0.25
    s.entry_day_worst_consolidation_max_pad_pct = 22.0
    s.entry_day_worst_top_score_risk_bypass_min_score = 0.0
    s.entry_day_chop_coil_top_max_position_frac = 0.40
    s.entry_day_chop_coil_top_min_run_pct = 0.06
    s.entry_day_chop_coil_top_max_run_pct = 0.25
    s.entry_day_chop_building_cold_min_velocity_3s = 1.5
    s.entry_day_chop_cold_base_lot_cap = 3
    s.entry_day_chop_block_building_watch_cold_base = True
    s.entry_day_chop_probe_max_capital_pct = 0.40
    s.entry_day_chop_consolidation_max_pad_pct = 26.0
    s.entry_day_chop_rally_coil_top_max_position_frac = 0.40
    s.entry_day_chop_rally_building_cold_min_velocity_3s = 1.5
    s.entry_day_chop_rally_consolidation_max_pad_pct = 30.0
    s.entry_day_normal_coil_top_max_position_frac = 0.50
    s.entry_day_normal_coil_top_min_run_pct = 0.06
    s.entry_day_normal_coil_top_max_run_pct = 0.28
    s.entry_day_normal_building_cold_min_velocity_3s = 1.2
    s.entry_day_normal_cold_base_lot_cap = 3
    s.entry_day_normal_probe_max_capital_pct = 0.40
    s.entry_day_normal_consolidation_max_pad_pct = 24.0
    s.entry_day_good_coil_top_max_position_frac = 0.50
    s.entry_day_good_coil_top_min_run_pct = 0.06
    s.entry_day_good_coil_top_max_run_pct = 0.30
    s.entry_day_good_building_cold_min_velocity_3s = 1.0
    s.entry_day_good_cold_base_lot_cap = 3
    s.entry_day_good_probe_max_capital_pct = 0.40
    s.entry_day_good_consolidation_max_pad_pct = 28.0
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
    assert policy.probe_max_capital_pct == 0.40
    assert policy.consolidation_max_pad_pct == 30.0
    assert policy.consolidation_cold_v3_at_base is True
    assert policy.top_score_risk_bypass_min_score == 80.0


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
    assert policy.probe_max_capital_pct == 0.25
    assert policy.consolidation_max_pad_pct == 22.0
    assert policy.consolidation_cold_v3_at_base is False
    assert policy.top_score_risk_bypass_min_score == 0.0


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
    assert policy.consolidation_max_pad_pct == 28.0


@patch("app.engines.entry_day_adaptive.get_settings")
@patch("app.engines.day_adaptive_engine.classify_day_type")
def test_normal_day_defaults(mock_classify, mock_settings):
    mock_settings.return_value = _settings()
    mock_classify.return_value = "NORMAL"
    policy = resolve_entry_day_policy(day_mode="NORMAL", confidence_tier="MEDIUM")
    assert policy.coil_top_max_position_frac == 0.50
    assert policy.probe_max_capital_pct == 0.40
    assert policy.consolidation_max_pad_pct == 24.0


@patch("app.engines.entry_day_adaptive.get_settings")
@patch("app.engines.day_adaptive_engine.classify_day_type")
def test_probe_capital_pct_only_on_cold_timing(mock_classify, mock_settings):
    mock_settings.return_value = _settings()
    mock_classify.return_value = "CHOP"
    policy = resolve_entry_day_policy(day_mode="CHOP + RALLY", confidence_tier="ELITE")
    assert probe_capital_pct_for_timing(policy, {"assessment": "COLD_BASE", "action": "lot_cap"}) == 0.40
    assert probe_capital_pct_for_timing(policy, {"assessment": "GOOD", "action": "allow"}) == 1.0


@patch("app.engines.entry_day_adaptive.get_settings")
@patch("app.engines.day_adaptive_engine.classify_day_type")
def test_policy_serializes_all_levers(mock_classify, mock_settings):
    mock_settings.return_value = _settings()
    mock_classify.return_value = "CHOP"
    policy = resolve_entry_day_policy(day_mode="CHOP + RALLY", confidence_tier="ELITE")
    d = policy.to_dict()
    assert d["probeMaxCapitalPct"] == 0.40
    assert d["consolidationMaxPadPct"] == 30.0
    assert "consolidationColdV3AtBase" in d
    assert "topScoreRiskBypassMinScore" in d
