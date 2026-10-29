"""Exec premium fade false positives on local-base lifts (all sessions)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.pad_lane_capture import (
    local_base_first_lift_premium_fade_bypass,
    local_base_first_lift_premium_fade_stamp_ok,
)
from app.engines.winner_entry_guards import premium_fading_blocks_entry

IST = ZoneInfo("Asia/Kolkata")
OPEN_TS = datetime(2026, 10, 29, 9, 35, tzinfo=IST)
AFTERNOON_TS = datetime(2026, 10, 29, 14, 20, tzinfo=IST)


def _settings(**overrides):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 999.0
    s.execution_chart_min_premium_momentum_pct = -0.15
    s.local_base_first_lift_premium_fade_fill_enabled = True
    s.local_base_first_lift_premium_fade_max_drawdown_pct = -2.8
    s.local_base_first_lift_premium_fade_max_local_base_pct = 28.0
    s.shallow_otm_local_base_min_move_pct = 2.0
    for key, val in overrides.items():
        setattr(s, key, val)
    return s


def _sensex_call_alert() -> dict:
    return {
        "symbol": "SENSEX",
        "side": "CALL",
        "tier": "ELITE",
        "ictFirstLift": True,
        "ictArmedBaseLaunch": True,
        "momentType": "ict_base_armed",
        "localBaseMovePct": 12.0,
        "ictBaseRelativeMovePct": 12.0,
    }


@patch("app.engines.pad_lane_capture.get_settings")
def test_local_base_stamp_ok(mock_settings):
    mock_settings.return_value = _settings()
    event = SimpleNamespace(tier="ELITE", daily_move_pct=12.0)
    assert local_base_first_lift_premium_fade_stamp_ok(_sensex_call_alert(), event)


@patch("app.engines.pad_lane_capture.get_settings")
def test_local_base_bypass_morning_and_afternoon(mock_settings):
    mock_settings.return_value = _settings()
    event = SimpleNamespace(tier="ELITE", daily_move_pct=12.0)
    assert local_base_first_lift_premium_fade_bypass(
        _sensex_call_alert(), event, when=OPEN_TS,
    )
    assert local_base_first_lift_premium_fade_bypass(
        _sensex_call_alert(), event, when=AFTERNOON_TS,
    )


@patch("app.engines.winner_entry_guards.get_settings")
def test_local_base_fills_through_cold_exec_momentum(mock_guard):
    mock_guard.return_value = _settings()
    event = SimpleNamespace(tier="ELITE", daily_move_pct=12.0)
    blocked, reason = premium_fading_blocks_entry(
        trade_score=100.0,
        premium_momentum_3s=-0.6,
        premium_momentum_5s=-1.1,
        premium_direction="BEARISH",
        explosion_event=event,
        local_base_first_lift_bypass=True,
    )
    assert blocked is False
    assert reason == "local_base_first_lift_shallow_fade_ok"


@patch("app.engines.winner_entry_guards.get_settings")
def test_local_base_still_blocks_deep_collapse(mock_guard):
    mock_guard.return_value = _settings()
    event = SimpleNamespace(tier="ELITE", daily_move_pct=12.0)
    blocked, reason = premium_fading_blocks_entry(
        premium_momentum_3s=-3.5,
        premium_momentum_5s=-4.0,
        premium_direction="BEARISH",
        explosion_event=event,
        local_base_first_lift_bypass=True,
    )
    assert blocked is True
    assert reason == "premium_fading_at_execution"
