"""Adjacent ITM continuation after a profitable peak-keep exit on the parent strike."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.session_mode_feedback import (
    adjacent_strike_post_peak_keep_continuation,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _peak_keep_win(
    *,
    side: Side = Side.CALL,
    strike: float = 22700.0,
    symbol: str = "NIFTY",
    pnl_inr: float = 19000.0,
) -> PaperTrade:
    closed_at = datetime.now(IST) - timedelta(minutes=20)
    return PaperTrade(
        id="peak-keep-win",
        symbol=symbol,
        side=side,
        strike=strike,
        entryPremium=248.0,
        currentPremium=276.0,
        lots=11,
        openedAt=closed_at - timedelta(minutes=20),
        closedAt=closed_at,
        status="CLOSED",
        exitReason="explosion_profit_ladder_peak_keep",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=pnl_inr,
        entryContext={"selectionMode": "explosion"},
    )


def _state(*trades: PaperTrade) -> AutoTraderState:
    return AutoTraderState(closedPaperTrades=list(trades))


def _call(**kwargs):
    settings = kwargs.pop("settings", Settings())
    with patch("app.engines.session_mode_feedback.get_settings", return_value=settings):
        return adjacent_strike_post_peak_keep_continuation(**kwargs)


def test_nifty_call_22650_continuation_after_22700_peak_keep_win():
    ok, meta = _call(
        state=_state(_peak_keep_win()),
        symbol="NIFTY",
        side=Side.CALL,
        strike=22650.0,
        premium=310.0,
        velocity_3s=0.8,
        alert={
            "tier": "EXPLODING",
            "radarExplosionScore": 56.0,
            "premiumMomentum5Pct": 1.2,
        },
    )
    assert ok is True
    assert meta["reason"] == "adjacent_peak_keep_continuation"
    assert meta["parentStrike"] == 22700.0
    assert meta["candidateStrike"] == 22650.0


def test_put_symmetry_parent_strike_step():
    win = _peak_keep_win(side=Side.PUT, strike=22800.0, symbol="NIFTY")
    ok, meta = _call(
        state=_state(win),
        symbol="NIFTY",
        side=Side.PUT,
        strike=22850.0,
        premium=120.0,
        velocity_3s=0.9,
        alert={"tier": "BUILDING", "explosionScore": 48.0, "premiumMomentum5Pct": 0.8},
    )
    assert ok is True
    assert meta["parentStrike"] == 22800.0


def test_blocks_when_parent_exit_was_not_peak_keep():
    win = _peak_keep_win()
    win.exitReason = "explosion_stage_trail"
    ok, meta = _call(
        state=_state(win),
        symbol="NIFTY",
        side=Side.CALL,
        strike=22650.0,
        premium=310.0,
        velocity_3s=0.8,
        alert={"tier": "EXPLODING", "radarExplosionScore": 56.0},
    )
    assert ok is False
    assert meta["reason"] == "parent_not_peak_keep_exit"


def test_blocks_second_adjacent_leg():
    parent = _peak_keep_win()
    follow = PaperTrade(
        id="adj-leg",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22650.0,
        entryPremium=310.0,
        currentPremium=320.0,
        lots=11,
        openedAt=parent.closedAt + timedelta(minutes=5),
        status="OPEN",
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"selectionMode": "explosion"},
    )
    ok, meta = _call(
        state=_state(parent, follow),
        symbol="NIFTY",
        side=Side.CALL,
        strike=22650.0,
        premium=330.0,
        velocity_3s=0.8,
        alert={"tier": "EXPLODING", "radarExplosionScore": 56.0},
    )
    assert ok is False
    assert meta["reason"] == "adjacent_continuation_already_taken"


def test_elite_entry_waives_score_floor_for_adjacent_continuation():
    from app.engines.elite_score_engine import elite_entry_allowed

    state = _state(_peak_keep_win())
    evidence = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 22650.0,
        "premium": 310.0,
        "velocity3s": 0.8,
        "tier": "EXPLODING",
        "explosionScore": 56.0,
        "mode": "explosion",
        "localBaseMovePct": 18.0,
        "timingAssessment": "GOOD",
        "timingAction": "allow",
        "orderflowPositive": True,
    }
    ranking = {"grade": "A", "rankScore": 72.0, "side": "CALL"}
    with patch(
        "app.engines.session_mode_feedback.adjacent_strike_post_peak_keep_continuation",
        return_value=(
            True,
            {"adjacentStrikePeakKeepContinuation": True, "reason": "adjacent_peak_keep_continuation"},
        ),
    ):
        ok, reason, assessment = elite_entry_allowed(
            evidence,
            ranking,
            state=state,
            day_mode="EXPIRY DAY",
        )
    assert assessment.get("adjacentStrikePeakKeepContinuation") is True
    assert ok or reason != "elite_score_below_78"
