"""Early flat→vertical ICT capture — NIFTY 24400 CE 26→70 style moments."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent, _history, _strike_key, event_to_dict
from app.engines.ict_breakout_monitor import (
    analyze_ict_breakout,
    good_day_ict_capture_active,
    late_fade_chase_blocked,
)
from app.models.schemas import AutoTraderState, MarketPhase, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.ict_breakout_monitor_enabled = True
    s.ict_fvg_min_gap_pct = 12.0
    s.ict_flat_base_max_range_pct = 8.0
    s.ict_displacement_min_velocity_3s = 2.2
    s.ict_vertical_min_session_move_pct = 80.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.ict_early_vertical_min_velocity_3s = 2.0
    s.ict_volume_surge_awaken_min = 3.0
    s.ict_mega_rip_min_session_move_pct = 200.0
    s.ict_breakout_min_score = 28.0
    s.ict_fvg_score_bonus = 14.0
    s.ict_flat_vertical_score_bonus = 18.0
    s.ict_early_breakout_score_bonus = 16.0
    s.ict_mega_rip_score_bonus = 22.0
    s.ict_max_rank_bonus = 30.0
    s.ict_good_day_capture_enabled = True
    s.ict_all_day_capture_enabled = True
    s.ict_all_day_capture_min_score = 30.0
    s.ict_all_day_lot_multiplier = 0.85
    s.ict_good_day_min_score = 35.0
    s.ict_good_day_rank_bonus = 18.0
    s.ict_mega_rip_rank_bonus = 25.0
    s.explosion_volume_awaken_min = 25000
    s.ict_late_chase_block_enabled = True
    s.ict_late_chase_min_peak_pct = 120.0
    s.ict_late_chase_max_live_velocity_3s = 0.4
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _seed_24400_ce_base_break() -> None:
    """Flat 25–30 then break to 45 — mid-rip before 80% full vertical."""
    symbol, strike, side = "NIFTY", 24400.0, Side.CALL
    key = _strike_key(strike, side)
    base = datetime.now(IST) - timedelta(seconds=90)
    from collections import deque

    hist = deque(maxlen=40)
    for i, prem in enumerate([26.0, 27.0, 25.5, 26.5, 26.0, 27.5, 26.2, 28.0]):
        hist.append((base + timedelta(seconds=i * 4), prem, 8000))
    for j, prem in enumerate([32.0, 38.0, 45.0]):
        hist.append((base + timedelta(seconds=(8 + j) * 4), prem, 180000))
    _history.setdefault(symbol, {})[key] = hist


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_early_flat_vertical_at_45pct_not_80(mock_settings):
    mock_settings.return_value = _settings()
    _seed_24400_ce_base_break()
    # ~73% from 26→45 — below legacy 80% vertical threshold
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24400.0,
        premium=45.0,
        session_move_pct=45.0,
        peak_move_pct=73.0,
        velocity_3s=3.5,
        volume_surge=4.2,
        volume=180000,
        tier="BUILDING",
        reason="vertical_rip",
    )
    assert ict.active
    assert ict.flat_then_vertical
    assert ict.volume_awakening
    assert ict.pattern == "flat_then_vertical"


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_volume_surge_counts_as_awakening(mock_settings):
    mock_settings.return_value = _settings()
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24400,
        premium=40.0,
        session_move_pct=35.0,
        velocity_3s=2.5,
        volume_surge=4.0,
        volume=1000,  # below absolute volume awaken floor
        tier="EXPLODING",
    )
    assert ict.volume_awakening


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("NORMAL", {}))
def test_all_day_ict_capture_on_normal_mode(mock_mode, mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55,
    )
    from app.engines.ict_breakout_monitor import ICTBreakoutSignal

    ict = ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=42.0,
        reasons=["early_flat_break"],
        flat_then_vertical=True,
        volume_awakening=True,
        displacement=True,
        session_move_pct=55.0,
        velocity_3s=3.2,
        volume_surge=4.0,
    )
    active, meta = good_day_ict_capture_active(
        state, {"NIFTY": snap}, ict=ict,
    )
    assert active
    assert meta.get("allDayIctCapture") is True
    assert meta.get("capturePath") == "all_day_flat_vertical"
    assert meta.get("lotMultiplier") == 0.85


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_late_fade_chase_blocked(mock_settings):
    mock_settings.return_value = _settings()
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24400,
        premium=72.0,
        velocity_3s=0.1,
        velocity_9s=0.2,
        velocity_15s=0.0,
        volume_surge=1.1,
        explosion_score=40.0,
        tier="ELITE",
        reason="faded",
        daily_move_pct=160.0,
        peak_move_pct=170.0,
    )
    blocked, reason = late_fade_chase_blocked(event)
    assert blocked
    assert "late_fade" in reason


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_building_early_break_tradeable(mock_settings):
    mock_settings.return_value = _settings()
    _seed_24400_ce_base_break()
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24400,
        premium=45.0,
        velocity_3s=3.5,
        velocity_9s=4.0,
        velocity_15s=3.0,
        volume_surge=4.2,
        explosion_score=48.0,
        tier="BUILDING",
        reason="vertical_rip",
        daily_move_pct=45.0,
        peak_move_pct=73.0,
    )
    d = event_to_dict(event)
    assert d["tradeable"] is True
    assert d["ictFlatThenVertical"] is True
    assert d["momentType"] == "flat_then_vertical"
