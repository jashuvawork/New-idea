"""Session mode PF feedback + size-until-first-green."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.pretrade_validator import TradeRecord
from app.engines.session_mode_feedback import (
    cap_lots_until_first_green,
    compute_mode_stats,
    mode_session_rank_bonus,
    session_has_green_explosion,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.session_mode_feedback_enabled = True
    s.session_mode_feedback_min_trades = 2
    s.edge_session_pf_target = 2.5
    s.size_until_first_green_enabled = True
    s.size_until_first_green_lot_cap = 6
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_mode_stats_and_bonus_demotes_bleeding_explosion():
    trades = [
        TradeRecord("NIFTY", "CALL", -18000, mode="explosion", best_pnl_points=0),
        TradeRecord("NIFTY", "CALL", -34000, mode="quick_sideways", best_pnl_points=0),
        TradeRecord("NIFTY", "PUT", -5000, mode="quick_sideways", best_pnl_points=0),
        TradeRecord("NIFTY", "CALL", -2000, mode="explosion", best_pnl_points=0),
        TradeRecord("SENSEX", "CALL", 800, mode="explosion", best_pnl_points=20),
    ]
    stats = compute_mode_stats(trades)
    assert stats["explosion"].trades == 3
    assert stats["quick_sideways"].net_pnl_inr < 0
    with patch("app.engines.session_mode_feedback.get_settings", return_value=_settings()):
        # quick bled hard → demote
        assert mode_session_rank_bonus("quick_sideways", stats) < 0
        # explosion mixed but net negative with losses → demote or small
        exp_bonus = mode_session_rank_bonus("explosion", stats)
        assert exp_bonus <= 0


def test_mode_bonus_promotes_winning_mode():
    trades = [
        TradeRecord("NIFTY", "CALL", 5000, mode="scalp", best_pnl_points=10),
        TradeRecord("NIFTY", "CALL", 8000, mode="scalp", best_pnl_points=15),
        TradeRecord("NIFTY", "PUT", -500, mode="scalp", best_pnl_points=2),
    ]
    stats = compute_mode_stats(trades)
    with patch("app.engines.session_mode_feedback.get_settings", return_value=_settings()):
        assert mode_session_rank_bonus("scalp", stats) > 0


def test_size_until_first_green_caps_before_proof():
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="a",
            symbol="NIFTY",
            side=Side.CALL,
            strike=24300,
            entryPremium=50,
            currentPremium=45,
            lots=5,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
            pnlInr=-2000,
            bestPnlPoints=0,
            entryContext={"selectionMode": "explosion"},
        )
    ]
    with patch("app.engines.session_mode_feedback.get_settings", return_value=_settings()):
        assert session_has_green_explosion(state) is False
        assert cap_lots_until_first_green(49, state, mode="explosion") == 6


def test_size_until_first_green_allows_after_proof():
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="b",
            symbol="SENSEX",
            side=Side.CALL,
            strike=78100,
            entryPremium=100,
            currentPremium=110,
            lots=2,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
            pnlInr=800,
            bestPnlPoints=20,
            entryContext={"selectionMode": "explosion"},
        )
    ]
    with patch("app.engines.session_mode_feedback.get_settings", return_value=_settings()):
        assert session_has_green_explosion(state) is True
        assert cap_lots_until_first_green(49, state, mode="explosion") == 49
