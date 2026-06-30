"""Chop-day guardrail tests."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.chop_day_guards import (
    apply_tiered_lot_cap,
    is_chop_session,
    neutral_breadth_blocks_entry,
    record_session_trade_close,
    reset_session_guards,
    session_pause_active,
    symbol_rank_adjustment,
)
from app.models.schemas import AutoTraderState, Breadth, Regime, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap(bias: str = "NEUTRAL", regime: Regime = Regime.RANGE_BOUND) -> SymbolSnapshot:
    from app.models.schemas import MarketPhase

    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=regime,
        breadth=Breadth(score=50, bias=bias, aligned=False),
    )


@patch("app.engines.chop_day_guards.get_settings")
def test_chop_session_detected(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    mock_settings.return_value = s
    snaps = {"NIFTY": _snap("NEUTRAL"), "SENSEX": _snap("NEUTRAL")}
    assert is_chop_session(snaps)


@patch("app.engines.chop_day_guards.get_settings")
def test_neutral_breadth_blocks_low_score(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.neutral_breadth_min_score = 60.0
    s.neutral_breadth_explosion_min_score = 55.0
    s.explosion_early_velocity_3s = 3.0
    s.momentum_bypass_velocity_pct = 2.5
    s.momentum_bypass_volume_surge = 1.4
    s.momentum_bypass_explosion_score = 48.0
    mock_settings.return_value = s
    blocked, reason = neutral_breadth_blocks_entry("NEUTRAL", 52.0, velocity_pct=1.0)
    assert blocked
    assert "neutral_breadth" in reason


@patch("app.engines.chop_day_guards.get_settings")
def test_sensex_rank_bonus_on_chop(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.sensex_rank_bonus = 10.0
    s.nifty_rank_penalty_chop = 5.0
    mock_settings.return_value = s
    assert symbol_rank_adjustment("SENSEX", True) == 10.0
    assert symbol_rank_adjustment("NIFTY", True) == -5.0


@patch("app.engines.chop_day_guards.get_settings")
def test_loss_streak_pause(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.loss_streak_pause_count = 3
    s.loss_streak_pause_seconds = 1200
    mock_settings.return_value = s
    reset_session_guards()
    record_session_trade_close(-1000)
    record_session_trade_close(-1000)
    assert not session_pause_active()[0]
    record_session_trade_close(-1000)
    paused, reason = session_pause_active()
    assert paused
    assert "loss_streak_pause" in reason


@patch("app.engines.chop_day_guards.get_settings")
def test_tiered_lot_cap(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.chop_lots_high = 40
    s.chop_lots_mid = 20
    s.chop_lots_min_rank = 48.0
    s.chop_lots_high_min_rank = 55.0
    s.momentum_bypass_velocity_pct = 2.5
    s.momentum_bypass_volume_surge = 1.4
    s.momentum_bypass_explosion_score = 48.0
    mock_settings.return_value = s
    with patch("app.engines.session_timing.in_midday_chop_window", return_value=False):
        assert apply_tiered_lot_cap(100, 58.0, True, "SENSEX") == 100
        assert apply_tiered_lot_cap(100, 52.0, True, "SENSEX") == 100
        assert apply_tiered_lot_cap(100, 45.0, True, "SENSEX") == 0
        assert apply_tiered_lot_cap(100, 52.0, True, "SENSEX", velocity_pct=3.0) == 100


@patch("app.engines.chop_day_guards.get_settings")
def test_day_mode_bearish(mock_settings):
    from app.engines.chop_day_guards import chop_guard_summary
    from app.models.schemas import AutoTraderState

    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.primary_window_start_hour = 10
    s.primary_window_start_minute = 0
    s.daily_max_trades_pre10_chop = 5
    s.daily_max_trades_chop = 20
    s.loss_streak_pause_count = 3
    s.loss_streak_pause_seconds = 1200
    s.momentum_rally_start_hour = 11
    s.momentum_rally_start_minute = 0
    s.momentum_rally_end_hour = 13
    s.momentum_rally_end_minute = 45
    mock_settings.return_value = s

    snaps = {
        "NIFTY": _snap("BEARISH", Regime.TREND_EXPANSION),
        "SENSEX": _snap("BEARISH", Regime.TREND_EXPANSION),
    }
    snaps["NIFTY"].symbol = "NIFTY"
    snaps["SENSEX"].symbol = "SENSEX"
    summary = chop_guard_summary(AutoTraderState(), snaps)
    assert summary["dayMode"] == "BEARISH DAY"
    assert "NIFTY" in summary["symbolBreadth"]
    assert summary["symbolBreadth"]["NIFTY"]["bias"] == "BEARISH"
