"""Post-win same-strike V-rip re-entry waiver (Oct 5 NIFTY 22550 CE afternoon rip)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.put_slide_ce_mirror import ce_win_pe_mirror_call_chase_blocked
from app.engines.session_mode_feedback import (
    reentry_ml_win_prob_blocked,
    same_strike_post_win_v_rip_reentry_waive,
)
from app.models.schemas import AutoTraderState, Side

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.same_strike_post_win_v_rip_reentry_waive_enabled = True
    s.same_strike_post_win_v_rip_min_prior_win_inr = 5000.0
    s.same_strike_post_win_v_rip_min_tier_score = 90.0
    s.ict_v_rip_pad_min_move_pct = 2.0
    s.ict_v_rip_max_move_pct = 25.0
    s.explosion_reentry_ml_win_prob_gate_enabled = True
    s.explosion_reentry_ml_win_prob_min = 0.52
    s.explosion_reentry_ml_win_prob_same_strike_min = 0.55
    s.ce_win_pe_mirror_enabled = True
    s.ce_win_pe_mirror_block_call_chase_enabled = True
    s.ce_win_pe_mirror_block_call_chase_seconds = 900
    return s


def _closed_call_win(*, strike: float = 22550.0, pnl: float = 28572.0):
    t = MagicMock()
    t.id = "d9006251"
    t.symbol = "NIFTY"
    t.side = Side.CALL
    t.strike = strike
    t.strategyType = "EXPLOSIVE"
    t.exitReason = "explosion_peak_velocity_reversal_keep"
    t.pnlInr = pnl
    t.closedAt = datetime.now(IST) - timedelta(hours=4)
    t.openedAt = t.closedAt - timedelta(minutes=30)
    t.entryContext = {"selectionMode": "explosion"}
    return t


def _v_rip_alert():
    return {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "momentType": "v_rip_session_low",
        "ictVRipReady": True,
        "localBaseMovePct": 8.5,
        "armedBaseLaunch": True,
    }


@patch("app.engines.session_mode_feedback.get_settings")
def test_same_strike_post_win_v_rip_waive_active(mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_call_win()]
    ok, meta = same_strike_post_win_v_rip_reentry_waive(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22550.0,
        alert=_v_rip_alert(),
        confidence=100.0,
    )
    assert ok is True
    assert meta.get("waive") is True


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_reentry_ml_waived_for_post_win_v_rip(mock_settings, mock_ml):
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.41
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_call_win()]
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22550.0,
        snap=MagicMock(),
        confidence=100.0,
        alert=_v_rip_alert(),
    )
    assert blocked is False
    assert meta.get("waive") is True
    mock_ml.assert_not_called()


@patch("app.engines.put_slide_ce_mirror.put_slide_entry_unlock_armed")
@patch("app.engines.put_slide_ce_mirror.session_call_win_meta")
@patch("app.engines.put_slide_ce_mirror._seconds_since_last_call_win")
@patch("app.engines.session_mode_feedback.get_settings")
@patch("app.engines.put_slide_ce_mirror.get_settings")
def test_ce_mirror_put_leg_waived_for_v_rip_second_leg(
    mock_ps_settings,
    mock_sm_settings,
    mock_elapsed,
    mock_call_win,
    mock_put_armed,
):
    mock_ps_settings.return_value = _settings()
    mock_sm_settings.return_value = _settings()
    mock_elapsed.return_value = 100.0
    mock_call_win.return_value = (True, {"callWinSymbol": "NIFTY"})
    mock_put_armed.return_value = (True, "put_slide", {})

    state = AutoTraderState()
    state.closedPaperTrades = [_closed_call_win()]
    candidate = MagicMock()
    candidate.mode = "explosion"
    candidate.side = Side.CALL
    candidate.symbol = "NIFTY"
    candidate.strike = 22550.0
    candidate.score = 100.0
    candidate.alert = _v_rip_alert()
    candidate.snap = MagicMock()

    blocked, reason, meta = ce_win_pe_mirror_call_chase_blocked(
        candidate, state, {"NIFTY": candidate.snap, "SENSEX": MagicMock(dataAvailable=True)},
    )
    assert blocked is False
    assert meta.get("ceWinPeMirrorWaived") is True
