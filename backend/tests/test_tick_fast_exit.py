"""Tick-fast exit path — WS LTP overlay and scan scheduling."""

import asyncio
import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.auto_trader import _record_observed_max_ltp, _trade_premium_velocity
from app.engines.snapshot_fast import overlay_snapshot_ltps, resolve_trade_premium
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    ChartAnalysis,
    HeatmapStrike,
    MarketPhase,
    MarketProfile,
    PaperTrade,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)
from app.services.tick_store import clear, get_velocity_pct, record_tick
from app.services.upstox import INDEX_KEYS

IST = ZoneInfo("Asia/Kolkata")


def _snap(strike: float = 24000, call_ltp: float = 100.0, put_ltp: float = 95.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        breadth=Breadth(score=50, bias="NEUTRAL", aligned=False),
        heatmap=[
            HeatmapStrike(
                strike=strike,
                callLtp=call_ltp,
                putLtp=put_ltp,
                callInstrumentKey="NSE_FO|12345",
                putInstrumentKey="NSE_FO|67890",
            ),
        ],
    )


def test_resolve_trade_premium_prefers_ws_tick():
    clear()
    record_tick("NSE_FO|67890", 88.5)
    snap = _snap()
    premium = resolve_trade_premium(snap, 24000, Side.PUT, "NSE_FO|67890")
    assert premium == 88.5


@patch("app.services.tick_store.time.monotonic")
def test_option_tick_velocity_uses_fresh_three_second_tape(mock_mono):
    clear()
    mock_mono.side_effect = [100.0, 101.5, 103.0, 103.1]
    record_tick("NSE_FO|67890", 100.0)
    record_tick("NSE_FO|67890", 110.0)
    record_tick("NSE_FO|67890", 130.0)

    assert get_velocity_pct("NSE_FO|67890", window_seconds=3.0) == 30.0


@patch("app.services.tick_store.time.monotonic")
def test_trade_velocity_prefers_websocket_leg_over_snapshot(mock_mono):
    clear()
    mock_mono.side_effect = [200.0, 203.0, 203.1]
    record_tick("NSE_FO|67890", 120.0)
    record_tick("NSE_FO|67890", 108.0)
    trade = PaperTrade(
        id="peak-put",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24000,
        entryPremium=100.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"instrumentKey": "NSE_FO|67890"},
    )

    assert _trade_premium_velocity(_snap(), trade) == -10.0


def test_observed_max_ltp_is_sticky_across_pullback():
    trade = PaperTrade(
        id="peak-call",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24000,
        entryPremium=100.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
    )
    _record_observed_max_ltp(trade, 180.0)
    peak_at = trade.maxLtpAt
    _record_observed_max_ltp(trade, 172.0)

    assert trade.maxLtp == 180.0
    assert trade.maxLtpAt == peak_at
    assert trade.entryContext["givebackFromMaxLtpPoints"] == 8.0


def test_observed_max_ltp_ignores_corrupt_persisted_peak():
    trade = PaperTrade(
        id="peak-recovery",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24000,
        entryPremium=100.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"maxLtp": "not-a-number"},
    )

    _record_observed_max_ltp(trade, 125.0)
    assert trade.maxLtp == 125.0


def test_every_websocket_tick_captures_open_trade_peak_before_exit_throttle():
    import app.engines.auto_trader as auto_trader

    clear()
    trade = PaperTrade(
        id="sub-cycle-peak",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24000,
        entryPremium=100.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"instrumentKey": "NSE_FO|67890"},
    )
    auto_trader._auto_trader_state = AutoTraderState(openPaperTrades=[trade])
    try:
        record_tick("NSE_FO|67890", 115.0)
        record_tick("NSE_FO|67890", 102.0)
        assert trade.maxLtp == 115.0
    finally:
        auto_trader._auto_trader_state = AutoTraderState()


def test_overlay_snapshot_spot_charts_refreshes_rsi():
    from app.engines.snapshot_fast import overlay_snapshot_spot_charts

    clear()
    record_tick(INDEX_KEYS["NIFTY"], 24233.2)

    recent = [24000 + i * 2 for i in range(20)] + [24030.0]
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24030.0,
        spotChart=SpotChart(direction="BEARISH", spot=24030.0, rsi=22.0, macdBias="BEARISH"),
        chartAnalysis=ChartAnalysis(
            consensus="NEUTRAL",
            recentCloses=recent,
            ichimoku={"cloudBias": "BULLISH", "priceVsCloud": "ABOVE"},
        ),
        marketProfile=MarketProfile(poc=24100, openingRangeHigh=24200, openingRangeLow=23900),
    )
    out = overlay_snapshot_spot_charts({"NIFTY": snap})
    refreshed = out["NIFTY"]
    assert refreshed.spot == 24233.2
    assert refreshed.spotChart.rsi > 50


