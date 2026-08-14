"""First lift off the lowest flat→vertical local base — appear at ~15%, not chase."""

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import _history, _strike_key
from app.engines.ict_breakout_monitor import (
    _detect_flat_base,
    analyze_ict_breakout,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.ict_breakout_monitor_enabled = True
    s.ict_fvg_min_gap_pct = 12.0
    s.ict_flat_base_max_range_pct = 8.0
    s.ict_flat_base_use_lowest = True
    s.ict_displacement_min_velocity_3s = 2.2
    s.ict_vertical_min_session_move_pct = 80.0
    s.ict_early_vertical_min_session_move_pct = 12.0
    s.ict_early_vertical_min_velocity_3s = 2.0
    s.ict_volume_surge_awaken_min = 2.0
    s.ict_mega_rip_min_session_move_pct = 200.0
    s.ict_breakout_min_score = 28.0
    s.ict_fvg_score_bonus = 14.0
    s.ict_flat_vertical_score_bonus = 18.0
    s.ict_early_breakout_score_bonus = 16.0
    s.ict_mega_rip_score_bonus = 22.0
    s.ict_max_rank_bonus = 30.0
    s.explosion_volume_awaken_min = 25000
    s.ict_structured_early_min_move_pct = 15.0
    s.ict_structured_early_max_move_pct = 65.0
    s.elite_local_base_max_move_pct = 40.0
    s.ict_first_lift_appear_enabled = True
    s.ict_first_lift_min_velocity_3s = 1.2
    s.session_move_max_credible_pct = 500.0
    s.explosion_immature_min_session_move_pct = 28.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _seed_flat_then_lift(*, lift_premium: float) -> None:
    """Flat trough at 89–92 then first lift — true low is 89, not the avg (~90.5)."""
    symbol, strike, side = "NIFTY", 24350.0, Side.CALL
    key = _strike_key(strike, side)
    base = datetime.now(IST) - timedelta(seconds=120)
    hist = deque(maxlen=40)
    for i, prem in enumerate([91.0, 89.0, 90.5, 89.5, 92.0, 90.0, 91.5, 89.0]):
        hist.append((base + timedelta(seconds=i * 5), prem, 12000))
    hist.append((base + timedelta(seconds=45), lift_premium, 160000))
    _history.setdefault(symbol, {})[key] = hist


def test_flat_base_uses_lowest_premium_not_average():
    settings = _settings()
    base_t = datetime.now(IST)
    history = [
        (base_t + timedelta(seconds=i), p, 1000.0)
        for i, p in enumerate([91.0, 89.0, 90.5, 89.5, 92.0, 90.0, 91.5, 89.0, 95.0, 102.0])
    ]
    flat, _dev, level = _detect_flat_base(history, settings)
    assert flat is True
    assert level == 89.0  # trough, not ~90.5 avg


def test_flat_base_can_use_average_when_disabled():
    settings = _settings(ict_flat_base_use_lowest=False)
    base_t = datetime.now(IST)
    history = [
        (base_t + timedelta(seconds=i), p, 1000.0)
        for i, p in enumerate([91.0, 89.0, 90.5, 89.5, 92.0, 90.0, 91.5, 89.0, 95.0, 102.0])
    ]
    flat, _dev, level = _detect_flat_base(history, settings)
    assert flat is True
    assert level > 89.0


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_first_lift_appears_at_15pct_off_lowest_base(mock_settings):
    mock_settings.return_value = _settings()
    # 89 → 102.35 ≈ 15% off the trough
    _seed_flat_then_lift(lift_premium=102.35)
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24350.0,
        premium=102.35,
        session_move_pct=15.0,
        peak_move_pct=15.0,
        velocity_3s=2.4,
        volume_surge=3.5,
        volume=160000,
        tier="BUILDING",
        reason="volAwaken",
    )
    assert ict.base_premium == 89.0
    assert 14.0 <= ict.base_relative_move_pct <= 16.5
    assert ict.first_lift is True
    assert ict.flat_then_vertical is True
    assert ict.active is True
    assert any("first_lift_local_base" in r for r in ict.reasons)


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_chase_past_40pct_is_not_first_lift(mock_settings):
    mock_settings.return_value = _settings()
    # 89 → 131 ≈ 47% — Aug14-style chase print
    _seed_flat_then_lift(lift_premium=131.0)
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24350.0,
        premium=131.0,
        session_move_pct=47.0,
        peak_move_pct=47.0,
        velocity_3s=0.2,
        volume_surge=2.0,
        volume=160000,
        tier="ELITE",
        reason="volAwaken",
    )
    assert ict.base_premium == 89.0
    assert ict.base_relative_move_pct >= 40.0
    assert ict.first_lift is False
