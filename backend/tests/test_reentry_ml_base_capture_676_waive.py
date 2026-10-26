"""Re-entry ML waived on PR #676-style base capture (CE + PUT mirror)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.session_mode_feedback import reentry_ml_win_prob_blocked
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _closed_ce_win(*, strike: float = 22500.0) -> MagicMock:
    t = MagicMock()
    t.id = "morning-win"
    t.symbol = "NIFTY"
    t.side = Side.CALL
    t.strike = strike
    t.strategyType = "EXPLOSIVE"
    t.exitReason = "explosion_profit_ladder_peak_keep"
    t.pnlInr = 5089.5
    t.closedAt = datetime.now(IST) - timedelta(hours=2)
    t.entryContext = {"selectionMode": "explosion"}
    return t


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-10-26T14:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=22520.0,
        atmStrike=22500.0,
        dataAvailable=True,
    )


def _676_call_alert(*, strike: float = 22550.0) -> dict:
    return {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": strike,
        "tier": "ELITE",
        "armedBaseLaunch": True,
        "firstLift": True,
        "ictFirstLift": True,
        "localBaseMovePct": 8.0,
        "ictBaseRelativeMovePct": 8.0,
        "explosionScore": 95.0,
    }


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
def test_reentry_ml_waived_when_call_atm_itm_base_676_eligible(mock_ml):
    """Afternoon CE at new ATM base — ML 41% must not block (#676 parity)."""
    s = settings_mock()
    s.explosion_reentry_ml_win_prob_gate_enabled = True
    s.reentry_ml_waive_on_base_capture_eligible_enabled = True
    mock_ml.return_value = 0.41

    state = AutoTraderState()
    state.closedPaperTrades = [_closed_ce_win(strike=22500.0)]

    with patch("app.engines.session_mode_feedback.get_settings", return_value=s):
        blocked, meta = reentry_ml_win_prob_blocked(
            state,
            symbol="NIFTY",
            side=Side.CALL,
            strike=22550.0,
            snap=_snap(),
            confidence=160.0,
            alert=_676_call_alert(strike=22550.0),
        )

    assert blocked is False
    assert meta.get("reentryMlBaseCaptureWaived") is True
    assert meta.get("reentryMlBaseCaptureWaiveReason") == "call_atm_itm_base_capture_676"
    mock_ml.assert_not_called()


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
def test_reentry_ml_still_blocks_chase_without_676_shape(mock_ml):
    """Extended OTM chase after win — ML gate stays on (not a base capture)."""
    s = settings_mock()
    s.explosion_reentry_ml_win_prob_gate_enabled = True
    s.reentry_ml_waive_on_base_capture_eligible_enabled = True
    s.ce_new_base_fresh_entry_enabled = False
    s.quality_moment_passport_enabled = False
    mock_ml.return_value = 0.41

    state = AutoTraderState()
    state.closedPaperTrades = [_closed_ce_win()]

    chase_alert = {
        "tier": "ELITE",
        "armedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 28.0,
        "ictBaseRelativeMovePct": 28.0,
    }

    with patch("app.engines.session_mode_feedback.get_settings", return_value=s):
        blocked, meta = reentry_ml_win_prob_blocked(
            state,
            symbol="NIFTY",
            side=Side.CALL,
            strike=22700.0,
            snap=_snap(),
            alert=chase_alert,
        )

    assert blocked is True
    assert meta.get("reason") == "reentry_ml_win_prob_low"
    mock_ml.assert_called_once()
