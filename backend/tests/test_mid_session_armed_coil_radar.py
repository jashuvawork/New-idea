"""Mid-session flat armed-base coil must stay on radar (CE/PE symmetric)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import mid_session_armed_coil_radar_retain


def test_mid_session_armed_coil_retain_sensex_after_peak_pullback():
    settings = MagicMock()
    settings.mid_session_armed_coil_radar_enabled = True
    settings.mid_session_armed_coil_min_samples = 6
    settings.mid_session_armed_coil_max_armed_range_pct = 8.0
    settings.mid_session_armed_coil_min_peak_pullback_pct = 22.0
    settings.mid_session_armed_coil_max_local_move_pct = 18.0
    settings.building_armed_prelaunch_min_base_rel_pct = 5.0
    with patch(
        "app.engines.premium_filter.premium_in_band",
        return_value=True,
    ):
        ok = mid_session_armed_coil_radar_retain(
            symbol="SENSEX",
            premium=400.0,
            armed_samples=6,
            armed_range_pct=4.5,
            base_relative_move_pct=7.5,
            session_peak=630.0,
            settings=settings,
        )
    assert ok is True


def test_mid_session_armed_coil_retain_put_mirror_nifty():
    settings = MagicMock()
    settings.mid_session_armed_coil_radar_enabled = True
    settings.mid_session_armed_coil_min_samples = 6
    settings.mid_session_armed_coil_max_armed_range_pct = 8.0
    settings.mid_session_armed_coil_min_peak_pullback_pct = 22.0
    settings.mid_session_armed_coil_max_local_move_pct = 18.0
    settings.building_armed_prelaunch_min_base_rel_pct = 5.0
    with patch(
        "app.engines.premium_filter.premium_in_band",
        return_value=True,
    ):
        ok = mid_session_armed_coil_radar_retain(
            symbol="NIFTY",
            premium=95.0,
            armed_samples=6,
            armed_range_pct=3.0,
            base_relative_move_pct=9.0,
            session_peak=140.0,
            settings=settings,
        )
    assert ok is True


def test_mid_session_armed_coil_config_defaults():
    from app.config import Settings

    s = Settings()
    assert bool(getattr(s, "mid_session_armed_coil_radar_enabled", True)) is True
    assert int(getattr(s, "mid_session_armed_coil_min_samples", 6)) == 6


def test_detection_milestone_on_ict_base_armed_transition():
    from app.services.radar_archive import _should_append_detection_milestone

    prior = {
        "milestones": [
            {
                "seenAt": "2026-11-16T11:40:00+05:30",
                "ictBaseArmed": False,
                "momentType": "WATCH",
            }
        ]
    }
    alert = {
        "ictBaseArmed": True,
        "momentType": "ict_base_armed",
        "tradeable": True,
        "tier": "BUILDING",
    }
    assert _should_append_detection_milestone(
        prior,
        alert,
        "2026-11-16T11:47:00+05:30",
    )