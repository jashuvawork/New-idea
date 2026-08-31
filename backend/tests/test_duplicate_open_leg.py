"""Block re-opening the same symbol+side+strike while a leg is still open."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.risk_engine import RiskEngine
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.aggressive_lot_sizing = True
    s.aggressive_max_open_scalps = 2
    s.swing_max_open = 1
    s.per_trade_capital_pct = 0.95
    s.max_risk_per_trade_inr = 20_000
    s.swing_max_loss_inr = 20_000
    s.emergency_stop_enabled = False
    s.daily_loss_stop_inr = 0
    s.block_duplicate_open_leg = True
    s.enable_live_trading = False
    s.live_hold_to_structural_sl = False
    s.ftv_ranked_allocation_enabled = True
    s.ftv_allocation_max_positions = 3
    s.ftv_allocation_max_same_side = 2
    return s


@patch("app.engines.risk_engine.get_capital_snapshot")
@patch("app.engines.risk_engine.get_settings")
def test_blocks_same_leg_while_open(mock_settings, mock_capital):
    mock_settings.return_value = _settings()
    cap = MagicMock()
    cap.availableMarginInr = 500_000
    cap.perTradeCapitalInr = 200_000
    mock_capital.return_value = cap

    open_trade = PaperTrade(
        id="open1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24100.0,
        entryPremium=180.0,
        currentPremium=175.0,
        lots=16,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.SCALP,
    )
    state = AutoTraderState(running=True, openPaperTrades=[open_trade])
    engine = RiskEngine()

    ok, reason = engine.check_new_entry(
        state, "NIFTY", Side.CALL, 16, 181.0, lot_multiplier=65, strike=24100.0,
    )
    assert not ok
    assert reason == "same_leg_already_open"


@patch("app.engines.risk_engine.get_capital_snapshot")
@patch("app.engines.risk_engine.get_settings")
def test_risk_check_uses_actual_planned_stop(mock_settings, mock_capital):
    mock_settings.return_value = _settings()
    cap = MagicMock()
    cap.availableMarginInr = 500_000
    cap.perTradeCapitalInr = 200_000
    mock_capital.return_value = cap
    engine = RiskEngine()

    ok, reason = engine.check_new_entry(
        AutoTraderState(running=True),
        "NIFTY",
        Side.CALL,
        50,
        50,
        lot_multiplier=65,
        strategy_type=StrategyType.SCALP,
        strike=24_500,
        stop_points=10,
    )

    assert not ok
    assert reason == "per_trade_risk_exceeded"
