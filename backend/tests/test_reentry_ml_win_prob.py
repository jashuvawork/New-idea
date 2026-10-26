"""ML win-probability gate for explosion re-entries (Aug28 24050)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.session_mode_feedback import reentry_ml_win_prob_blocked
from app.models.schemas import AutoTraderState, Side

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.explosion_reentry_ml_win_prob_gate_enabled = True
    s.explosion_reentry_ml_win_prob_min = 0.52
    s.explosion_reentry_ml_win_prob_same_strike_min = 0.55
    s.quality_moment_passport_enabled = True
    s.quality_moment_waive_reentry_ml_after_win = True
    s.quality_moment_waive_reentry_ml_after_loss = False
    return s


def _closed(
    *,
    trade_id: str = "prior-1",
    strike: float = 24200.0,
    pnl_inr: float = 2346.0,
    exit_reason: str = "explosion_stage_trail",
    minutes_ago: float = 30.0,
    side: Side = Side.PUT,
) -> MagicMock:
    t = MagicMock()
    t.id = trade_id
    t.symbol = "NIFTY"
    t.side = side
    t.strike = strike
    t.strategyType = "EXPLOSIVE"
    t.exitReason = exit_reason
    t.pnlInr = pnl_inr
    t.bestPnlPoints = 0.0
    t.closedAt = datetime.now(IST) - timedelta(minutes=minutes_ago)
    t.openedAt = t.closedAt - timedelta(minutes=20)
    t.entryContext = {"selectionMode": "explosion"}
    return t


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_first_entry_not_gated(mock_settings, mock_ml):
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.41
    state = AutoTraderState()
    state.closedPaperTrades = []
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=snap,
        confidence=210.0,
    )
    assert blocked is False
    assert meta.get("applied") is False
    mock_ml.assert_not_called()


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_post_win_session_reentry_blocks_low_ml(mock_settings, mock_ml):
    """Aug28 first 24050 — post 24200 win, ML 41% must block at 52% floor."""
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.411
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(strike=24200.0, pnl_inr=2346.0)]
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=snap,
        confidence=210.84,
    )
    assert blocked is True
    assert meta["reentryKind"] == "session"
    assert meta["mlWinProb"] == 0.411
    assert meta["requiredMlWinProb"] == 0.52
    assert meta["reason"] == "reentry_ml_win_prob_low"


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_same_strike_reentry_uses_stricter_floor(mock_settings, mock_ml):
    """Aug28 second 24050 — same strike after loss, ML 43% blocked at 55%."""
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.434
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed(
            trade_id="ca829ece",
            strike=24050.0,
            pnl_inr=-3551.75,
            exit_reason="adaptive_stop_loss",
            minutes_ago=17.0,
        )
    ]
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=snap,
        confidence=257.73,
    )
    assert blocked is True
    assert meta["reentryKind"] == "same_strike"
    assert meta["requiredMlWinProb"] == 0.55
    assert meta["priorExitReason"] == "adaptive_stop_loss"


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_session_reentry_allows_high_ml(mock_settings, mock_ml):
    """Winners were ~56% ML — post-win re-entry at 56% passes session floor."""
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.556
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(strike=24200.0, pnl_inr=2346.0)]
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24100.0,
        snap=snap,
        confidence=177.78,
    )
    assert blocked is False
    assert meta["reentryKind"] == "session"
    assert meta["mlWinProb"] == 0.556


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_same_strike_reentry_allows_high_ml(mock_settings, mock_ml):
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.58
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed(
            strike=24050.0,
            pnl_inr=-3551.75,
            exit_reason="adaptive_stop_loss",
        )
    ]
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=snap,
    )
    assert blocked is False
    assert meta["reentryKind"] == "same_strike"


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_quality_passport_waives_ml_after_session_win_cross_strike_call(
    mock_settings, mock_ml,
):
    """Passport waives session CE re-entry off a different strike; PUT stays on ML (#849)."""
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.41
    state = AutoTraderState()
    win = _closed(strike=22500.0, pnl_inr=5089.0, side=Side.CALL)
    state.closedPaperTrades = [win]
    snap = MagicMock()
    alert = {
        "tier": "ELITE",
        "ictFirstLift": True,
        "ictFlatThenVertical": True,
        "ictBaseArmed": True,
        "momentType": "first_lift_local_base",
    }
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22600.0,
        snap=snap,
        confidence=160.0,
        alert=alert,
    )
    assert blocked is False
    assert meta.get("qualityMomentPassport") is True


