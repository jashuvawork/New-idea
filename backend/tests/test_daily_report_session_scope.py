"""Daily report and in-memory closed trades must scope to today's session."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.engines.daily_profit_strategy import DailyCalibration
from app.engines.session_trade_integrity import (
    closed_trades_for_session_day,
    prune_prior_session_closed_trades,
    resolve_trade_session_date,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")
_TODAY = datetime.now(IST).strftime("%Y-%m-%d")
_YESTERDAY = "2026-09-10"


def _closed(
    *,
    session_date: str,
    pnl: float = -710.0,
    trade_id: str = "50fc9677",
) -> PaperTrade:
    opened = datetime.fromisoformat(f"{session_date}T14:40:39+05:30")
    closed = datetime.fromisoformat(f"{session_date}T14:41:08+05:30")
    return PaperTrade(
        id=trade_id,
        symbol="SENSEX",
        side=Side.PUT,
        strike=75000.0,
        entryPremium=371.4,
        currentPremium=371.7,
        lots=24,
        pnlInr=pnl,
        strategyType=StrategyType.EXPLOSIVE,
        status="CLOSED",
        exitReason="explosion_trail_lock",
        openedAt=opened,
        closedAt=closed,
        sessionDate=session_date,
    )


def test_resolve_trade_session_date_prefers_session_date_field():
    trade = _closed(session_date=_YESTERDAY)
    assert resolve_trade_session_date(trade) == _YESTERDAY


def test_build_report_scopes_to_session_day():
    cal = DailyCalibration()
    report = cal.build_report(
        [_closed(session_date=_YESTERDAY), _closed(session_date=_TODAY, pnl=1200.0, trade_id="today-win")],
        session_date=_TODAY,
    )
    assert report.wins == 1
    assert report.losses == 0
    assert report.netPnlInr == 1200.0


def test_build_report_default_is_today_only():
    cal = DailyCalibration()
    report = cal.build_report([_closed(session_date=_YESTERDAY)])
    assert report.wins == 0
    assert report.losses == 0
    assert report.netPnlInr == 0.0


def test_prune_prior_session_closed_trades():
    state = AutoTraderState(
        closedPaperTrades=[
            _closed(session_date=_YESTERDAY),
            _closed(session_date=_TODAY, pnl=500.0, trade_id="today"),
        ]
    )
    pruned = prune_prior_session_closed_trades(state)
    assert pruned == 1
    assert len(state.closedPaperTrades) == 1
    assert state.closedPaperTrades[0].id == "today"
    assert closed_trades_for_session_day(state.closedPaperTrades) == state.closedPaperTrades
