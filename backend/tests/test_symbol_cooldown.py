"""Symbol cooldown and calibration tests."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.daily_profit_strategy import DailyCalibration
from app.engines.symbol_cooldown import (
    entry_score_penalty,
    record_symbol_result,
    reset_symbol_cooldowns,
    symbol_in_cooldown,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _trade(pnl: float, side: Side = Side.CALL) -> PaperTrade:
    return PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=side,
        strike=24000,
        entryPremium=50,
        lots=10,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.SCALP,
        pnlInr=pnl,
    )


def test_symbol_cooldown_after_loss():
    reset_symbol_cooldowns()
    record_symbol_result("NIFTY", -1000, "simple_emergency_inr_stop")
    blocked, reason = symbol_in_cooldown("NIFTY")
    assert blocked
    assert "symbol_cooldown" in reason


def test_score_penalty_after_loss_streak():
    reset_symbol_cooldowns()
    record_symbol_result("NIFTY", -1000, "adaptive_sl")
    assert entry_score_penalty("NIFTY") >= 6


def test_calibration_needs_five_losses_to_block():
    cal = DailyCalibration()
    for _ in range(4):
        cal.record_trade(_trade(-100))
    assert not cal.get_blocks()["CALL"]
    cal.record_trade(_trade(-100))
    assert cal.get_blocks()["CALL"]


def test_win_eases_calibration_loss_pressure():
    cal = DailyCalibration()
    for _ in range(4):
        cal.record_trade(_trade(-100))
    cal.record_trade(_trade(500))
    assert not cal.get_blocks()["CALL"]
