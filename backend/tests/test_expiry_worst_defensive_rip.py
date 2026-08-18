"""Block weak defensive/armed base rips on EXPIRY WORST (Aug18 SENSEX 77400 PUT)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent
from app.engines.ict_breakout_monitor import (
    ICTBreakoutSignal,
    _expiry_worst_defensive_rip_allowed,
    _expiry_worst_session,
    first_lift_entry_readiness,
    good_day_ict_capture_active,
)
from app.models.schemas import AutoTraderState, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.ict_breakout_monitor_enabled = True
    s.ict_good_day_capture_enabled = True
    s.ict_all_day_capture_enabled = True
    s.ict_all_day_capture_min_score = 30.0
    s.ict_all_day_lot_multiplier = 0.85
    s.ict_good_day_min_score = 35.0
    s.ict_early_vertical_min_session_move_pct = 12.0
    s.ict_defensive_base_rip_enabled = True
    s.ict_defensive_base_rip_full_lots = True
    s.ict_defensive_base_rip_lot_multiplier = 0.55
    s.ict_defensive_base_rip_max_move_pct = 55.0
    s.ict_defensive_base_rip_tiers_csv = "ELITE,EXPLODING"
    s.ict_defensive_base_rip_full_lots_tiers_csv = "ELITE,EXPLODING"
    s.ict_defensive_base_rip_require_top_quality = True
    s.ict_defensive_base_rip_min_score = 80.0
    s.ict_defensive_base_rip_min_quality = 70.0
    s.ict_defensive_base_rip_min_velocity_3s = 2.5
    s.ict_defensive_base_rip_block_expiry_worst = True
    s.ict_defensive_base_rip_expiry_worst_min_tier = "ELITE"
    s.ict_defensive_base_rip_expiry_worst_min_quality = 85.0
    s.ict_defensive_base_rip_expiry_worst_min_score = 90.0
    s.ict_defensive_base_rip_expiry_worst_min_velocity_3s = 3.0
    s.elite_local_base_max_move_pct = 40.0
    s.explosion_require_chart_align_enabled = False
    s.first_lift_trade_enabled = True
    s.first_lift_trade_min_score = 70.0
    s.first_lift_trade_min_quality = 70.0
    s.first_lift_trade_min_volume_surge = 2.0
    s.first_lift_trade_min_velocity_3s = 2.0
    s.first_lift_trade_min_velocity_9s = 1.5
    s.first_lift_trade_max_move_pct = 25.0
    s.ict_structured_early_min_move_pct = 15.0
    s.ict_armed_base_launch_min_move_pct = 5.0
    s.ict_armed_base_launch_max_move_pct = 12.0
    s.ict_armed_base_launch_min_quality = 70.0
    s.ict_armed_base_launch_min_score = 70.0
    s.ict_armed_base_launch_min_velocity_3s = 2.5
    s.ict_armed_base_launch_min_velocity_9s = 1.75
    s.ict_armed_base_launch_min_absolute_volume = 25000.0
    s.ict_armed_base_min_samples = 6
    s.ict_armed_base_min_span_seconds = 15.0
    s.ict_elite_base_ready_min_quality = 55.0
    s.ict_elite_base_ready_min_score = 45.0
    s.first_lift_option_led_enabled = False
    s.first_lift_trade_min_momentum_shift_pct = 0.03
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77450.0,
        atmStrike=77400.0,
        tradeQualityScore=55,
        spotChart=SpotChart(
            direction="BEARISH",
            timeframe="5m",
            barCount=40,
            momentum5Pct=-0.15,
            momentum15Pct=-0.10,
            trendStrength=60.0,
            emaBias="BEARISH",
            candleBias="BEARISH",
            recommendedSide="PUT",
        ),
    )


def _event(*, tier="EXPLODING", score=71.5, v3=2.4) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77400.0,
        premium=270.0,
        velocity_3s=v3,
        velocity_9s=v3,
        velocity_15s=v3,
        volume_surge=2.5,
        explosion_score=score,
        tier=tier,
        reason="flat_then_vertical",
        daily_move_pct=20.0,
        peak_move_pct=25.0,
        volume=80000,
    )


def _ict(*, quality=64.8, pad=9.4) -> ICTBreakoutSignal:
    return ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=42.0,
        reasons=["armed_base_launch"],
        flat_then_vertical=True,
        volume_awakening=True,
        displacement=True,
        session_move_pct=25.0,
        velocity_3s=2.4,
        volume_surge=2.5,
        base_premium=247.0,
        base_relative_move_pct=pad,
        local_swing_base=True,
        flat_vertical_quality=quality,
        flat_vertical_grade="B",
        armed_base_launch=True,
        first_lift=False,
        armed_base_samples=8,
        armed_base_span_seconds=20.0,
        armed_base_range_pct=2.5,
    )


def test_expiry_worst_session_detects_labels():
    assert _expiry_worst_session(day_mode="EXPIRY WORST") is True
    assert _expiry_worst_session(day_mode="EXPIRY DAY", meta={"dayType": "WORST"}) is True
    assert _expiry_worst_session(day_mode="NORMAL") is False


def test_expiry_worst_bar_rejects_aug18_sensex_style():
    settings = _settings()
    ok, reason = _expiry_worst_defensive_rip_allowed(
        tier="EXPLODING",
        quality=64.8,
        score=71.5,
        velocity_3s=2.4,
        settings=settings,
    )
    assert ok is False
    assert "expiry_worst" in reason


def test_expiry_worst_bar_allows_true_elite():
    settings = _settings()
    ok, reason = _expiry_worst_defensive_rip_allowed(
        tier="ELITE",
        quality=88.0,
        score=95.0,
        velocity_3s=4.0,
        settings=settings,
    )
    assert ok is True
    assert reason == "ok"


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("DEFENSIVE", {"dayMode": "EXPIRY WORST"}))
def test_defensive_capture_blocked_on_expiry_worst(mock_mode, mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    state.dailyStrategy = {"dayMode": "EXPIRY WORST", "dayType": "WORST"}
    snap = _snap()
    event = _event()
    ict = _ict()
    active, meta = good_day_ict_capture_active(
        state,
        {"SENSEX": snap},
        event=event,
        ict=ict,
        day_mode="EXPIRY WORST",
        confidence_tier="HIGH",
    )
    assert active is False
    assert meta.get("expiryWorstDefensiveRipBlocked") is True
    assert "expiry_worst" in str(meta.get("deniedReason") or "")


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.daily_18pct_strategy.get_session_limits", return_value=None)
def test_armed_first_lift_blocked_on_expiry_worst(mock_limits, mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap()
    event = _event()
    ict = _ict()
    ready, reason = first_lift_entry_readiness(
        snap=snap,
        event=event,
        ict=ict,
        day_mode="EXPIRY WORST",
    )
    assert ready is False
    assert "expiry_worst" in reason
