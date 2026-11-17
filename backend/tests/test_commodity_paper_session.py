"""Paper-only MCX entry window when equity cash is closed."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.session_timing import (
    commodity_paper_evening_active,
    entries_allowed_now,
    explosion_entries_allowed_now,
    in_regular_explosion_session_window,
    symbol_entry_market_live,
)
IST = ZoneInfo("Asia/Kolkata")
EVENING = datetime(2026, 11, 16, 20, 0, tzinfo=IST)


def test_commodity_paper_evening_entries_allowed():
    settings = type(
        "S",
        (),
        {
            "paper_trading": True,
            "commodity_paper_entries_enabled": True,
            "commodity_session_start_hour": 9,
            "commodity_session_start_minute": 0,
            "symbols": ["NIFTY", "CRUDEOIL"],
        },
    )()
    with patch("app.engines.session_timing.get_settings", return_value=settings):
        with patch("app.engines.session_timing.get_market_phase", return_value="CLOSED"):
            with patch(
                "app.engines.session_timing.any_configured_commodity_live",
                return_value=True,
            ):
                with patch("app.engines.session_timing.datetime") as mock_dt:
                    mock_dt.now.return_value = EVENING
                    ok, reason = entries_allowed_now()
    assert ok
    assert reason == "commodity_paper_evening"


def test_live_book_still_blocked_after_equity_close():
    settings = type(
        "S",
        (),
        {
            "paper_trading": False,
            "enable_live_trading": True,
            "commodity_paper_entries_enabled": True,
            "symbols": ["CRUDEOIL"],
        },
    )()
    with patch("app.engines.session_timing.get_settings", return_value=settings):
        with patch("app.engines.session_timing.get_market_phase", return_value="CLOSED"):
            with patch(
                "app.engines.session_timing.any_configured_commodity_live",
                return_value=True,
            ):
                ok, reason = entries_allowed_now()
    assert not ok
    assert reason == "market_not_live"
    assert not commodity_paper_evening_active()


def test_symbol_entry_market_live_commodity_vs_index():
    with patch(
        "app.engines.session_timing.get_market_phase",
        return_value="CLOSED",
    ), patch(
        "app.services.upstox.get_market_phase_for_symbol",
        return_value="LIVE_MARKET",
    ):
        assert symbol_entry_market_live("CRUDEOIL")
    with patch(
        "app.engines.session_timing.get_market_phase",
        return_value="CLOSED",
    ):
        assert not symbol_entry_market_live("NIFTY")


def test_explosion_and_regular_window_in_commodity_paper_evening():
    with patch("app.engines.session_timing.commodity_paper_evening_active", return_value=True):
        with patch(
            "app.engines.session_timing.entries_allowed_now",
            return_value=(True, "commodity_paper_evening"),
        ):
            exp_ok, _ = explosion_entries_allowed_now()
            assert exp_ok
            assert in_regular_explosion_session_window()