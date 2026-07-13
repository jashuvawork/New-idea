"""Explosion hold — avoid 1pt edge exits when breadth-aligned."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.adaptive_exits import AdaptiveExitPlan, evaluate_adaptive_explosion_exit
from app.engines.edge_engine import check_edge_realtime_exit
from app.engines.explosion_profit import _chart_aligned_with_trade
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _explosion_trade(**ctx) -> PaperTrade:
    base_ctx = {
        "breadth": "BULLISH",
        "entryVelocity3s": 7.0,
        "selectionMode": "explosion",
        "executionChart": {
            "snapshotChart": {"direction": "BULLISH"},
            "indexChart": {"direction": "BEARISH"},
        },
    }
    base_ctx.update(ctx)
    return PaperTrade(
        id="t1",
        symbol="SENSEX",
        side=Side.CALL,
        strike=76800,
        entryPremium=160.0,
        currentPremium=161.0,
        lots=9,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=1.0,
        pnlPoints=1.0,
        entryContext=base_ctx,
    )


@patch("app.engines.edge_engine.get_settings")
@patch("app.engines.bullish_hold.get_settings")
def test_edge_skips_early_exit_on_breadth_aligned_explosion(mock_bh, mock_edge):
    s = MagicMock()
    s.edge_engine_enabled = True
    s.edge_velocity_exhaustion_ratio = 0.35
    s.edge_rsi_overbought_exit = 72.0
    s.edge_macd_fade_exit_enabled = True
    mock_edge.return_value = s
    mock_bh.return_value = MagicMock(bullish_hold_enabled=True)

    trade = _explosion_trade()
    reason, _ = check_edge_realtime_exit(trade, 161.0, None, current_velocity_3s=0.5, lot_multiplier=20)
    assert reason is None


@patch("app.engines.bullish_hold.get_settings")
def test_adaptive_trail_waits_for_5pt_on_breadth_hold(mock_bh):
    mock_bh.return_value = MagicMock(bullish_hold_enabled=True)
    trade = _explosion_trade(bestPnlPoints=3.0)
    plan = AdaptiveExitPlan(
        stopPoints=6.0,
        targetPoints=12.0,
        trailArmPoints=1.2,
        trailKeepRatio=0.88,
    )
    reason, _ = evaluate_adaptive_explosion_exit(
        trade, 162.5, plan, "ELITE", 20, current_velocity_3s=2.0,
    )
    assert reason is None


def test_chart_aligned_uses_snapshot_when_exec_bearish():
    trade = _explosion_trade()
    with patch("app.engines.bullish_hold.get_settings") as mock_bh:
        mock_bh.return_value = MagicMock(bullish_hold_enabled=True)
        assert _chart_aligned_with_trade(trade) is True
