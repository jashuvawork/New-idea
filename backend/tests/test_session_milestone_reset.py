"""Session entry window, open caution, and milestone reset tests."""

import asyncio
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.performance_milestone import _current_batch_trades, compute_milestone_stats
from app.engines.session_timing import (
    entries_allowed_now,
    in_open_caution_window,
    min_explosion_score_now,
)
from app.services import trade_store

IST = ZoneInfo("Asia/Kolkata")


def test_entries_blocked_before_920():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 18, 0, tzinfo=IST)
            ok, reason = entries_allowed_now()
    assert not ok
    assert "09:20" in reason


def test_entries_allowed_at_920():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 20, 0, tzinfo=IST)
            ok, reason = entries_allowed_now()
    assert ok


def test_open_caution_window_924():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 24, 0, tzinfo=IST)
            assert in_open_caution_window()
            assert min_explosion_score_now() >= 52


def test_after_caution_normal_score():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 10, 0, 0, tzinfo=IST)
            assert not in_open_caution_window()
            assert min_explosion_score_now() == 52


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
