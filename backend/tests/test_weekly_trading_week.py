"""Weekly dashboard Mon–Fri trading week window."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.weekly_dashboard import _daily_breakdown, _trading_week_bounds, _weekday_dates

IST = ZoneInfo("Asia/Kolkata")


def test_trading_week_bounds_wednesday():
    wed = datetime(2026, 7, 8, 12, 0, tzinfo=IST)  # Wednesday
    mon, fri, through = _trading_week_bounds(wed)
    assert mon == "2026-07-06"
    assert fri == "2026-07-10"
    assert through == "2026-07-08"


def test_trading_week_bounds_saturday():
    sat = datetime(2026, 7, 11, 10, 0, tzinfo=IST)  # Saturday
    mon, fri, through = _trading_week_bounds(sat)
    assert mon == "2026-07-06"
    assert fri == "2026-07-10"
    assert through == "2026-07-10"


def test_weekday_dates_fills_mon_fri():
    days = _weekday_dates("2026-07-06", "2026-07-10")
    assert days == ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"]


@patch("app.engines.weekly_dashboard.get_settings")
def test_daily_breakdown_includes_zero_trade_days(mock_settings):
    s = mock_settings.return_value
    s.expiry_cheap_premium_threshold_inr = 55.0
    s.expiry_cheap_premium_lot_cap = 20
    s.expiry_low_tqs_lot_cap_tqs = 40.0
    s.expiry_low_tqs_lot_cap = 15
    s.expiry_scalp_min_symbol_tqs = 38.0
    s.quick_sideways_high_premium_threshold_inr = 90.0

    trades = [{
        "openedAt": "2026-07-07T10:00:00+05:30",
        "pnlInr": 1000,
        "side": "PUT",
        "entryPremium": 80,
        "lots": 5,
        "entryContext": {"selectionMode": "scalp", "tqs": 45, "breadth": "BEARISH"},
    }]
    rows = _daily_breakdown(trades, "2026-07-06", "2026-07-08")
    assert len(rows) == 3
    assert rows[0]["trades"] == 0
    assert rows[1]["trades"] == 1
    assert rows[0]["weekday"] == "Mon"
