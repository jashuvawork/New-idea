"""Session entry window, open caution, and milestone reset tests."""

import asyncio
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.performance_milestone import _current_batch_trades, compute_milestone_stats
from app.engines.session_timing import (
    entries_allowed_now,
    explosion_entries_allowed_now,
    in_open_caution_window,
    min_explosion_score_now,
)
from app.services import trade_store

IST = ZoneInfo("Asia/Kolkata")


def test_entries_blocked_before_915():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 14, 0, tzinfo=IST)
            ok, reason = entries_allowed_now()
    assert not ok
    assert "09:15" in reason


def test_entries_allowed_at_915():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 15, 0, tzinfo=IST)
            ok, reason = entries_allowed_now()
    assert ok
    assert reason == "ok"


def test_explosion_and_entries_aligned_at_open_setup_start():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 10, 21, 9, 16, 37, tzinfo=IST)
            early_ok, _ = explosion_entries_allowed_now()
            ok, reason = entries_allowed_now()
    assert early_ok is False
    assert ok is True
    assert reason == "ok"


def test_entries_allowed_at_920():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 20, 0, tzinfo=IST)
            ok, reason = entries_allowed_now()
    assert ok


def test_open_caution_active_until_945():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 24, 0, tzinfo=IST)
            assert in_open_caution_window()
            assert min_explosion_score_now() == 45


def test_open_caution_starts_at_915_not_before():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 14, 59, tzinfo=IST)
            assert not in_open_caution_window()
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 15, 0, tzinfo=IST)
            assert in_open_caution_window()


def test_open_caution_ends_at_945_not_extended():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 44, 59, tzinfo=IST)
            assert in_open_caution_window()
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 45, 0, tzinfo=IST)
            assert not in_open_caution_window()


def test_after_open_normal_score():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 10, 0, 0, tzinfo=IST)
            assert not in_open_caution_window()
            assert min_explosion_score_now() == 38


def test_current_batch_rolls_after_fifty():
    trades = [{"id": str(i), "pnlInr": 1000.0} for i in range(1, 76)]
    batch_num, completed, batch = _current_batch_trades(trades)
    assert completed == 1
    assert batch_num == 2
    assert len(batch) == 25


@patch("app.engines.performance_milestone.trade_store.get_milestone_batch_offset", return_value=35)
@patch("app.engines.performance_milestone.trade_store.get_milestone_meta", return_value={"resetAt": "2026-06-30T10:00:00+05:30"})
@patch("app.engines.performance_milestone.trade_store.get_all_closed_trades_chronological")
def test_milestone_reset_starts_fresh_batch(mock_get, _meta, _offset):
    mock_get.return_value = [{"id": str(i), "status": "CLOSED", "pnlInr": 0} for i in range(1, 36)]
    stats = compute_milestone_stats()
    assert stats["batchOffset"] == 35
    assert stats["tradeCount"] == 0


def test_can_relogin_after_330_expiry(monkeypatch):
    from app.services import token_manager

    async def fake_meta():
        return {"sessionDate": "2026-06-29", "generatedAt": "2026-06-29T03:27:07+05:30"}

    async def fake_token():
        return "stale-token"

    monkeypatch.setattr(token_manager, "get_token_meta", fake_meta)
    monkeypatch.setattr(token_manager, "get_upstox_token", fake_token)
    monkeypatch.setattr(token_manager, "_today_ist", lambda: "2026-06-29")

    assert not asyncio.run(token_manager.is_token_valid_today())
