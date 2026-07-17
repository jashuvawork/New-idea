"""High-mover ELITE bypass — last-N rank and instrument cooldown."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import ExplosionEvent
from app.engines.extreme_explosion_moment import is_high_mover_elite_bypass
from app.engines.pretrade_validator import check_last_n_candidate_gate
from app.models.schemas import AutoTraderState, Side


def _elite_call_event(daily_move: float = 105.0) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=78700.0,
        premium=150.0,
        velocity_3s=3.0,
        velocity_9s=5.0,
        velocity_15s=8.0,
        volume_surge=2.0,
        explosion_score=62.0,
        tier="ELITE",
        reason="+105%/session",
        daily_move_pct=daily_move,
    )


@patch("app.engines.extreme_explosion_moment.get_settings")
def test_elite_105pct_high_mover_bypass_blocked_as_late_chase(mock_settings):
    """+105% is past the chase ceiling — bypass must NOT reopen PF killers."""
    s = MagicMock()
    s.extreme_explosion_all_in_enabled = True
    s.extreme_explosion_elite_move_min_pct = 100.0
    s.extreme_explosion_all_in_move_min_pct = 150.0
    s.extreme_explosion_all_in_min_score = 35.0
    s.all_day_explosion_min_score = 38.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.high_mover_bypass_max_move_pct = 70.0
    s.extreme_all_in_bypass_max_move_pct = 70.0
    s.vertical_rip_bypass_min_peak_pct = 30.0
    mock_settings.return_value = s

    assert is_high_mover_elite_bypass(event=_elite_call_event()) is False


@patch("app.engines.extreme_explosion_moment.get_settings")
def test_elite_45pct_high_mover_bypass_still_works(mock_settings):
    s = MagicMock()
    s.extreme_explosion_all_in_enabled = True
    s.extreme_explosion_elite_move_min_pct = 100.0
    s.extreme_explosion_all_in_move_min_pct = 150.0
    s.extreme_explosion_all_in_min_score = 35.0
    s.all_day_explosion_min_score = 38.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.high_mover_bypass_max_move_pct = 70.0
    s.extreme_all_in_bypass_max_move_pct = 70.0
    s.vertical_rip_bypass_min_peak_pct = 30.0
    mock_settings.return_value = s

    assert is_high_mover_elite_bypass(event=_elite_call_event(daily_move=45.0)) is True


@patch("app.engines.pretrade_validator.get_settings")
@patch("app.engines.pretrade_validator.last_n_elevated_min_rank", return_value=72.0)
@patch("app.engines.pretrade_validator.analyze_last_n_trades")
def test_last_n_bypassed_for_elite_105pct(mock_analyze, mock_elevated, mock_settings):
    s = MagicMock()
    s.last_n_trades_gate_enabled = True
    s.last_n_trades_min_count = 3
    s.best_trades_only_enabled = True
    s.best_trades_min_rank_score = 62.0
    s.best_trades_explosion_only_after_losses = 3
    mock_settings.return_value = s
    mock_analyze.return_value = {"losses": 4, "profitFactor": 0.2, "allLosses": True}

    from types import SimpleNamespace

    candidate = SimpleNamespace(
        mode="explosion",
        score=62.0,
        tier="ELITE",
        symbol="SENSEX",
        side=Side.CALL,
        explosion_event=_elite_call_event(),
        snap=MagicMock(),
    )
    with patch(
        "app.engines.extreme_explosion_moment.is_high_mover_elite_bypass",
        return_value=True,
    ):
        ok, reason, _ = check_last_n_candidate_gate(candidate, AutoTraderState())
    assert ok is True
    assert reason == "ok"
