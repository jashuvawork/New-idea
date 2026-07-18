"""Catch flat→vertical PE/CE base rips and trail toward max (12→392 style)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.ict_breakout_monitor import good_day_ict_capture_active, ICTBreakoutSignal
from app.engines.premium_filter import premium_in_band
from app.models.schemas import AutoTraderState, MarketPhase, PaperTrade, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.ict_breakout_monitor_enabled = True
    s.ict_good_day_capture_enabled = True
    s.ict_all_day_capture_enabled = True
    s.ict_all_day_capture_min_score = 30.0
    s.ict_all_day_lot_multiplier = 0.85
    s.ict_good_day_min_score = 35.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.ict_defensive_base_rip_enabled = True
    s.ict_defensive_base_rip_lot_multiplier = 0.55
    s.ict_defensive_base_rip_max_move_pct = 55.0
    s.ict_max_profit_skip_hard_target = True
    s.ict_max_profit_target_points = 180.0
    s.ict_max_profit_trail_keep_ratio = 0.42
    s.ict_max_profit_max_hold_seconds = 1200
    s.ict_mega_rip_trail_arm_multiplier = 2.2
    s.ict_breakout_trail_arm_multiplier = 1.5
    s.ict_mega_rip_no_progress_seconds = 600
    s.ict_breakout_no_progress_seconds = 360
    s.explosion_no_progress_seconds = 150
    s.explosion_no_progress_enabled = True
    s.explosion_no_progress_skip_when_aligned = True
    s.explosion_trail_arm_points = 4.0
    s.explosion_trail_keep_ratio = 0.65
    s.explosion_trail_step_points = 3.5
    s.explosion_trail_tight_arm = 12.0
    s.explosion_trail_tight_points = 5.0
    s.explosion_target_elite = 25.0
    s.explosion_target_standard = 12.0
    s.explosion_micro_target_points = 3.0
    s.explosion_stop_min_hold_seconds = 15
    s.explosion_initial_stop_points = 6.0
    s.emergency_stop_enabled = True
    s.emergency_stop_inr = 18000
    s.runner_trail_keep_ratio = 0.38
    s.runner_micro_giveback_points = 4.0
    s.runner_min_best_points = 5.0
    s.afternoon_capture_exit_max_hold_seconds = 480
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 300.0
    s.explosion_max_premium_inr = 400.0
    s.explosion_cheap_rip_min_premium_inr = 8.0
    s.explosion_cheap_rip_min_peak_pct = 25.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _ict_flat(**kwargs):
    base = dict(
        active=True,
        pattern="flat_then_vertical",
        score=42.0,
        reasons=["early_flat_break", "volume_awakening"],
        flat_then_vertical=True,
        volume_awakening=True,
        displacement=True,
        session_move_pct=40.0,
        velocity_3s=3.5,
        volume_surge=4.0,
    )
    base.update(kwargs)
    return ICTBreakoutSignal(**base)


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("DEFENSIVE", {}))
def test_defensive_day_allows_early_base_rip(mock_mode, mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=50,
    )
    active, meta = good_day_ict_capture_active(
        state, {"SENSEX": snap}, ict=_ict_flat(session_move_pct=40.0),
    )
    assert active is True
    assert meta.get("defensiveBaseRip") is True
    assert meta.get("maxProfitCapture") is True
    assert meta.get("capturePath") == "defensive_base_flat_vertical"
    assert meta.get("lotMultiplier") == 0.55


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("DEFENSIVE", {}))
def test_defensive_blocks_late_mega_chase(mock_mode, mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
    )
    ict = _ict_flat(session_move_pct=120.0, mega_rip=True, pattern="mega_rip")
    active, _ = good_day_ict_capture_active(state, {"SENSEX": snap}, ict=ict)
    assert active is False


@patch("app.engines.premium_filter.get_settings")
def test_cheap_pe_base_premium_allowed(mock_settings):
    mock_settings.return_value = _settings()
    # SENSEX ~12 base breaking to ~16 (+33%)
    assert premium_in_band(16.0, mode="explosion", peak_move_pct=33.0) is True
    assert premium_in_band(10.0, mode="explosion", peak_move_pct=30.0) is True


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_max_profit_skips_tiny_hard_tp(mock_ict, mock_ep):
    s = _settings()
    mock_ep.return_value = s
    mock_ict.return_value = s
    trade = PaperTrade(
        id="t1",
        symbol="SENSEX",
        side=Side.PUT,
        strike=76500.0,
        entryPremium=16.0,
        currentPremium=42.0,
        lots=4,
        openedAt=datetime.now(IST),
        bestPnlPoints=26.0,
        entryContext={
            "maxProfitCapture": True,
            "allDayIctCapture": True,
            "ictFlatThenVertical": True,
            "momentType": "flat_then_vertical",
        },
    )
    reason, _ = evaluate_explosion_exit(
        trade, current_premium=42.0, event_tier="ELITE", lot_multiplier=20,
    )
    # Old path would hit explosion_target_hit at ~25pts — must keep running.
    assert reason != "explosion_target_hit"
    assert reason != "explosion_half_tp_profit_lock"