def test_overlay_snapshot_ltps_updates_heatmap():
    clear()
    record_tick("NSE_FO|67890", 91.0)
    snap = _snap(put_ltp=80.0)
    out = overlay_snapshot_ltps({"NIFTY": snap})
    row = out["NIFTY"].heatmap[0]
    assert row.putLtp == 91.0


@patch("app.routers.market.get_settings")
@patch("app.routers.market.get_state")
@patch("app.routers.market.is_ws_active")
def test_can_run_tick_fast_requires_open_trades(mock_ws, mock_state, mock_settings):
    from app.routers.market import can_run_tick_fast, _cache

    settings = MagicMock()
    settings.tick_fast_exit_enabled = True
    mock_settings.return_value = settings
    mock_ws.return_value = True

    import app.routers.market as market_mod
    market_mod._cache = MagicMock(dataReady=True)

    st = MagicMock()
    st.openPaperTrades = []
    mock_state.return_value = st
    assert not can_run_tick_fast()

    st.openPaperTrades = [MagicMock()]
    assert can_run_tick_fast()


@patch("app.routers.market.get_settings")
def test_entry_scan_due_after_interval(mock_settings):
    import app.routers.market as market_mod
    from app.routers.market import entry_scan_due, mark_full_scan_done

    settings = MagicMock()
    settings.entry_scan_interval_ms = 250
    mock_settings.return_value = settings

    market_mod._last_full_scan_mono = 0.0
    assert entry_scan_due()

    mark_full_scan_done()
    assert not entry_scan_due()


def test_three_overlapping_cycles_close_one_trade_exactly_once():
    """A third cycle during persistence skips the already-CLOSED listed trade."""
    import app.engines.auto_trader as auto_trader
    from app.config import get_settings

    trade = PaperTrade(
        id="nifty-24300-ce",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24300,
        entryPremium=75.05,
        currentPremium=86.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=30.75,
        maxLtp=105.80,
        entryContext={
            "instrumentKey": "NSE_FO|24300CE",
            "selectionMode": "explosion",
            "ictFlatThenVertical": True,
            "maxProfitCapture": True,
        },
    )
    state = AutoTraderState(openPaperTrades=[trade])
    auto_trader._auto_trader_state = state
    auto_trader._state_loaded = True
    settings = get_settings().model_copy(
        update={
            "adaptive_exits_enabled": False,
            "edge_engine_enabled": False,
            "explosion_capture_mode": True,
            "enable_live_trading": False,
            "auto_trading_enabled": True,
            "paper_live_parity_enabled": True,
            "paper_simulate_broker_orders": True,
        }
    )
    snapshots = {"NIFTY": _snap(strike=24300, call_ltp=86.0)}
    first_at_broker_await = asyncio.Event()
    release_broker = asyncio.Event()
    persistence_started = threading.Event()
    release_persistence = threading.Event()
    broker_calls = 0

    async def simulated_exit(_client, _trade, _current):
        nonlocal broker_calls
        broker_calls += 1
        call_number = broker_calls
        first_at_broker_await.set()
        await release_broker.wait()
        return {
            "order_id": f"exit-{call_number}",
            "fill_premium": 86.0,
        }

    def persist_close(_trade, _ctx):
        if record_closed.call_count > 1:
            return
        persistence_started.set()
        assert release_persistence.wait(timeout=1)

    async def replay_overlap():
        full_cycle = asyncio.create_task(
            auto_trader.process(snapshots, client=MagicMock())
        )
        await asyncio.wait_for(first_at_broker_await.wait(), timeout=1)
        tick_fast_cycle = asyncio.create_task(
            auto_trader.process_exits_only(snapshots, client=MagicMock())
        )
        await asyncio.wait_for(asyncio.shield(tick_fast_cycle), timeout=1)
        assert not full_cycle.done()
        release_broker.set()
        assert await asyncio.to_thread(persistence_started.wait, 1)
        assert trade.status == "CLOSED"
        assert trade in state.openPaperTrades
        assert trade.id not in auto_trader._exit_claims

        third_cycle = asyncio.create_task(
            auto_trader.process_exits_only(snapshots, client=MagicMock())
        )
        await asyncio.wait_for(third_cycle, timeout=1)
        assert not full_cycle.done()

        release_persistence.set()
        await full_cycle

    with (
        patch.object(auto_trader, "get_settings", return_value=settings),
        patch.object(auto_trader, "get_market_phase", return_value="CLOSED"),
        patch.object(
            auto_trader,
            "evaluate_explosion_exit",
            return_value=("explosion_peak_capture", 10.95 * 65),
        ),
        patch.object(auto_trader, "simulate_exit_order", side_effect=simulated_exit),
        patch.object(
            auto_trader.trade_store,
            "record_trade_closed",
            side_effect=persist_close,
        ) as record_closed,
        patch("app.services.trade_store.record_trade_report") as record_report,
        patch("app.services.radar_learning.record_funnel_state"),
        patch("app.engines.snapshot_lag_analyzer.build_trade_close_report", return_value={}),
        patch(
            "app.engines.explosion_detector.consume_armed_base_anchor",
        ) as consume_anchor,
    ):
        asyncio.run(replay_overlap())

    assert broker_calls == 1
    assert record_closed.call_count == 1
    assert record_report.call_count == 1
    assert [t.id for t in state.closedPaperTrades] == ["nifty-24300-ce"]
    assert state.openPaperTrades == []
    assert trade.entryContext["brokerExitOrderId"] == "exit-1"
    assert trade.entryContext["maxLtp"] == 105.80
    consume_anchor.assert_called_once_with(
        "NIFTY", 24300, Side.CALL, closed_at=trade.closedAt,
    )


