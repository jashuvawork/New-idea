"""Trade store purge — clears persisted logs that block session gates."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.models.schemas import PaperTrade, Side, StrategyType
from app.services import trade_store

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def isolated_store(tmp_path):
    store = tmp_path / "trades"
    store.mkdir()
    trade_store._store_dir = store
    trade_store._log_path = store / "trades.log"
    yield store
    trade_store._store_dir = None
    trade_store._log_path = None
    from app.engines import auto_trader

    auto_trader._auto_trader_state = None
    auto_trader._state_loaded = False


def test_purge_removes_day_files_and_clears_log(isolated_store):
    day = isolated_store / "2026-07-01.json"
    day.write_text(json.dumps({"date": "2026-07-01", "trades": [{"id": "1", "status": "CLOSED"}], "events": []}))
    log = isolated_store / "trades.log"
    log.write_text('{"type":"TRADE_CLOSED"}\n' * 100)

    batches = isolated_store / "batches"
    batches.mkdir()
    (batches / "batch-001.json").write_text("{}")
    (isolated_store / "session_meta.json").write_text('{"lastResetAt": "2026-07-01T09:00:00+05:30"}')

    result = trade_store.purge_all_trade_data()

    assert not day.exists()
    assert log.read_text() == "" or "PURGE_ALL" in log.read_text()
    assert not (batches / "batch-001.json").exists()
    assert result["removedCount"] >= 3
    assert trade_store.get_milestone_batch_offset() == 0
    assert trade_store.count_today_trades()["closed"] == 0
    assert not (isolated_store / "session_meta.json").exists()


def test_open_trade_mark_restores_peak_and_trail_after_restart(isolated_store):
    trade = PaperTrade(
        id="restart-peak",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24000,
        entryPremium=100.0,
        currentPremium=100.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"instrumentKey": "NSE_FO|12345"},
    )
    trade_store.record_trade_opened(trade, trade.entryContext)
    trade.currentPremium = 145.0
    trade.bestPnlPoints = 45.0
    trade.maxLtp = 145.0
    trade.maxLtpAt = datetime.now(IST)
    trade.entryContext.update({
        "explosionTrailFloorPts": 36.0,
        "stageTrailFloorPts": 30.0,
    })
    trade_store.record_trade_mark(trade)

    restored = PaperTrade(**trade_store.load_open_trades()[0])
    assert restored.bestPnlPoints == 45.0
    assert restored.maxLtp == 145.0
    assert restored.entryContext["explosionTrailFloorPts"] == 36.0
    assert restored.entryContext["stageTrailFloorPts"] == 30.0


def test_process_restart_and_session_reset_preserve_open_trade(isolated_store):
    from app.engines import auto_trader

    trade = PaperTrade(
        id="restart-open",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24350,
        entryPremium=42.7,
        currentPremium=49.45,
        lots=2,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={
            "instrumentKey": "NSE_FO|restart",
            "brokerOrderId": "entry-1",
        },
    )
    trade_store.record_trade_opened(trade, trade.entryContext)

    auto_trader._auto_trader_state = None
    auto_trader._state_loaded = False
    state = auto_trader.get_state()
    assert [row.id for row in state.openPaperTrades] == ["restart-open"]

    auto_trader.reset_session()
    reset_state = auto_trader.get_state()
    persisted = trade_store.load_open_trades()

    assert [row.id for row in reset_state.openPaperTrades] == ["restart-open"]
    assert [row["id"] for row in persisted] == ["restart-open"]
    assert persisted[0]["status"] == "OPEN"


def test_trade_close_is_persisted_exactly_once(isolated_store):
    trade = PaperTrade(
        id="exactly-once-close",
        symbol="SENSEX",
        side=Side.CALL,
        strike=77700,
        entryPremium=378.05,
        currentPremium=410.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
    )
    trade_store.record_trade_opened(trade)
    trade.status = "CLOSED"
    trade.exitReason = "target"
    trade.closedAt = datetime.now(IST)

    assert trade_store.record_trade_closed(trade) is True
    assert trade_store.record_trade_closed(trade) is False

    day = trade_store.get_day_detail(datetime.now(IST).strftime("%Y-%m-%d"))
    closes = [
        event for event in day["events"]
        if event.get("type") == "TRADE_CLOSED"
        and event.get("tradeId") == trade.id
    ]
    assert len(closes) == 1


def test_closed_trade_restart_keeps_points_and_peak(isolated_store):
    from app.engines import auto_trader

    opened = datetime.now(IST)
    trade = PaperTrade(
        id="5708f6d3",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22050,
        entryPremium=585.93,
        currentPremium=585.93,
        lots=6,
        openedAt=opened,
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"selectionMode": "explosion"},
    )
    trade_store.record_trade_opened(trade, trade.entryContext)
    trade.currentPremium = 597.75
    trade.pnlPoints = 9.528897435897436
    trade.pnlInr = 3716.27
    trade.bestPnlPoints = 29.62
    trade.maxLtp = 615.55
    trade.maxLtpAt = datetime.now(IST)
    trade.status = "CLOSED"
    trade.exitReason = "explosion_tp_rung_floor"
    trade.closedAt = datetime.now(IST)
    assert trade_store.record_trade_closed(trade, trade.entryContext) is True

    auto_trader._auto_trader_state = None
    auto_trader._state_loaded = False
    state = auto_trader.get_state()
    restored = next(row for row in state.closedPaperTrades if row.id == "5708f6d3")

    assert restored.pnlInr == pytest.approx(3716.27)
    assert restored.pnlPoints == pytest.approx(9.528897435897436)
    assert restored.bestPnlPoints == pytest.approx(29.62)
    assert restored.maxLtp == pytest.approx(615.55)
    assert restored.maxLtpAt is not None
    assert restored.exitReason == "explosion_tp_rung_floor"


def test_closed_trade_restart_fills_points_when_archive_omits_them(isolated_store):
    from app.engines import auto_trader

    now = datetime.now(IST)
    day = now.strftime("%Y-%m-%d")
    trade_store._save_day(day, {
        "date": day,
        "trades": [{
            "id": "legacy-close",
            "symbol": "NIFTY",
            "side": "CALL",
            "strike": 22050,
            "entryPremium": 100.0,
            "currentPremium": 112.5,
            "lots": 1,
            "pnlInr": 812.5,
            "status": "CLOSED",
            "exitReason": "target",
            "strategyType": "EXPLOSIVE",
            "openedAt": now.isoformat(),
            "closedAt": now.isoformat(),
            "entryContext": {"bestPnlPoints": 18.0},
        }],
        "events": [],
    })

    auto_trader._auto_trader_state = None
    auto_trader._state_loaded = False
    state = auto_trader.get_state()
    restored = next(row for row in state.closedPaperTrades if row.id == "legacy-close")

    assert restored.pnlPoints == pytest.approx(12.5)
    assert restored.bestPnlPoints == pytest.approx(18.0)
