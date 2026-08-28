"""Aug28 SENSEX PUT 77500 — ict_base_armed ELITE at 5.4% lb missed at morning pad."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.early_radar_pad_capture import (
    early_radar_pad_capture_active,
    early_radar_pad_off_low_pct,
    ict_base_armed_prelaunch_pad_lane,
    stamp_early_radar_pad_capture,
)
from app.engines.explosion_entry_guards import (
    detect_fake_explosion_trap,
    immature_explosion_blocked,
    live_explosion_confirmation_blocked,
)
from app.engines.explosion_detector import (
    _open_key,
    _session_low,
    _session_peak,
)
from app.engines.session_mode_feedback import session_peak_late_reentry_blocked
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _sensex_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 8, 28, 11, 16, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=61.0,
        spot=77252.0,
        atmStrike=77300.0,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.03,
            momentum10Pct=-0.02,
            momentum15Pct=-0.01,
        ),
    )


def _aug28_77500_alert(**overrides) -> dict:
    alert = {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77500.0,
        "premium": 362.8,
        "tier": "ELITE",
        "explosionScore": 44.6,
        "dailyMovePct": 68.71,
        "peakMovePct": 68.71,
        "localBaseMovePct": 5.4,
        "ictBaseRelativeMovePct": 5.4,
        "ictBaseArmed": True,
        "ictArmedBaseSamples": 8,
        "ictArmedBaseLaunch": False,
        "ictFirstLift": False,
        "momentType": "ict_base_armed",
        "velocity3s": 0.0,
        "velocity9s": 0.0,
        "volumeAwaken": False,
        "tradeable": True,
    }
    alert.update(overrides)
    return alert


def _seed_77500_session_peak(*, low: float = 330.0, peak: float = 376.1) -> None:
    key = _open_key("SENSEX", 77500.0, Side.PUT)
    _session_low[key] = low
    _session_peak[key] = peak


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_prelaunch_pad_lane_active_despite_high_session_peak(mock_settings):
    mock_settings.return_value = Settings()
    alert = _aug28_77500_alert()
    assert ict_base_armed_prelaunch_pad_lane(alert) is True
    assert early_radar_pad_off_low_pct(alert) == 5.4


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_prelaunch_pad_stamps_early_radar_capture(mock_settings):
    mock_settings.return_value = Settings()
    snap = _sensex_snap()
    alert = _aug28_77500_alert()
    assert early_radar_pad_capture_active(alert, snap) is True
    stamped = dict(alert)
    assert stamp_early_radar_pad_capture(stamped, snap) is True
    assert stamped["earlyRadarPadCapture"] is True


@patch("app.engines.explosion_entry_guards.get_settings")
def test_immature_local_base_waived_for_prelaunch_pad(mock_settings):
    mock_settings.return_value = Settings()
    event = SimpleNamespace(
        daily_move_pct=68.71,
        peak_move_pct=68.71,
        explosion_score=44.6,
        tier="ELITE",
    )
    ict = SimpleNamespace(
        base_armed=True,
        armed_base_launch=False,
        local_swing_base=True,
        flat_then_vertical=False,
        session_move_pct=68.71,
        base_relative_move_pct=5.4,
        v_rip_ready=False,
        volume_awakening=False,
    )
    blocked, reason = immature_explosion_blocked(
        event,
        ict=ict,
        bullish_local_base=False,
    )
    assert blocked is False, reason


def test_late_reentry_allows_ict_base_armed_prelaunch_cold_v3():
    _seed_77500_session_peak()
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
    )
    alert = _aug28_77500_alert()
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="SENSEX",
            side=Side.PUT,
            strike=77500.0,
            premium=362.8,
            velocity_3s=0.0,
            alert=alert,
        )
    assert blocked is False, reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_live_confirmation_waived_for_prelaunch_cold_v3(mock_settings):
    mock_settings.return_value = Settings()
    event = SimpleNamespace(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77500.0,
        tier="ELITE",
        velocity_3s=0.0,
        velocity_9s=0.0,
        explosion_score=44.6,
        daily_move_pct=68.71,
        peak_move_pct=68.71,
        volume_surge=0.0,
    )
    ict = SimpleNamespace(
        base_armed=True,
        armed_base_launch=False,
        active=True,
        flat_then_vertical=False,
        base_relative_move_pct=5.4,
    )
    blocked, reason = live_explosion_confirmation_blocked(event, ict=ict)
    assert blocked is False, reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_fake_trap_post_win_skipped_on_prelaunch_pad(mock_settings):
    mock_settings.return_value = Settings(
        fake_explosion_trap_post_win_velocity_block_enabled=True,
        fake_explosion_trap_post_win_min_velocity_3s=0.0,
        fake_explosion_trap_post_win_midday_min_velocity_3s=1.0,
    )
    snap = _sensex_snap()
    event = SimpleNamespace(
        tier="ELITE",
        velocity_3s=0.0,
        daily_move_pct=68.71,
        peak_move_pct=68.71,
        volume_surge=0.0,
    )
    candidate = SimpleNamespace(
        mode="explosion",
        tier="ELITE",
        side=Side.PUT,
        strike=77500.0,
        score=44.6,
        explosion_event=event,
        alert=_aug28_77500_alert(),
    )
    with patch(
        "app.engines.explosion_entry_guards._post_small_win",
        return_value=(True, {"postWin": True}),
    ):
        blocked, reason, _ = detect_fake_explosion_trap(
            candidate,
            snap,
            state=None,
            ict=SimpleNamespace(base_relative_move_pct=5.4),
        )
    assert blocked is False, reason
