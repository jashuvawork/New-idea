"""Faded vertical rip caution exit — explosion trades only."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_entry_guards import (
    faded_rip_no_green_exit_reason,
    is_faded_rip_caution_trade,
)
from app.engines.explosion_profit import evaluate_explosion_exit
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings() -> MagicMock:
    s = MagicMock()
    s.explosion_faded_rip_no_green_exit_enabled = True
    s.explosion_faded_rip_no_green_seconds = 60
    s.explosion_faded_rip_min_green_points = 0.5
    s.emergency_stop_enabled = False
    s.explosion_stop_min_hold_seconds = 15
    s.explosion_no_progress_enabled = True
    s.explosion_no_progress_skip_when_aligned = True
    s.explosion_no_progress_aligned_seconds = 420
    s.explosion_no_progress_seconds = 150
    s.explosion_target_standard = 12.0
    s.explosion_trail_arm_points = 4.0
    s.runner_trail_keep_ratio = 0.38
    s.runner_min_best_points = 5.0
    s.runner_micro_giveback_points = 4.0
    s.all_day_min_chart_confidence = 62.0
    s.afternoon_capture_exit_max_hold_seconds = 600
    s.chart_confidence_half_tp_giveback_ratio = 0.40
    return s


def _explosion_trade(*, faded: bool = True) -> PaperTrade:
    ctx = {
        "selectionMode": "explosion",
        "explosionTier": "ELITE",
        "selectionScore": 120.0,
    }
    if faded:
        ctx["fadedRipCaution"] = True
        ctx["fadedVerticalRip"] = True
    return PaperTrade(
        id="t1",
        symbol="SENSEX",
        side=Side.CALL,
        strike=77600.0,
        entryPremium=41.0,
        currentPremium=35.0,
        lots=8,
        pnlInr=-960.0,
        pnlPoints=-6.0,
        openedAt=datetime.now(IST) - timedelta(seconds=75),
        status="OPEN",
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=0.0,
        entryContext=ctx,
    )


def test_is_faded_rip_caution_trade_explosion_only():
    assert is_faded_rip_caution_trade(_explosion_trade()) is True
    scalp = _explosion_trade()
    scalp.strategyType = StrategyType.SCALP
    scalp.entryContext["selectionMode"] = "scalp"
    assert is_faded_rip_caution_trade(scalp) is False


@patch("app.config.get_settings")
def test_faded_rip_no_green_exit_after_60s(mock_settings):
    mock_settings.return_value = _settings()
    trade = _explosion_trade()
    reason = faded_rip_no_green_exit_reason(trade, hold_seconds=65, best_points=0.0)
    assert reason == "explosion_faded_rip_no_green"


@patch("app.config.get_settings")
def test_faded_rip_kept_when_went_green(mock_settings):
    mock_settings.return_value = _settings()
    trade = _explosion_trade()
    reason = faded_rip_no_green_exit_reason(trade, hold_seconds=90, best_points=1.2)
    assert reason is None


@patch("app.engines.explosion_profit._hold_seconds", return_value=70)
@patch("app.config.get_settings")
def test_evaluate_explosion_exit_faded_rip_no_green(mock_settings, _hold):
    mock_settings.return_value = _settings()
    trade = _explosion_trade()
    reason, pnl = evaluate_explosion_exit(trade, 34.0, "ELITE", lot_multiplier=20)
    assert reason == "explosion_faded_rip_no_green"
    assert pnl < 0
