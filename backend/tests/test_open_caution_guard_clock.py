"""Open caution gates must use decision clock — never stale snap timestamps after 09:45."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.open_index_lane import open_setup_guard_when, resolve_lane_when
from app.engines.open_setup_guards import (
    daily_entry_prefilter_reason,
    open_caution_side_align_ok,
    validate_open_setup_entry,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
MORNING_SNAP = datetime(2026, 11, 5, 9, 20, tzinfo=IST)
OPEN = datetime(2026, 11, 5, 9, 35, tzinfo=IST)
AFTER_OPEN = datetime(2026, 11, 5, 10, 30, tzinfo=IST)


def _cand_bearish_call_block():
    """Morning snap + CALL blocks in open window on bearish tape."""
    snap = SimpleNamespace(
        symbol="SENSEX",
        spot=72800.0,
        dataAvailable=True,
        timestamp=MORNING_SNAP,
    )
    return SimpleNamespace(
        symbol="SENSEX",
        side=Side.CALL,
        strike=72800.0,
        snap=snap,
        alert={"ictFirstLift": True, "tier": "ELITE"},
    )


def test_resolve_lane_when_still_uses_snap_for_replay_helpers():
    cand = _cand_bearish_call_block()
    assert resolve_lane_when(cand, None) == MORNING_SNAP
    assert open_setup_guard_when(cand, OPEN) == OPEN


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_open_setup_blocks_in_window_with_explicit_when(mock_session):
    mock_session.return_value = {
        "open": 73000.0,
        "last": 72800.0,
        "hi": 73000.0,
        "lo": 72800.0,
    }
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_side_align_index_enabled=True,
        open_caution_itm_band_enabled=False,
        open_caution_non_lane_index_blocked=False,
    )
    cand = _cand_bearish_call_block()
    ok, reason, _ = validate_open_setup_entry(cand, settings=s, when=OPEN)
    assert not ok
    assert reason == "open_caution_call_on_bearish_open"


@patch("app.engines.index_tick_helpers.resolve_index_session")
@patch("app.engines.open_setup_guards.open_setup_guard_when", return_value=AFTER_OPEN)
def test_open_setup_idle_after_945_despite_morning_snap(mock_guard_when, mock_session):
    mock_session.return_value = {
        "open": 73000.0,
        "last": 72800.0,
        "hi": 73000.0,
        "lo": 72800.0,
    }
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_side_align_index_enabled=True,
        open_caution_itm_band_enabled=False,
        open_caution_non_lane_index_blocked=False,
    )
    cand = _cand_bearish_call_block()
    ok, reason, meta = validate_open_setup_entry(cand, settings=s)
    assert ok, reason
    assert meta == {}
    mock_guard_when.assert_called()


@patch("app.engines.index_tick_helpers.resolve_index_session")
@patch("app.engines.open_setup_guards.open_setup_guard_when", return_value=AFTER_OPEN)
def test_side_align_idle_after_945_without_explicit_when(mock_guard_when, mock_session):
    mock_session.return_value = {
        "open": 73000.0,
        "last": 72800.0,
        "hi": 73000.0,
        "lo": 72800.0,
    }
    s = Settings(open_caution_side_align_index_enabled=True)
    snap = SimpleNamespace(spot=72800.0, timestamp=MORNING_SNAP)
    ok, reason, _ = open_caution_side_align_ok("SENSEX", "CALL", snap, settings=s)
    assert ok, reason


@patch("app.engines.index_tick_helpers.resolve_index_session")
@patch("app.engines.open_setup_guards.open_setup_guard_when", return_value=AFTER_OPEN)
def test_daily_prefilter_no_open_caution_block_after_945(mock_guard_when, mock_session):
    mock_session.return_value = {
        "open": 73000.0,
        "last": 72800.0,
        "hi": 73000.0,
        "lo": 72800.0,
    }
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_side_align_index_enabled=True,
        open_caution_itm_band_enabled=False,
        open_caution_non_lane_index_blocked=False,
        selector_expiry_otm_prefilter_enabled=False,
    )
    cand = _cand_bearish_call_block()
    reason = daily_entry_prefilter_reason(cand, {}, settings=s)
    assert reason == ""
