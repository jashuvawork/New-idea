"""Aug27 SENSEX PUT 77200 — shallow OTM ELITE flat→vertical at local base blocked tradeable."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.config import Settings
from app.engines.explosion_detector import (
    ExplosionEvent,
    _shallow_otm_local_base_tradeable,
    event_to_dict,
)
from app.models.schemas import MarketPhase, Side, SymbolSnapshot


def _sensex_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-08-27T10:50:00+05:30",
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=46.0,
        spot=77323.99,
        atmStrike=77300.0,
    )


def _aug27_event(*, lb: float = 8.5) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77200.0,
        premium=56.25 + lb,  # lift off ~56 base
        velocity_3s=1.2,
        velocity_9s=0.8,
        velocity_15s=0.5,
        volume_surge=3.5,
        explosion_score=100.0,
        tier="ELITE",
        reason="flat_then_vertical",
        daily_move_pct=lb,
        peak_move_pct=max(lb, 12.0),
        volume=80_000.0,
        moneyness="OTM",
    )


def _aug27_ict(*, lb: float = 8.5):
    return SimpleNamespace(
        flat_then_vertical=True,
        active=True,
        pattern="flat_then_vertical",
        score=80.0,
        base_relative_move_pct=lb,
        base_premium=56.25,
        session_move_pct=lb,
        displacement=True,
        local_swing_base=True,
        first_lift=False,
        volume_awakening=True,
        reasons=["flat_then_vertical"],
        mega_rip=False,
        premium_fvg=False,
        armed_base_sustained_lift=False,
        armed_base_launch=False,
        elite_base_ready=False,
        v_rip_ready=False,
        building_rip_ready=False,
        base_armed=False,
        armed_base_samples=0,
        armed_base_span_seconds=0,
        armed_base_range_pct=0.0,
        armed_at="",
        armed_base_expires_at="",
        flat_vertical_quality=70.0,
        flat_vertical_grade="A",
    )


@patch("app.config.get_settings")
def test_shallow_otm_local_base_helper_allows_one_step_otm(mock_settings):
    settings = Settings(
        explosion_shallow_otm_history_steps=1,
        explosion_shallow_otm_history_min_volume=25000,
    )
    mock_settings.return_value = settings
    event = _aug27_event()
    ict = _aug27_ict()
    assert _shallow_otm_local_base_tradeable(
        event,
        ict,
        structure_pad=8.5,
        snap=_sensex_snap(),
        settings=settings,
    )


@patch("app.config.get_settings")
def test_shallow_otm_local_base_rejects_deep_otm(mock_settings):
    settings = Settings(
        explosion_shallow_otm_history_steps=1,
        explosion_shallow_otm_history_min_volume=25000,
    )
    mock_settings.return_value = settings
    event = _aug27_event()
    event.strike = 77000.0
    ict = _aug27_ict()
    assert not _shallow_otm_local_base_tradeable(
        event,
        ict,
        structure_pad=8.5,
        snap=_sensex_snap(),
        settings=settings,
    )


@patch("app.engines.ict_breakout_monitor.analyze_explosion_event_ict")
@patch("app.config.get_settings")
def test_event_to_dict_marks_shallow_otm_elite_flat_vertical_tradeable(
    mock_settings,
    mock_ict,
):
    settings = Settings(
        explosion_shallow_otm_history_steps=1,
        explosion_shallow_otm_history_min_volume=25000,
    )
    mock_settings.return_value = settings
    mock_ict.return_value = _aug27_ict(lb=8.5)
    with patch(
        "app.engines.explosion_entry_guards.effective_local_base_move_pct",
        return_value=8.5,
    ), patch(
        "app.engines.explosion_detector.session_low_relative_move_pct",
        return_value=8.5,
    ):
        radar = event_to_dict(_aug27_event(lb=8.5), _sensex_snap())

    assert radar["tier"] == "ELITE"
    assert radar["tradeable"] is True
    assert radar["shallowOtmLocalBaseTradeable"] is True
    assert 2.0 <= radar["localBaseMovePct"] <= 25.0


def _aug27_armed_launch_alert(*, lb: float = 8.5):
    return {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77200.0,
        "premium": 63.75,
        "tier": "ELITE",
        "explosionScore": 100.0,
        "dailyMovePct": lb,
        "peakMovePct": lb,
        "localBaseMovePct": lb,
        "ictBaseRelativeMovePct": lb,
        "tradeable": True,
        "shallowOtmLocalBaseTradeable": True,
        "ictBaseArmed": True,
        "ictArmedBaseLaunch": True,
        "ictArmedBaseSamples": 8,
        "ictArmedBaseSpanSeconds": 163.0,
        "ictArmedBaseRangePct": 3.0,
        "ictFlatThenVertical": True,
        "ictVolumeAwakening": True,
        "volumeAwaken": True,
        "flatVerticalQuality": 70.0,
        "velocity3s": 2.81,
        "velocity9s": 1.0,
    }


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.config.get_settings")
def test_shallow_otm_armed_launch_passes_strict_rank_one(mock_cfg, mock_expiry):
    """Aug27 10:51 — #427 tradeable stamp still blocked strict_rank_one on shallow OTM."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.engines.expiry_day_guards import alert_is_strict_rank_one_launch

    settings = Settings(
        explosion_shallow_otm_history_steps=1,
        explosion_shallow_otm_history_min_volume=25000,
    )
    mock_cfg.return_value = settings
    mock_expiry.return_value = settings
    snap = _sensex_snap()
    snap.tradeQualityScore = 46.0
    alert = _aug27_armed_launch_alert(lb=8.5)
    assert alert_is_strict_rank_one_launch(alert, snap) is True


@patch("app.config.get_settings")
def test_shallow_otm_local_base_waives_expiry_worst_defensive_rip_quality(mock_settings):
    from app.engines.ict_breakout_monitor import _expiry_worst_defensive_rip_allowed

    settings = Settings()
    mock_settings.return_value = settings
    evidence = {
        "shallowOtmLocalBaseTradeable": True,
        "armedBaseLaunch": True,
        "localBaseMovePct": 8.5,
        "tier": "ELITE",
    }
    ok, reason = _expiry_worst_defensive_rip_allowed(
        tier="ELITE",
        quality=70.0,
        score=100.0,
        velocity_3s=2.81,
        settings=settings,
        evidence=evidence,
    )
    assert ok is True
    assert reason == "shallow_otm_local_base_expiry_worst_waive"

