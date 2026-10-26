"""EOD replay includes live re-entry ML gate when enabled."""

from unittest.mock import MagicMock, patch

from app.config import Settings
from app.engines.eod_local_base_replay import evaluate_replay_structural_gates
from datetime import datetime
from zoneinfo import ZoneInfo

from app.models.schemas import AutoTraderState, MarketPhase, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=22500.0,
    )


@patch("app.engines.session_mode_feedback.reentry_ml_win_prob_blocked")
def test_replay_structural_calls_reentry_ml_when_enabled(mock_ml):
    mock_ml.return_value = (True, {"reason": "reentry_ml_win_prob_low"})
    s = Settings()
    s.eod_replay_structural_gates_enabled = True
    s.eod_replay_reentry_ml_gate_enabled = True
    s.eod_replay_pretrade_enabled = False
    alert = {
        "side": "CALL",
        "strike": 22500.0,
        "symbol": "NIFTY",
        "tier": "ELITE",
        "score": 150.0,
        "premium": 200.0,
    }
    snap = _snap()
    state = AutoTraderState()
    ok, reason = evaluate_replay_structural_gates(
        alert,
        snap,
        state,
        {"NIFTY": snap},
        settings=s,
        ranking={"grade": "A"},
    )
    assert ok is False
    assert reason == "reentry_ml_win_prob_low"
    mock_ml.assert_called_once()


@patch("app.engines.session_mode_feedback.reentry_ml_win_prob_blocked")
def test_replay_skips_reentry_ml_when_disabled(mock_ml):
    s = Settings()
    s.eod_replay_structural_gates_enabled = True
    s.eod_replay_reentry_ml_gate_enabled = False
    alert = {"side": "CALL", "strike": 22500.0, "tier": "ELITE", "premium": 200.0}
    snap = _snap()
    with patch(
        "app.engines.explosion_entry_guards.detect_fake_explosion_trap",
        return_value=(False, "ok", {}),
    ), patch(
        "app.engines.explosion_entry_guards.immature_explosion_blocked",
        return_value=(False, ""),
    ), patch(
        "app.engines.ict_breakout_monitor.analyze_explosion_event_ict",
        return_value=MagicMock(),
    ):
        evaluate_replay_structural_gates(
            alert,
            snap,
            AutoTraderState(),
            {"NIFTY": snap},
            settings=s,
        )
    mock_ml.assert_not_called()
