"""Risk guardrails: never-green cut, hard per-trade ₹ cap, whipsaw flip cap.

Aug6 SENSEX 78800 PE (never-green ELITE, 27 lots, −₹20k) and Jul30 (90-lot ELITE,
−₹86k) motivate bounding the downside on the trades that are wrong from entry.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.session_mode_feedback import cap_opposite_side_flip_after_win
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _trade(entry, cur, *, best=0.0, lots=10, hold_s=60):
    return PaperTrade(
        id="t", symbol="SENSEX", side=Side.PUT, strike=78800.0,
        entryPremium=entry, currentPremium=cur, lots=lots,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=hold_s),
        bestPnlPoints=best,
    )


def test_never_green_stop_cuts_faster():
    """Never printed green (best=0) and down past the floor (346×6%≈21pt) → never-green cut.
    Aug6 78800 PE ran to −37pt; this cuts it near −21."""
    reason, _ = evaluate_explosion_exit(_trade(346.0, 320.0, best=0.0, lots=27), 320.0, "ELITE", 20)
    assert reason == "explosion_never_green_stop"


def test_never_green_holds_if_within_floor():
    """Down but within the never-green floor (−5pt) → not yet cut by this rule."""
    reason, _ = evaluate_explosion_exit(_trade(346.0, 341.0, best=0.0, lots=1), 341.0, "ELITE", 20)
    assert reason != "explosion_never_green_stop"


def test_never_green_skipped_once_green_printed():
    """A trade that DID print green (best>0) is not subject to the never-green cut."""
    reason, _ = evaluate_explosion_exit(_trade(346.0, 330.0, best=6.0, lots=1), 330.0, "ELITE", 20)
    assert reason != "explosion_never_green_stop"


def test_hard_per_trade_risk_cap():
    """Loss beyond the hard ₹ cap exits regardless of lots/stop width (best>0 so the
    never-green rule doesn't preempt; small point loss × big lots → big ₹ loss)."""
    # −5pt × 200 lots × 20 mult = −₹20,000 (> ₹12k cap)
    reason, pnl = evaluate_explosion_exit(
        _trade(500.0, 495.0, best=3.0, lots=200), 495.0, "ELITE", 20,
    )
    assert reason == "explosion_per_trade_risk_cap"
    assert pnl <= -12000


def _closed(side, pnl, symbol="SENSEX", mins_ago=10):
    return PaperTrade(
        id=f"c{side}", symbol=symbol, side=side, strike=78700.0,
        entryPremium=100.0, currentPremium=100.0, lots=25,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(minutes=mins_ago + 5),
        closedAt=datetime.now(IST) - timedelta(minutes=mins_ago),
        pnlInr=pnl,
    )


def test_whipsaw_flip_caps_after_opposite_side_win():
    """CALLs won this session → a max-size PUT flip is capped (Aug6 mechanism)."""
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(Side.CALL, 24000.0)]
    lots, meta = cap_opposite_side_flip_after_win(27, state, symbol="SENSEX", side=Side.PUT)
    assert lots == 8
    assert meta["applied"] is True
    assert meta["flipFromWinSide"] == "CALL"


def test_whipsaw_flip_no_cap_same_side():
    """Same side as the winner (CALL after CALL win) — not a flip, no cap."""
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(Side.CALL, 24000.0)]
    lots, meta = cap_opposite_side_flip_after_win(27, state, symbol="SENSEX", side=Side.CALL)
    assert lots == 27
    assert meta["applied"] is False


def test_whipsaw_flip_no_cap_after_opposite_loss():
    """Opposite side LOST (not a win) → no whipsaw cap."""
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(Side.CALL, -5000.0)]
    lots, meta = cap_opposite_side_flip_after_win(27, state, symbol="SENSEX", side=Side.PUT)
    assert lots == 27
    assert meta["applied"] is False
