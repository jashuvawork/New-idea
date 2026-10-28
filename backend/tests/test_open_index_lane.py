"""Open index lanes (09:20–09:45): SENSEX CALL default, NIFTY PUT opt-in."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.open_index_lane import (
    in_open_caution_window_at,
    open_index_lane_qualified,
    open_index_lane_summary,
    resolve_lane_when,
    validate_open_index_lane,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
OPEN_TIME = datetime(2026, 10, 21, 9, 25, tzinfo=IST)
AFTER_OPEN = datetime(2026, 10, 21, 10, 0, tzinfo=IST)


def _candidate(
    *,
    symbol: str = "SENSEX",
    side: str = "CALL",
    first_lift: bool = True,
    local_pct: float = 12.0,
):
    return SimpleNamespace(
        symbol=symbol,
        side=Side.CALL if side == "CALL" else Side.PUT,
        strike=73000.0,
        premium=120.0,
        mode="explosion",
        alert={
            "ictFirstLift": first_lift,
            "ictBaseRelativeMovePct": local_pct,
            "localBaseMovePct": local_pct,
            "tier": "ELITE",
            "explosionScore": 220.0,
            "ictBreakout": True,
            "ictFlatThenVertical": True,
            "flatVerticalGrade": "A",
        },
        explosion_event=SimpleNamespace(velocity_3s=1.2),
    )


def test_summary_defaults():
    s = Settings()
    summary = open_index_lane_summary(s)
    assert summary["enabled"] is True
    assert summary["sensexCallLane"] is True
    assert summary["niftyPutLane"] is True


def test_idle_after_0945():
    s = Settings(open_index_lane_enabled=True, open_sensex_call_lane_enabled=True)
    cand = _candidate(symbol="SENSEX", side="PUT")
    ok, reason, meta = validate_open_index_lane(cand, settings=s, when=AFTER_OPEN)
    assert ok is True
    assert meta == {}
    assert reason == "ok"


def test_sensex_put_blocked_during_open():
    s = Settings(open_index_lane_enabled=True, open_sensex_call_lane_enabled=True)
    cand = _candidate(symbol="SENSEX", side="PUT")
    ok, reason, _ = validate_open_index_lane(cand, settings=s, when=OPEN_TIME)
    assert ok is False
    assert reason == "open_index_lane_sensex_call_only"


@patch("app.engines.elite_score_engine.compute_elite_score")
@patch("app.engines.elite_score_engine.infer_stage")
@patch("app.engines.elite_score_engine.infer_setup_type")
@patch("app.engines.trade_ranking.rank_entry_candidate")
def test_sensex_call_passes_lane(mock_rank, mock_setup, mock_stage, mock_elite):
    mock_rank.return_value = {"evidence": {"tier": "ELITE"}, "grade": "A", "rankScore": 90.0}
    mock_setup.return_value = "V"
    mock_stage.return_value = "ARMED"
    mock_elite.return_value = (95.0, "ELITE", {})

    s = Settings(open_index_lane_enabled=True, open_sensex_call_lane_enabled=True)
    cand = _candidate(symbol="SENSEX", side="CALL")
    ok, reason, meta = validate_open_index_lane(cand, settings=s, when=OPEN_TIME)
    assert ok is True
    assert meta.get("openIndexLaneLane") == "SENSEX_CALL"


def test_default_nifty_call_blocked_during_open():
    s = Settings()
    cand = _candidate(symbol="NIFTY", side="CALL")
    ok, reason, _ = validate_open_index_lane(cand, settings=s, when=OPEN_TIME)
    assert ok is False
    assert reason == "open_index_lane_nifty_put_only"


def test_nifty_put_lane_opt_in_blocks_call():
    s = Settings(
        open_index_lane_enabled=True,
        open_nifty_put_lane_enabled=True,
        open_sensex_call_lane_enabled=False,
    )
    cand = _candidate(symbol="NIFTY", side="CALL")
    ok, reason, _ = validate_open_index_lane(cand, settings=s, when=OPEN_TIME)
    assert ok is False
    assert reason == "open_index_lane_nifty_put_only"


def test_resolve_lane_when_uses_snap_timestamp():
    ts = datetime(2026, 10, 21, 9, 25, tzinfo=IST)
    cand = _candidate(symbol="SENSEX", side="CALL")
    cand.snap = type("Snap", (), {"timestamp": ts})()
    assert resolve_lane_when(cand) == ts


def test_open_index_lane_qualified_requires_passed_quality():
    cand = _candidate(symbol="SENSEX", side="PUT")
    ok, reason, _ = open_index_lane_qualified(cand, when=OPEN_TIME)
    assert ok is False
    assert reason == "open_index_lane_sensex_call_only"


def test_in_open_caution_window_at_boundaries():
    s = Settings()
    t920 = datetime(2026, 10, 21, 9, 20, tzinfo=IST)
    t945 = datetime(2026, 10, 21, 9, 45, tzinfo=IST)
    assert in_open_caution_window_at(t920) is True
    assert in_open_caution_window_at(t945) is False
