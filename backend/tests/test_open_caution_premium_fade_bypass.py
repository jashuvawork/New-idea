"""Oct29-style exec premium fade false positives during 09:20–09:45 base lifts."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.pad_lane_capture import open_caution_premium_fade_bypass
from app.engines.winner_entry_guards import premium_fading_blocks_entry
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
OPEN_TS = datetime(2026, 10, 29, 9, 35, tzinfo=IST)


def _settings(**overrides):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 999.0
    s.execution_chart_min_premium_momentum_pct = -0.15
    s.open_caution_premium_fade_fill_enabled = True
    s.open_caution_premium_fade_max_drawdown_pct = -2.8
    s.open_caution_premium_fade_max_local_base_pct = 28.0
    s.shallow_otm_local_base_min_move_pct = 2.0
    s.open_caution_premium_fade_min_rank_score = 90.0
    s.open_caution_premium_fade_allow_grade_s = True
    s.open_caution_itm_band_enabled = True
    s.open_caution_sensex_call_max_itm_points = 800.0
    s.open_caution_nifty_put_max_itm_points = 400.0
    s.open_caution_default_max_itm_points = 800.0
    for key, val in overrides.items():
        setattr(s, key, val)
    return s


def _oct29_sensex_call_alert() -> dict:
    return {
        "symbol": "SENSEX",
        "side": "CALL",
        "strike": 73000.0,
        "tier": "ELITE",
        "ictFirstLift": True,
        "ictArmedBaseLaunch": True,
        "momentType": "ict_base_armed",
        "localBaseMovePct": 12.0,
        "ictBaseRelativeMovePct": 12.0,
        "causalRankScore": 92.0,
    }


@patch("app.engines.pad_lane_capture.get_settings")
def test_open_caution_bypass_stamp_in_morning_window(mock_settings):
    mock_settings.return_value = _settings()
    event = SimpleNamespace(tier="ELITE", daily_move_pct=12.0)
    snap = SimpleNamespace(symbol="SENSEX", spot=73500.0, timestamp=OPEN_TS)
    assert open_caution_premium_fade_bypass(
        _oct29_sensex_call_alert(), event, when=OPEN_TS, snap=snap,
    )


@patch("app.engines.pad_lane_capture.get_settings")
def test_open_caution_bypass_idle_after_open_caution(mock_settings):
    mock_settings.return_value = _settings()
    after = datetime(2026, 10, 29, 10, 5, tzinfo=IST)
    assert not open_caution_premium_fade_bypass(
        _oct29_sensex_call_alert(), SimpleNamespace(tier="ELITE"), when=after,
    )


@patch("app.engines.winner_entry_guards.get_settings")
def test_open_caution_fills_through_cold_exec_momentum(mock_guard):
    mock_guard.return_value = _settings()
    event = SimpleNamespace(tier="ELITE", daily_move_pct=12.0)
    blocked, reason = premium_fading_blocks_entry(
        trade_score=100.0,
        premium_momentum_3s=-0.6,
        premium_momentum_5s=-1.1,
        premium_direction="BEARISH",
        explosion_event=event,
        open_caution_bypass=True,
    )
    assert blocked is False
    assert reason == "open_caution_shallow_fade_ok"


@patch("app.engines.winner_entry_guards.get_settings")
def test_open_caution_still_blocks_deep_collapse(mock_guard):
    mock_guard.return_value = _settings()
    event = SimpleNamespace(tier="ELITE", daily_move_pct=12.0)
    blocked, reason = premium_fading_blocks_entry(
        premium_momentum_3s=-3.5,
        premium_momentum_5s=-4.0,
        premium_direction="BEARISH",
        explosion_event=event,
        open_caution_bypass=True,
    )
    assert blocked is True
    assert reason == "premium_fading_at_execution"
