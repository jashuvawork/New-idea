"""Sep 9–17 legacy profile lifts pre-loss worst-day full pause."""

from unittest.mock import patch

from app.config import Settings
from app.engines.sep917_legacy_profile import legacy_skip_preloss_worst_day_pause_active
from app.engines.worst_day_guard import session_entry_policy, WorstDayVerdict
from app.models.schemas import AutoTraderState


def test_legacy_skip_preloss_pause_active_when_profile_on():
    s = Settings()
    assert legacy_skip_preloss_worst_day_pause_active(s) is True


def test_legacy_skip_preloss_pause_off_when_flag_disabled():
    s = Settings(sep917_legacy_skip_preloss_worst_day_pause=False)
    assert legacy_skip_preloss_worst_day_pause_active(s) is False


@patch("app.engines.worst_day_guard.get_settings")
@patch("app.engines.worst_day_guard.identify_worst_day")
@patch("app.engines.worst_day_guard.compute_session_pnl", return_value=0.0)
def test_session_policy_normal_on_chop_when_legacy_lift(mock_pnl, mock_identify, mock_settings):
    mock_settings.return_value = Settings()
    mock_identify.return_value = WorstDayVerdict(True, 45.0, ["bearish_sideways", "chop_regime"])
    policy, meta = session_entry_policy(AutoTraderState(), {})
    assert policy == "NORMAL"
    assert meta.get("sep917LegacyWorstDayLift") is True


@patch("app.engines.worst_day_guard.identify_worst_day")
def test_session_policy_still_paused_on_severe_loss(mock_identify):
    mock_identify.return_value = WorstDayVerdict(True, 45.0, ["chop_regime"])
    state = AutoTraderState()
    with patch("app.engines.worst_day_guard.compute_session_pnl", return_value=-25_000.0):
        policy, meta = session_entry_policy(state, {})
    assert policy == "PAUSED"
    assert meta.get("pauseReason") == "worst_day_severe_session_loss"
    assert meta.get("sep917LegacyWorstDayLift") is not True