def _ce_new_base_alert(**extra) -> dict:
    """26 Oct 22500 CE shape: armed base still on the pad after the morning win."""
    alert = {
        "ictBaseArmed": True,
        "ictFlatThenVertical": True,
        "localBaseMovePct": 12.0,
        "tier": "ELITE",
        "side": "CALL",
    }
    alert.update(extra)
    return alert


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_ce_new_base_with_momentum_is_a_fresh_entry(mock_settings, mock_ml):
    """After a CE win, a new base that is already lifting is a new entry."""
    mock_settings.return_value = Settings()
    mock_ml.return_value = 0.41
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed(strike=22500.0, pnl_inr=5089.5, side=Side.CALL)
    ]
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22500.0,
        snap=snap,
        confidence=160.0,
        alert=_ce_new_base_alert(),
        velocity_3s=1.4,
    )
    assert blocked is False
    assert meta.get("freshEntry") is True
    assert meta.get("reason") == "ce_new_base_fresh_entry"
    assert meta.get("applied") is False
    mock_ml.assert_not_called()


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_ce_new_base_with_premium_momentum_is_a_fresh_entry(mock_settings, mock_ml):
    """Chart momentum on the new base counts when the 3s tape is flat."""
    mock_settings.return_value = Settings()
    mock_ml.return_value = 0.41
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed(strike=22500.0, pnl_inr=5089.5, side=Side.CALL)
    ]
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22500.0,
        snap=MagicMock(),
        alert=_ce_new_base_alert(premiumMomentum5Pct=4.05),
        velocity_3s=0.0,
    )
    assert blocked is False
    assert meta.get("reason") == "ce_new_base_fresh_entry"
    mock_ml.assert_not_called()


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_ce_new_base_without_momentum_stays_a_reentry(mock_settings, mock_ml):
    mock_settings.return_value = Settings()
    mock_ml.return_value = 0.41
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed(strike=22500.0, pnl_inr=5089.5, side=Side.CALL)
    ]
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22500.0,
        snap=MagicMock(),
        alert=_ce_new_base_alert(),
        velocity_3s=0.0,
    )
    assert blocked is True
    assert meta["reentryKind"] == "same_strike"
    assert meta["requiredMlWinProb"] == 0.55
    assert meta.get("freshEntry") is not True


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_ce_chase_without_new_base_stays_a_reentry(mock_settings, mock_ml):
    """Momentum alone, already off the base, is still a same-strike reentry."""
    mock_settings.return_value = Settings()
    mock_ml.return_value = 0.41
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed(strike=22500.0, pnl_inr=5089.5, side=Side.CALL)
    ]
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22500.0,
        snap=MagicMock(),
        alert={
            "ictBaseArmed": True,
            "ictFlatThenVertical": True,
            "localBaseMovePct": 40.0,
            "tier": "ELITE",
            "velocity3s": 2.5,
        },
        velocity_3s=2.5,
    )
    assert blocked is True
    assert meta["reason"] == "reentry_ml_win_prob_low"
    assert meta["reentryKind"] == "same_strike"


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_pe_new_base_with_momentum_is_a_fresh_entry(mock_settings, mock_ml):
    """A put lifting off a newly formed base matches the call fresh-entry rule."""
    mock_settings.return_value = Settings()
    mock_ml.return_value = 0.411
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(strike=24200.0, pnl_inr=2346.0)]
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=MagicMock(),
        confidence=210.84,
        alert=_ce_new_base_alert(side="PUT", velocity3s=2.0),
        velocity_3s=2.0,
        premium_momentum_pct=8.0,
    )
    assert blocked is False
    assert meta.get("freshEntry") is True
    assert meta.get("reason") == "pe_new_base_fresh_entry"
    assert meta.get("applied") is False
    mock_ml.assert_not_called()


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_pe_new_base_with_premium_momentum_is_a_fresh_entry(mock_settings, mock_ml):
    mock_settings.return_value = Settings()
    mock_ml.return_value = 0.41
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(strike=22350.0, pnl_inr=-25811.5)]
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=22350.0,
        snap=MagicMock(),
        alert=_ce_new_base_alert(side="PUT", premiumMomentum5Pct=0.90),
        velocity_3s=0.0,
    )
    assert blocked is False
    assert meta.get("reason") == "pe_new_base_fresh_entry"
    mock_ml.assert_not_called()


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_pe_new_base_without_momentum_stays_a_reentry(mock_settings, mock_ml):
    mock_settings.return_value = Settings()
    mock_ml.return_value = 0.411
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(strike=24200.0, pnl_inr=2346.0)]
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=MagicMock(),
        confidence=210.84,
        alert=_ce_new_base_alert(side="PUT"),
        velocity_3s=0.0,
    )
    assert blocked is True
    assert meta["reentryKind"] == "session"
    assert meta["mlWinProb"] == 0.411
    assert meta.get("freshEntry") is not True


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_pe_chase_without_new_base_stays_a_reentry(mock_settings, mock_ml):
    """Aug28 put reentries with momentum but no new base stay on the ML floor."""
    mock_settings.return_value = Settings()
    mock_ml.return_value = 0.411
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(strike=24200.0, pnl_inr=2346.0)]
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=MagicMock(),
        confidence=210.84,
        alert={
            "ictBaseArmed": True,
            "ictFlatThenVertical": True,
            "localBaseMovePct": 40.0,
            "tier": "ELITE",
            "side": "PUT",
            "velocity3s": 2.0,
        },
        velocity_3s=2.0,
        premium_momentum_pct=8.0,
    )
    assert blocked is True
    assert meta["reason"] == "reentry_ml_win_prob_low"
    assert meta["reentryKind"] == "session"
    assert meta.get("freshEntry") is not True
