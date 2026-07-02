"""Instrument-level cooldown — blocks same strike re-entry churn."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.instrument_cooldown import (
    instrument_daily_cap_reached,
    instrument_in_cooldown,
    record_instrument_close,
    record_instrument_entry,
    reset_instrument_cooldowns,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    from unittest.mock import MagicMock
    s = MagicMock()
    s.instrument_loss_cooldown_seconds = 300
    s.instrument_micro_win_cooldown_seconds = 180
    s.instrument_win_cooldown_seconds = 90
    s.instrument_max_entries_per_day = 3
    return s


@patch("app.engines.instrument_cooldown.get_settings")
def test_loss_blocks_same_strike_reentry(mock_settings):
    mock_settings.return_value = _settings()
    reset_instrument_cooldowns()
    record_instrument_close("NIFTY", Side.CALL, 23900, -5000, "simple_stop_loss")
    blocked, reason = instrument_in_cooldown("NIFTY", Side.CALL, 23900)
    assert blocked
    assert "instrument_cooldown" in reason
    blocked, _ = instrument_in_cooldown("NIFTY", Side.PUT, 23900)
    assert not blocked


@patch("app.engines.instrument_cooldown.get_settings")
def test_micro_win_cooldown_blocks_immediate_reentry(mock_settings):
    mock_settings.return_value = _settings()
    reset_instrument_cooldowns()
    record_instrument_close("NIFTY", Side.CALL, 23900, 4000, "simple_micro_profit_lock")
    blocked, _ = instrument_in_cooldown("NIFTY", Side.CALL, 23900)
    assert blocked


@patch("app.engines.instrument_cooldown.get_settings")
def test_daily_cap_limits_same_instrument_entries(mock_settings):
    mock_settings.return_value = _settings()
    reset_instrument_cooldowns()
    for _ in range(3):
        record_instrument_entry("NIFTY", Side.CALL, 23900)
    assert instrument_daily_cap_reached("NIFTY", Side.CALL, 23900)


@patch("app.engines.simple_profit.get_settings")
def test_counter_breadth_call_blocked(mock_settings):
    from app.engines.simple_profit import check_entry_gate
    from app.models.schemas import Breadth, SuggestedTrade, StrategyType

    s = mock_settings.return_value
    s.aggressive_lot_sizing = True
    s.aggressive_min_tqs = 50
    s.enhanced_velocity_threshold = 1.2
    s.midday_chop_block_scalps = False
    s.neutral_breadth_min_score = 60
    s.counter_breadth_min_score = 70

    trade = SuggestedTrade(
        id="x", symbol="NIFTY", side=Side.CALL, strike=23900,
        lastPremium=80.0, tqs=39, confidence=62, strategyType=StrategyType.SCALP,
    )
    breadth = Breadth(bias="BEARISH", score=40, aligned=False)
    passed, reason = check_entry_gate(trade, breadth, 39, 2.0, False)
    assert not passed
    assert reason.startswith("directional_") or reason == "breadth_counter_trend"
