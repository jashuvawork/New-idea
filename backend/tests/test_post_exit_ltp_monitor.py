"""Post-exit LTP monitor — peak after close and early-exit flags."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.post_exit_ltp_monitor import (
    post_exit_monitor_hud,
    register_post_exit_watch,
    tick_post_exit_monitors,
)
from app.models.schemas import (
    Breadth,
    MarketPhase,
    PaperTrade,
    Regime,
    Side,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=24000.0,
        atmStrike=24000.0,
        dataAvailable=True,
        regime=Regime.RANGE_BOUND,
        breadth=Breadth(bias="NEUTRAL", score=55.0, aligned=False),
    )


def _trade(*, exit_prem: float = 70.0) -> PaperTrade:
    now = datetime(2026, 11, 23, 10, 0, 0, tzinfo=IST)
    return PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=25600.0,
        entryPremium=72.4,
        currentPremium=exit_prem,
        lots=8,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=now - timedelta(seconds=72),
        closedAt=now,
        status="CLOSED",
        exitReason="explosion_failed_launch",
        sessionDate="2026-11-23",
        bestPnlPoints=1.5,
        maxLtp=73.9,
        entryContext={},
    )


@pytest.fixture(autouse=True)
def _clear_watches():
    import app.engines.post_exit_ltp_monitor as mod

    with mod._lock:
        mod._active.clear()
        mod._recent.clear()
    yield
    with mod._lock:
        mod._active.clear()
        mod._recent.clear()


@patch("app.engines.post_exit_ltp_monitor.get_settings")
def test_register_and_tick_raises_peak(mock_settings):
    s = MagicMock()
    s.post_exit_ltp_monitor_enabled = True
    s.post_exit_ltp_monitor_seconds = 120
    s.trade_entry_multiple_capture_max_n = 20
    s.post_exit_ltp_monitor_early_min_points = 5.0
    s.post_exit_ltp_monitor_early_min_missed_n = 1
    mock_settings.return_value = s

    import app.engines.post_exit_ltp_monitor as mod

    trade = _trade(exit_prem=69.85)
    trade.closedAt = datetime.now(IST)
    register_post_exit_watch(trade, exit_premium=69.85)
    with mod._lock:
        watch = mod._active["t1"]
        watch.monitor_until = datetime.now(IST) + timedelta(hours=2)
    with patch(
        "app.engines.post_exit_ltp_monitor.resolve_trade_premium",
        return_value=110.0,
    ):
        tick_post_exit_monitors({"NIFTY": _snap()})
    hud = post_exit_monitor_hud()
    assert hud["active"]
    assert hud["active"][0]["postExitPeakLtp"] == 110.0


@patch("app.engines.post_exit_ltp_monitor.get_settings")
def test_finalize_flags_early_exit(mock_settings):
    s = MagicMock()
    s.post_exit_ltp_monitor_enabled = True
    s.post_exit_ltp_monitor_seconds = 1
    s.trade_entry_multiple_capture_max_n = 20
    s.post_exit_ltp_monitor_early_min_points = 5.0
    s.post_exit_ltp_monitor_early_min_missed_n = 1
    mock_settings.return_value = s

    import app.engines.post_exit_ltp_monitor as mod

    trade = _trade(exit_prem=69.85)
    trade.closedAt = datetime.now(IST) - timedelta(seconds=30)
    register_post_exit_watch(trade, exit_premium=69.85)
    with mod._lock:
        mod._active["t1"].monitor_until = datetime.now(IST) - timedelta(seconds=1)
    with (
        patch(
            "app.engines.post_exit_ltp_monitor.resolve_trade_premium",
            return_value=125.0,
        ),
        patch("app.services.trade_store.merge_closed_trade_post_exit_monitor") as merge,
        patch("app.services.trade_store.record_post_exit_monitor_report"),
        patch("app.services.radar_learning.record_funnel_event"),
    ):
        finalized = tick_post_exit_monitors({"NIFTY": _snap()})
    assert finalized
    assert finalized[0]["earlyExitLikely"] is True
    assert finalized[0]["missedPointsAfterExit"] >= 50
    merge.assert_called_once()