"""Power hour — top trades only after 15:00 IST."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.power_hour_guards import (
    check_power_hour_session_allowed,
    in_power_hour_window,
)
from app.models.schemas import AutoTraderState, SymbolSnapshot, MarketPhase

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
    )


@patch("app.engines.power_hour_guards.get_market_phase", return_value="LIVE_MARKET")
@patch("app.engines.power_hour_guards._minutes_now", return_value=15 * 60 + 10)
def test_power_hour_window_active(_mins, _phase):
    assert in_power_hour_window() is True


@patch("app.engines.power_hour_guards.get_market_phase", return_value="LIVE_MARKET")
@patch("app.engines.power_hour_guards._minutes_now", return_value=14 * 60 + 59)
def test_before_power_hour_inactive(_mins, _phase):
    assert in_power_hour_window() is False


@patch("app.engines.power_hour_guards.in_power_hour_window", return_value=True)
@patch(
    "app.engines.power_hour_guards.snapshots_have_power_hour_top_signal",
    return_value=False,
)
def test_power_hour_blocks_without_top_radar(_top, _window):
    state = AutoTraderState()
    ok, reason, _meta = check_power_hour_session_allowed(state, {"NIFTY": _snap()})
    assert ok is False
    assert reason == "power_hour_top_only"


@patch("app.engines.power_hour_guards.in_power_hour_window", return_value=True)
@patch(
    "app.engines.power_hour_guards.snapshots_have_power_hour_top_signal",
    return_value=True,
)
def test_power_hour_allows_top_radar(_top, _window):
    state = AutoTraderState()
    ok, reason, meta = check_power_hour_session_allowed(state, {"NIFTY": _snap()})
    assert ok is True
    assert reason == "ok"
    assert meta.get("powerHourTopSignal") is True
