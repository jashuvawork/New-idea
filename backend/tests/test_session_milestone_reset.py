"""Session entry window and milestone reset tests."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.performance_milestone import _current_batch_trades, compute_milestone_stats
from app.engines.session_timing import entries_allowed_now
from app.services import trade_store

IST = ZoneInfo("Asia/Kolkata")


def test_entries_blocked_before_916():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 15, 30, tzinfo=IST)
            ok, reason = entries_allowed_now()
    assert not ok
    assert "09:16" in reason


def test_entries_allowed_after_916():
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, 9, 16, 0, tzinfo=IST)
            ok, reason = entries_allowed_now()
    assert ok
    assert reason == "ok"


@patch("app.engines.performance_milestone.trade_store.get_milestone_batch_offset", return_value=35)
@patch("app.engines.performance_milestone.trade_store.get_milestone_meta", return_value={"resetAt": "2026-06-30T10:00:00+05:30"})
@patch("app.engines.performance_milestone.trade_store.get_all_closed_trades_chronological")
def test_milestone_reset_starts_fresh_batch(mock_get, _meta, _offset):
    mock_get.return_value = [{"id": str(i), "status": "CLOSED", "pnlInr": 0} for i in range(1, 36)]
    stats = compute_milestone_stats()
    assert stats["batchOffset"] == 35
    assert stats["tradeCount"] == 0
    assert stats["tradeProgressPct"] == 0.0
    assert stats["batchNumber"] == 1


def test_current_batch_with_offset():
    trades = [{"id": str(i), "pnlInr": 1} for i in range(1, 41)]
    _, _, batch = _current_batch_trades(trades, offset=35)
    assert len(batch) == 5
