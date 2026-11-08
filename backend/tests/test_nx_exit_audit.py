"""N× exit audit: post-exit tape vs entryLtpMultipleCaptures."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.nx_exit_audit import audit_trade_nx_exit, generate_nx_exit_audit

IST = ZoneInfo("Asia/Kolkata")


def test_early_exit_flag_when_tape_runs_higher_after_close():
    """Trade closed below 2× but tape later hits 3× → earlyExitBeforeLaterNx."""
    closed = datetime(2026, 11, 10, 10, 30, 0, tzinfo=IST)
    trade = {
        "id": "t1",
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 24000,
        "entryPremium": 100.0,
        "maxLtp": 180.0,
        "status": "CLOSED",
        "closedAt": closed.isoformat(),
        "entryContext": {"entryLtpMultipleCaptures": []},
    }
    tape = [
        {
            "ts": closed.isoformat(),
            "contracts": [
                {"symbol": "NIFTY", "side": "CALL", "strike": 24000, "premium": 180.0},
            ],
        },
        {
            "ts": datetime(2026, 11, 10, 11, 0, 0, tzinfo=IST).isoformat(),
            "contracts": [
                {"symbol": "NIFTY", "side": "CALL", "strike": 24000, "premium": 320.0},
            ],
        },
    ]

    with patch("app.engines.nx_exit_audit.read_premium_tape", return_value=tape):
        row = audit_trade_nx_exit(trade, "2026-11-10", max_n=20)

    assert row["whileOpenMaxN"] == 1
    assert row["postExitTapeMaxN"] == 3
    assert row["earlyExitBeforeLaterNx"] is True
    assert row["missedNAfterExit"] == 2


def test_no_early_exit_when_captures_match_post_exit():
    trade = {
        "id": "t2",
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 24000,
        "entryPremium": 50.0,
        "maxLtp": 150.0,
        "status": "CLOSED",
        "closedAt": datetime(2026, 11, 10, 12, 0, 0, tzinfo=IST).isoformat(),
        "entryContext": {
            "entryLtpMultipleCaptures": [
                {"n": 2, "thresholdLtp": 100.0, "at": "2026-11-10T11:00:00+05:30", "peakLtp": 105.0},
                {"n": 3, "thresholdLtp": 150.0, "at": "2026-11-10T11:05:00+05:30", "peakLtp": 150.0},
            ],
        },
    }
    tape = [
        {
            "ts": datetime(2026, 11, 10, 12, 30, 0, tzinfo=IST).isoformat(),
            "contracts": [
                {"symbol": "NIFTY", "side": "PUT", "strike": 24000, "premium": 155.0},
            ],
        },
    ]

    with patch("app.engines.nx_exit_audit.read_premium_tape", return_value=tape):
        row = audit_trade_nx_exit(trade, "2026-11-10", max_n=20)

    assert row["whileOpenMaxN"] == 3
    assert row["postExitTapeMaxN"] == 3
    assert row["earlyExitBeforeLaterNx"] is False


@patch("app.engines.nx_exit_audit.get_settings")
@patch("app.engines.nx_exit_audit.get_day_detail")
def test_generate_nx_exit_audit_aggregates(mock_day, mock_settings):
    mock_settings.return_value.trade_entry_multiple_capture_max_n = 20
    mock_settings.return_value.trade_entry_multiple_capture_enabled = True
    mock_day.return_value = {
        "trades": [
            {
                "id": "a",
                "status": "CLOSED",
                "symbol": "NIFTY",
                "side": "CALL",
                "strike": 1,
                "entryPremium": 10,
                "closedAt": datetime(2026, 11, 10, 10, 0, 0, tzinfo=IST).isoformat(),
            },
        ],
    }
    with patch("app.engines.nx_exit_audit.read_premium_tape", return_value=[]):
        rep = generate_nx_exit_audit("2026-11-10")
    assert rep["status"] == "ok"
    assert rep["closedTradeCount"] == 1
    assert len(rep["trades"]) == 1
