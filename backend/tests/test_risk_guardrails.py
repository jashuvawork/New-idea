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
    """Never green and down past max(4pt, 8% premium) exits before a deep loss."""
    reason, _ = evaluate_explosion_exit(
        _trade(346.0, 315.0, best=0.0, lots=1), 315.0, "ELITE", 20,
    )
    assert reason == "explosion_never_green_stop"


def test_never_green_holds_if_within_floor():
    """Down but within the never-green floor (−5pt) → not yet cut by this rule."""
    reason, _ = evaluate_explosion_exit(_trade(346.0, 341.0, best=0.0, lots=1), 341.0, "ELITE", 20)
    assert reason != "explosion_never_green_stop"


def test_never_green_skipped_once_green_printed():
    """A trade that DID print green (best>0) is not subject to the never-green cut."""
    reason, _ = evaluate_explosion_exit(_trade(346.0, 330.0, best=6.0, lots=1), 330.0, "ELITE", 20)
    assert reason != "explosion_never_green_stop"


def test_hard_per_trade_risk_cap_enabled_by_default():
    """Ordinary trades cannot exceed the default ₹2k loss ceiling."""
    reason, pnl = evaluate_explosion_exit(
        _trade(500.0, 495.0, best=3.0, lots=200), 495.0, "ELITE", 20,
    )
    assert reason == "explosion_per_trade_risk_cap"
    assert pnl <= -12000


def test_hard_per_trade_risk_cap_when_enabled():
    """When explicitly set >0, the ₹ ceiling still cuts oversized losses."""
    from unittest.mock import MagicMock, patch

    s = MagicMock()
    # Keep never-green from preempting (best>0); enable ₹ cap only.
    s.explosion_never_green_stop_enabled = True
    s.explosion_never_green_min_green_points = 0.5
    s.explosion_never_green_stop_points = 18.0
    s.explosion_never_green_stop_pct = 6.0
    s.explosion_never_green_min_hold_seconds = 20
    s.explosion_per_trade_max_loss_inr = 12_000.0
    with patch("app.engines.explosion_profit.get_settings", return_value=s):
        reason, pnl = evaluate_explosion_exit(
            _trade(500.0, 495.0, best=3.0, lots=200), 495.0, "ELITE", 20,
        )
    assert reason == "explosion_per_trade_risk_cap"
    assert pnl <= -12000


def test_exceptional_full_sleeve_uses_bounded_four_thousand_cap():
    trade = _trade(100.0, 97.0, best=2.0, lots=75)
    trade.entryContext = {"fullSleeveQualified": True}
    reason, pnl = evaluate_explosion_exit(
        trade, 97.0, "ELITE", 20, live_velocity_3s=0.5,
    )
    assert reason == "explosion_per_trade_risk_cap"
    assert pnl <= -4_000


def test_failed_launch_scratches_on_negative_velocity():
    trade = _trade(51.0, 49.0, best=0.5, lots=1, hold_s=20)
    reason, _ = evaluate_explosion_exit(
        trade, 49.0, "ELITE", 65, live_velocity_3s=-1.0,
    )
    assert reason == "explosion_failed_launch"


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
    """CALLs won this session → a hot PUT flip is capped (Aug6 size mechanism)."""
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(Side.CALL, 24000.0)]
    lots, meta = cap_opposite_side_flip_after_win(
        27, state, symbol="SENSEX", side=Side.PUT, velocity_3s=3.0,
    )
    assert lots == 8
    assert meta["applied"] is True
    assert meta.get("blocked") is False
    assert meta["flipFromWinSide"] == "CALL"


def test_whipsaw_flip_blocks_weak_velocity():
    """Aug6 PUT v3=0.54 after CALL wins — weak flip is blocked, not just sized down."""
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(Side.CALL, 24000.0)]
    lots, meta = cap_opposite_side_flip_after_win(
        27, state, symbol="SENSEX", side=Side.PUT, velocity_3s=0.54,
    )
    assert lots == 0
    assert meta["blocked"] is True
    assert meta["blockReason"] == "whipsaw_flip_velocity_below_breakout"


def test_whipsaw_flip_no_cap_same_side():
    """Same side as the winner (CALL after CALL win) — not a flip, no cap."""
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(Side.CALL, 24000.0)]
    lots, meta = cap_opposite_side_flip_after_win(
        27, state, symbol="SENSEX", side=Side.CALL, velocity_3s=0.5,
    )
    assert lots == 27
    assert meta["applied"] is False


def test_whipsaw_flip_no_cap_after_opposite_loss():
    """Opposite side LOST (not a win) → no whipsaw cap."""
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(Side.CALL, -5000.0)]
    lots, meta = cap_opposite_side_flip_after_win(
        27, state, symbol="SENSEX", side=Side.PUT, velocity_3s=0.5,
    )
    assert lots == 27
    assert meta["applied"] is False