def test_failed_broker_exit_releases_claim_for_next_cycle_retry():
    import app.engines.auto_trader as auto_trader
    from app.config import get_settings

    trade = PaperTrade(
        id="nifty-24300-pe-retry",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24300,
        entryPremium=75.05,
        currentPremium=60.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"instrumentKey": "NSE_FO|24300PE"},
    )
    state = AutoTraderState(openPaperTrades=[trade])
    auto_trader._auto_trader_state = state
    auto_trader._state_loaded = True
    settings = get_settings().model_copy(
        update={
            "adaptive_exits_enabled": False,
            "edge_engine_enabled": False,
            "explosion_capture_mode": True,
            "enable_live_trading": False,
            "auto_trading_enabled": True,
            "paper_live_parity_enabled": True,
            "paper_simulate_broker_orders": True,
        }
    )
    snapshots = {"NIFTY": _snap(strike=24300, put_ltp=60.0)}
    broker_calls = 0

    async def fail_then_succeed(_client, _trade, _current):
        nonlocal broker_calls
        broker_calls += 1
        if broker_calls == 1:
            raise auto_trader.UpstoxError("temporary broker failure")
        return {"order_id": "exit-retry-2", "fill_premium": 60.0}

    async def run_failure_then_retry():
        await auto_trader.process_exits_only(snapshots, client=MagicMock())
        assert trade.status == "OPEN"
        assert trade.id not in auto_trader._exit_claims
        await auto_trader.process_exits_only(snapshots, client=MagicMock())

    with (
        patch.object(auto_trader, "get_settings", return_value=settings),
        patch.object(
            auto_trader,
            "evaluate_explosion_exit",
            return_value=("explosion_stop_loss", -15.05 * 65),
        ),
        patch.object(auto_trader, "simulate_exit_order", side_effect=fail_then_succeed),
        patch.object(auto_trader.trade_store, "record_trade_closed") as record_closed,
        patch("app.services.trade_store.record_trade_report"),
        patch("app.engines.snapshot_lag_analyzer.build_trade_close_report", return_value={}),
    ):
        asyncio.run(run_failure_then_retry())

    assert broker_calls == 2
    assert record_closed.call_count == 1
    assert state.openPaperTrades == []
    assert [t.id for t in state.closedPaperTrades] == [trade.id]
    assert trade.entryContext["brokerExitOrderId"] == "exit-retry-2"
    assert trade.id not in auto_trader._exit_claims


def test_entry_path_rejects_immediate_reentry_at_exhausted_ftv_high():
    from app.engines.auto_trader import _open_from_candidate
    from app.engines.trade_selector import EntryCandidate

    closed = PaperTrade(
        id="nifty-24300-ce-first-spike",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24300,
        entryPremium=75.05,
        currentPremium=86.0,
        lots=1,
        openedAt=datetime.now(IST),
        closedAt=datetime.now(IST),
        status="CLOSED",
        exitReason="explosion_peak_capture",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=10.95 * 65,
        pnlPoints=10.95,
        bestPnlPoints=30.75,
        maxLtp=105.80,
        entryContext={
            "selectionMode": "explosion",
            "ictFlatThenVertical": True,
            "maxProfitCapture": True,
        },
    )
    candidate = EntryCandidate(
        symbol="NIFTY",
        snap=_snap(strike=24300, call_ltp=108.02),
        mode="explosion",
        score=95.0,
        side=Side.CALL,
        strike=24300,
        premium=108.02,
        strategy_type=StrategyType.EXPLOSIVE,
        confidence=95.0,
        tqs=95.0,
        tier="ELITE",
        explosion_event=SimpleNamespace(velocity_3s=3.0),
    )

    opened, reason = asyncio.run(
        _open_from_candidate(
            candidate,
            AutoTraderState(closedPaperTrades=[closed]),
        )
    )

    assert opened is False
    assert reason == "exhausted_ftv_requires_new_base_reacceleration"
