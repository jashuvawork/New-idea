"""First-lift pad cold explosion score — Aug25 NIFTY PUT 24250 GOOD_MISS fix."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import effective_explosion_min_score


def _settings() -> MagicMock:
    s = MagicMock()
    s.aggressive_min_explosion_score = 45
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_min_score = 38.0
    s.peak_move_explosion_bypass_enabled = True
    s.peak_move_explosion_min_pct = 35.0
    s.peak_move_explosion_min_tier = "ELITE"
    s.peak_move_explosion_score_floor = 38.0
    s.first_lift_pad_explosion_bypass_enabled = True
    s.first_lift_pad_explosion_min_peak_pct = 25.0
    s.first_lift_pad_explosion_min_score = 24.0
    s.first_lift_pad_local_base_min_pct = 2.0
    s.first_lift_pad_local_base_max_pct = 25.0
    return s


@patch("app.config.get_settings")
def test_first_lift_pad_lowers_min_for_exploding_peak_25(mock_settings):
    """24250 profile: EXPLODING, lb=19.2%, peak=28%, score 26 — min should be 24 not 45."""
    mock_settings.return_value = _settings()
    assert (
        effective_explosion_min_score(
            tier="EXPLODING",
            peak_move_pct=28.0,
            daily_move_pct=19.16,
            first_lift_ready=True,
            local_base_move_pct=19.2,
        )
        == 24.0
    )


@patch("app.config.get_settings")
def test_first_lift_pad_does_not_apply_outside_lb_band(mock_settings):
    mock_settings.return_value = _settings()
    assert (
        effective_explosion_min_score(
            tier="EXPLODING",
            peak_move_pct=30.0,
            first_lift_ready=True,
            local_base_move_pct=28.0,
        )
        == 45.0
    )


@patch("app.config.get_settings")
def test_first_lift_pad_does_not_apply_below_peak_threshold(mock_settings):
    mock_settings.return_value = _settings()
    assert (
        effective_explosion_min_score(
            tier="EXPLODING",
            peak_move_pct=22.0,
            first_lift_ready=True,
            local_base_move_pct=18.0,
        )
        == 45.0
    )


@patch("app.config.get_settings")
def test_first_lift_pad_requires_first_lift_ready(mock_settings):
    mock_settings.return_value = _settings()
    assert (
        effective_explosion_min_score(
            tier="EXPLODING",
            peak_move_pct=28.0,
            first_lift_ready=False,
            local_base_move_pct=19.2,
        )
        == 45.0
    )


@patch("app.config.get_settings")
def test_elite_peak_bypass_still_applies_after_pad(mock_settings):
    mock_settings.return_value = _settings()
    assert (
        effective_explosion_min_score(
            tier="ELITE",
            peak_move_pct=40.0,
            first_lift_ready=True,
            local_base_move_pct=20.0,
        )
        == 24.0
    )
