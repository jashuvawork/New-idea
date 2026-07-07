"""Weekly dashboard aggregation."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.weekly_dashboard import (
    build_weekly_dashboard,
    detect_policy_violations,
)
from app.models.schemas import AutoTraderState

IST = ZoneInfo("Asia/Kolkata")


def _trade(**kwargs) -> dict:
    base = {
        "id": "t1",
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 24500.0,
        "entryPremium": 28.9,
        "lots": 75,
        "pnlInr": -12471.0,
        "openedAt": "2026-07-07T10:09:32+05:30",
        "closedAt": "2026-07-07T10:10:00+05:30",
        "status": "CLOSED",
        "strategyType": "SCALP",
        "entryContext": {
            "selectionMode": "scalp",
            "tqs": 37.6,
            "breadth": "BULLISH",
            "psychology": "NEUTRAL",
        },
    }
    base.update(kwargs)
    return base


@patch("app.engines.weekly_dashboard.get_settings")
def test_detect_policy_violations_cheap_premium(mock_settings):
    s = mock_settings.return_value
    s.expiry_cheap_premium_threshold_inr = 55.0
    s.expiry_cheap_premium_lot_cap = 20
    s.expiry_low_tqs_lot_cap_tqs = 40.0
    s.expiry_low_tqs_lot_cap = 15
    s.expiry_scalp_min_symbol_tqs = 38.0
    s.quick_sideways_high_premium_threshold_inr = 90.0

    violations = detect_policy_violations(_trade())
    assert any(v.startswith("cheap_premium") for v in violations)


@patch("app.engines.weekly_dashboard.get_settings")
def test_detect_counter_breadth_call(mock_settings):
    s = mock_settings.return_value
    s.expiry_cheap_premium_threshold_inr = 55.0
    s.expiry_cheap_premium_lot_cap = 20
    s.expiry_low_tqs_lot_cap_tqs = 40.0
    s.expiry_low_tqs_lot_cap = 15
    s.expiry_scalp_min_symbol_tqs = 38.0
    s.quick_sideways_high_premium_threshold_inr = 90.0

    t = _trade(
        symbol="SENSEX",
        side="CALL",
        entryPremium=225.6,
        lots=5,
        entryContext={"selectionMode": "explosion", "tqs": 33.5, "breadth": "BEARISH"},
    )
    assert "counter_breadth_call" in detect_policy_violations(t)


@patch("app.engines.weekly_dashboard.trade_store.get_session_reset_at", return_value=None)
@patch("app.engines.weekly_dashboard._trades_in_window")
@patch("app.engines.weekly_dashboard.get_settings")
def test_build_weekly_dashboard_goals(mock_settings, mock_trades, mock_reset):
    s = mock_settings.return_value
    s.emergency_stop_inr = 20_000.0
    s.daily_profit_target_inr = 36_000.0
    s.expiry_max_trades_per_day = 6
    s.expiry_cheap_premium_threshold_inr = 55.0
    s.expiry_cheap_premium_lot_cap = 20
    s.expiry_low_tqs_lot_cap_tqs = 40.0
    s.expiry_low_tqs_lot_cap = 15
    s.expiry_scalp_min_symbol_tqs = 38.0
    s.quick_sideways_high_premium_threshold_inr = 90.0

    mock_trades.return_value = ([_trade()], "2026-07-07", "2026-07-07")
    state = AutoTraderState()
    state.skipped = [{"symbol": "SESSION", "reason": "worst_day_breakout_only", "message": "test"}]

    dash = build_weekly_dashboard(days=7, state=state, snapshots={})
    assert dash["summary"]["tradeCount"] == 1
    assert dash["policyViolations"]["count"] == 1
    assert dash["currentSession"]["skipped"]["total"] == 1
    assert "safety" in dash["goals"]
    assert dash["recommendation"]
