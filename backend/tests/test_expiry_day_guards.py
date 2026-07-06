"""Tests for expiry-day guards and worst-day prediction."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.expiry_day_guards import (
    check_expiry_entry_allowed,
    in_expiry_evening_block,
    in_expiry_morning_window,
    is_symbol_expiry_day,
    predict_worst_expiry_day,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    PaperTrade,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(symbol: str = "NIFTY", expiry: str = "2026-06-30") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=expiry,
        spot=24000.0,
        regime=Regime.RANGE_BOUND,
        breadth=Breadth(bias="BEARISH", score=42, aligned=False),
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.05,
            trendStrength=30,
            dataAvailable=True,
        ),
    )


def test_is_symbol_expiry_day():
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-06-30"):
        assert is_symbol_expiry_day(_snap()) is True
        assert is_symbol_expiry_day(_snap(expiry="2026-07-03")) is False


def test_morning_vs_evening_windows():
    with patch("app.engines.expiry_day_guards.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 30, 10, 0, tzinfo=IST)
        assert in_expiry_morning_window() is True
        assert in_expiry_evening_block() is False

    with patch("app.engines.expiry_day_guards.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 30, 14, 30, tzinfo=IST)
        assert in_expiry_morning_window() is False
        assert in_expiry_evening_block() is True


def test_predict_worst_expiry_day():
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="a", symbol="NIFTY", side=Side.PUT, strike=24000,
            entryPremium=50, currentPremium=45, lots=10,
            pnlInr=-5000, openedAt=datetime.now(IST), status="CLOSED",
        ),
        PaperTrade(
            id="b", symbol="NIFTY", side=Side.CALL, strike=23900,
            entryPremium=50, currentPremium=45, lots=10,
            pnlInr=-6000, openedAt=datetime.now(IST), status="CLOSED",
        ),
    ]
    snaps = {"NIFTY": _snap()}
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-06-30"):
        with patch("app.engines.expiry_day_guards.compute_session_pnl", return_value=-15000):
            is_worst, score, reasons = predict_worst_expiry_day(state, snaps)
    assert is_worst is True
    assert score >= 55
    assert "chop_regime" in reasons
    assert "bearish_sideways" in reasons


def test_expiry_evening_block_entries():
    state = AutoTraderState()
    snaps = {"NIFTY": _snap()}
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-06-30"):
        with patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=True):
            ok, reason, meta = check_expiry_entry_allowed(state, snaps)
    assert ok is False
    assert reason == "expiry_evening_block"
    assert meta["expirySymbols"] == ["NIFTY"]


@patch("app.engines.expiry_day_guards.get_settings")
def test_expiry_open_block_exploding(mock_settings):
    from app.engines.expiry_day_guards import check_expiry_explosion_open_block

    s = mock_settings.return_value
    s.expiry_day_guards_enabled = True
    s.entry_earliest_hour = 9
    s.entry_earliest_minute = 20
    s.expiry_explosion_open_block_minutes = 5
    snap = _snap(expiry="2026-06-30")
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-06-30"):
        with patch("app.engines.expiry_day_guards.get_market_phase", return_value="LIVE_MARKET"):
            with patch("app.engines.expiry_day_guards._minutes_now", return_value=9 * 60 + 22):
                blocked, reason = check_expiry_explosion_open_block(
                    snap=snap,
                    tier="EXPLODING",
                    side=Side.PUT,
                    breadth=snap.breadth,
                )
    assert blocked is True
    assert reason == "expiry_open_block_exploding"


@patch("app.engines.expiry_day_guards.get_settings")
def test_expiry_open_allows_elite_aligned(mock_settings):
    from app.engines.expiry_day_guards import check_expiry_explosion_open_block

    s = mock_settings.return_value
    s.expiry_day_guards_enabled = True
    s.entry_earliest_hour = 9
    s.entry_earliest_minute = 20
    s.expiry_explosion_open_block_minutes = 5
    snap = _snap(expiry="2026-06-30")
    snap.breadth = Breadth(bias="BEARISH", score=70, aligned=True)
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-06-30"):
        with patch("app.engines.expiry_day_guards.get_market_phase", return_value="LIVE_MARKET"):
            with patch("app.engines.expiry_day_guards._minutes_now", return_value=9 * 60 + 22):
                blocked, reason = check_expiry_explosion_open_block(
                    snap=snap,
                    tier="ELITE",
                    side=Side.PUT,
                    breadth=snap.breadth,
                )
    assert blocked is False
