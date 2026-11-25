"""Open-book shadow funnel — SELECT without orders before entry_earliest."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.open_setup_shadow import (
    assess_open_setup_shadow_preorder,
    build_open_setup_shadow_events,
    open_setup_shadow_select_active,
    open_setup_shadow_summary,
)
from app.models.schemas import AutoTraderState, Side
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = settings_mock()
    s.open_setup_shadow_record_enabled = True
    s.open_setup_shadow_pretrade_enabled = True
    s.entry_earliest_hour = 9
    s.entry_earliest_minute = 45
    s.open_setup_start_hour = 9
    s.open_setup_start_minute = 15
    s.open_caution_until_hour = 9
    s.open_caution_until_minute = 45
    s.controlled_trading_enabled = False
    return s


def test_shadow_active_only_inside_open_book_before_945():
    s = _settings()
    when = datetime(2026, 11, 25, 9, 20, tzinfo=IST)
    with patch("app.engines.open_setup_shadow.get_settings", return_value=s), patch(
        "app.engines.session_timing.get_settings", return_value=s
    ), patch("app.engines.open_setup_shadow.get_market_phase", return_value="LIVE_MARKET"), patch(
        "app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"
    ), patch("app.engines.session_timing.datetime") as mock_dt:
        mock_dt.now.return_value = when
        active, reason = open_setup_shadow_select_active()
    assert active is True
    assert reason == "open_setup_shadow_active"


def test_shadow_inactive_after_entry_earliest():
    s = _settings()
    when = datetime(2026, 11, 25, 9, 50, tzinfo=IST)
    with patch("app.engines.open_setup_shadow.get_settings", return_value=s), patch(
        "app.engines.session_timing.get_settings", return_value=s
    ), patch("app.engines.open_setup_shadow.get_market_phase", return_value="LIVE_MARKET"), patch(
        "app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"
    ), patch("app.engines.session_timing.datetime") as mock_dt:
        mock_dt.now.return_value = when
        active, reason = open_setup_shadow_select_active()
    assert active is False


def test_assess_marks_would_enter_except_clock():
    s = _settings()
    cand = MagicMock()
    cand.mode = "explosion"
    with patch("app.engines.open_setup_shadow.get_settings", return_value=s), patch(
        "app.engines.session_timing.get_settings", return_value=s
    ), patch(
        "app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"
    ), patch("app.engines.session_timing.datetime") as mock_dt, patch(
        "app.engines.pretrade_validator.validate_candidate", return_value=(True, "", {})
    ):
        mock_dt.now.return_value = datetime(2026, 11, 25, 9, 25, tzinfo=IST)
        ok, reason, meta = assess_open_setup_shadow_preorder(
            cand, AutoTraderState(), snapshots={},
        )
    assert meta.get("wouldEnterAt915") is True
    assert meta.get("liveClockWouldBlock") is True
    assert "before_entry_window" in reason


def test_build_events_pair_select_and_preorder():
    cand = MagicMock()
    cand.symbol = "SENSEX"
    cand.side = Side.CALL
    cand.strike = 84400.0
    cand.mode = "explosion"
    cand.score = 120.0
    cand.tier = "ELITE"
    rows = build_open_setup_shadow_events(
        cand,
        cycle_id="abc",
        radar_key="SENSEX:CALL:84400",
        would_ok=True,
        would_reason="open_setup_shadow_would_enter",
        shadow_meta={"wouldEnterAt915": True},
        selected_ranking={"grade": "A", "rankScore": 99.0},
    )
    assert len(rows) == 2
    assert rows[0]["event"] == "SELECTED"
    assert rows[0]["openSetupShadow"] is True
    assert rows[1]["event"] == "OPEN_SETUP_SHADOW_PREORDER"
    assert rows[1]["wouldEnter"] is True


def test_summary_exposes_enabled():
    s = _settings()
    with patch("app.engines.open_setup_shadow.get_settings", return_value=s):
        summ = open_setup_shadow_summary(s)
    assert summ["enabled"] is True
    assert "09:15" in summ["purpose"]