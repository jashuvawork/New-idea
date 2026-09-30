"""Sep 9–17 legacy — CE rally/at-base waives elite chase/timing in elite_entry_allowed."""

from unittest.mock import MagicMock, patch

from app.config import Settings
from app.engines.elite_score_engine import elite_entry_allowed, elite_perfect_score_blocked


def _ranking(**kwargs):
    base = {"grade": "A", "rankScore": 88.0, "side": "CALL"}
    base.update(kwargs)
    return base


def test_perfect_score_waived_for_legacy_call_capture_near_base():
    s = Settings()
    blocked, reason = elite_perfect_score_blocked(
        100.0,
        18.0,
        settings=s,
        call_capture_waive=True,
    )
    assert not blocked
    assert reason == ""


def test_perfect_score_still_blocks_chase_without_waive():
    s = Settings()
    blocked, reason = elite_perfect_score_blocked(100.0, 25.0, settings=s, call_capture_waive=False)
    assert blocked
    assert reason == "elite_perfect_score_chase_blocked"


@patch("app.engines.index_rally_side_flip.index_rally_side_flip_bypass", return_value=(True, "index_rally_side_flip", {}))
@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_fingerprint", return_value=False)
@patch("app.engines.pe_win_ce_mirror.call_ce_base_context_armed", return_value=(False, "", {}))
@patch("app.engines.best_trade_policy.call_at_base_best_trade_fingerprint", return_value=False)
def test_elite_entry_waives_timing_on_index_rally_flip(_base, _armed, _rally_fp, _flip):
    s = Settings(
        sep917_legacy_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
        elite_trade_engine_enabled=True,
    )
    snap = MagicMock(symbol="SENSEX", spotChart=MagicMock())
    evidence = {
        "symbol": "SENSEX",
        "side": "CALL",
        "tier": "ELITE",
        "explosionScore": 92.0,
        "localBaseMovePct": 12.0,
        "firstLift": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "armedBaseLaunch": True,
        "orderflowPositive": True,
        "velocity3s": 2.5,
        "velocity9s": 1.8,
        "flatVerticalQuality": 80.0,
        "volumeAwaken": True,
        "timingAssessment": "POOR",
        "timingAction": "wait",
        "mode": "explosion",
    }
    state = MagicMock()
    ok, reason, _ = elite_entry_allowed(
        evidence,
        _ranking(),
        settings=s,
        state=state,
        snapshots={"SENSEX": snap},
        side="CALL",
    )
    assert ok, reason
    assert reason == "ok"
