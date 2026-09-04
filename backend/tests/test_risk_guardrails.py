"""Risk guardrails: never-green cut, whipsaw flip cap.

Aug6 SENSEX 78800 PE (never-green ELITE, 27 lots, −₹20k) and Jul30 (90-lot ELITE,
−₹86k) motivate bounding the downside on the trades that are wrong from entry.
Per-trade INR exit caps removed — structural/point SL only.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.session_mode_feedback import cap_opposite_side_flip_after_win
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _scratch_guard_settings() -> MagicMock:
    """Settings with scratch/early exits enabled (for unit tests of those guards)."""
    s = MagicMock()
    s.explosion_failed_launch_exit_enabled = True
    s.explosion_failed_launch_min_hold_seconds = 15
    s.explosion_failed_launch_max_hold_seconds = 45
    s.explosion_failed_launch_max_best_points = 1.0
    s.explosion_failed_launch_min_loss_points = 1.5
    s.explosion_failed_launch_max_velocity_3s = 0.0
    s.explosion_never_green_stop_enabled = True
    s.explosion_never_green_min_green_points = 0.5
    s.explosion_never_green_stop_points = 4.0
    s.explosion_never_green_stop_pct = 8.0
    s.explosion_never_green_min_hold_seconds = 10
    s.explosion_faded_rip_no_green_exit_enabled = False
    s.explosion_early_green_lock_enabled = False
    s.explosion_peak_fade_lock_enabled = False
    s.explosion_peak_capture_enabled = False
    s.explosion_no_progress_enabled = False
    s.explosion_per_trade_max_loss_inr = 0.0
    s.explosion_exceptional_per_trade_max_loss_inr = 0.0
    s.emergency_stop_enabled = False
    s.enable_live_trading = False
    s.live_hold_to_structural_sl = True
    return s


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
    with patch("app.engines.explosion_profit.get_settings", return_value=_scratch_guard_settings()):
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


def test_no_inr_per_trade_risk_cap_exit():
    """INR per-trade loss caps removed — oversized loss waits for point SL."""
    reason, _ = evaluate_explosion_exit(
        _trade(500.0, 495.0, best=3.0, lots=200), 495.0, "ELITE", 20,
    )
    assert reason != "explosion_per_trade_risk_cap"


def test_full_sleeve_no_inr_cap_exit():
    trade = _trade(100.0, 97.0, best=2.0, lots=75)
    trade.entryContext = {"fullSleeveQualified": True}
    reason, _ = evaluate_explosion_exit(
        trade, 97.0, "ELITE", 20, live_velocity_3s=0.5,
    )
    assert reason != "explosion_per_trade_risk_cap"


def test_elite_full_lot_uses_structural_sl_not_rupee_clip():
    """ELITE full-lot prefers structural SL + daily stop — no INR clip."""
    deep = _trade(100.0, 94.0, best=2.0, lots=100)
    deep.entryContext = {"eliteFullLot": True}
    reason, pnl = evaluate_explosion_exit(deep, 94.0, "ELITE", 20, live_velocity_3s=0.5)
    assert reason != "explosion_per_trade_risk_cap"
    assert pnl <= -10_000


def test_index_confirmed_ftv_no_inr_cap_exit():
    """Index-confirmed FTV — no per-trade INR clip; point SL owns exit."""
    survive = _trade(100.0, 97.0, best=2.0, lots=40)
    survive.entryContext = {"indexConfirmedFtv": True}
    reason, _ = evaluate_explosion_exit(survive, 97.0, "ELITE", 20, live_velocity_3s=0.5)
    assert reason != "explosion_per_trade_risk_cap"
    cut = _trade(100.0, 97.0, best=2.0, lots=75)
    cut.entryContext = {"indexConfirmedFtv": True}
    reason2, _ = evaluate_explosion_exit(cut, 97.0, "ELITE", 20, live_velocity_3s=0.5)
    assert reason2 != "explosion_per_trade_risk_cap"


def test_failed_launch_scratches_on_negative_velocity():
    with patch("app.engines.explosion_profit.get_settings", return_value=_scratch_guard_settings()):
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


def test_always_max_does_not_undo_whipsaw_flip_cap():
    """Aug6 pattern: whipsaw cap to 8 lots must not be re-floored to max lots."""
    from unittest.mock import patch

    from app.engines.capital_allocator import apply_explosion_always_max_lots

    state = AutoTraderState()
    state.closedPaperTrades = [_closed(Side.CALL, 24000.0)]
    lots, flip_cap_meta = cap_opposite_side_flip_after_win(
        27, state, symbol="SENSEX", side=Side.PUT, velocity_3s=3.0,
    )
    assert lots == 8
    assert flip_cap_meta["applied"] is True

    size_cap_applied = bool(flip_cap_meta.get("applied"))
    if not size_cap_applied:
        with patch(
            "app.engines.capital_allocator.max_lots_for_capital",
            return_value=27,
        ):
            lots = apply_explosion_always_max_lots(
                lots, "SENSEX", 50.0, mode="explosion",
            )
    assert lots == 8
