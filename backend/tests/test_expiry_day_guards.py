"""Tests for expiry-day guards and worst-day prediction."""

from dataclasses import dataclass
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.expiry_day_guards import (
    check_expiry_candidate,
    check_expiry_entry_allowed,
    expiry_pm_itm_chart_bypass_allowed,
    in_expiry_evening_block,
    in_expiry_morning_window,
    in_expiry_pm_itm_window,
    is_near_expiry_day,
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


def test_expiry_afternoon_allows_all_day_explosion():
    """Afternoon expiry session must not hard-block when all-day explosion window is live."""
    from app.engines.expiry_day_guards import check_expiry_entry_allowed

    state = AutoTraderState()
    snaps = {"SENSEX": _snap(expiry="2026-07-09")}
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-09"):
        with patch("app.engines.expiry_day_guards._minutes_now", return_value=14 * 60 + 30):
            with patch("app.engines.expiry_day_guards.expiry_pm_itm_quick_session_active", return_value=False):
                with patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=False):
                    with patch("app.engines.expiry_day_guards.predict_worst_expiry_day", return_value=(False, 0, [])):
                        with patch("app.engines.expiry_day_guards.expiry_trades_cap_reached", return_value=(False, "")):
                            with patch("app.engines.morning_premium_capture.in_all_day_explosion_window", return_value=True):
                                ok, reason, meta = check_expiry_entry_allowed(state, snaps)
    assert ok is True
    assert reason == "ok"
    assert meta.get("expiryAfternoonExplosionAllowed") is True


def test_expiry_evening_block_entries():
    state = AutoTraderState()
    snaps = {"NIFTY": _snap()}
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-06-30"):
        with patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=True):
            with patch("app.engines.expiry_day_guards.in_expiry_pm_itm_window", return_value=False):
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
        with patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET"):
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
        with patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET"):
            with patch("app.engines.expiry_day_guards._minutes_now", return_value=9 * 60 + 22):
                blocked, reason = check_expiry_explosion_open_block(
                    snap=snap,
                    tier="ELITE",
                    side=Side.PUT,
                    breadth=snap.breadth,
                )
    assert blocked is False


def test_near_expiry_day_includes_tomorrow():
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-06"):
        assert is_near_expiry_day(_snap(expiry="2026-07-07")) is True
        assert is_near_expiry_day(_snap(expiry="2026-07-08")) is False


@patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET")
def test_in_expiry_pm_itm_window(mock_phase):
    with patch("app.engines.expiry_day_guards.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 6, 14, 30, tzinfo=IST)
        assert in_expiry_pm_itm_window() is True
    with patch("app.engines.expiry_day_guards.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 6, 13, 30, tzinfo=IST)
        assert in_expiry_pm_itm_window() is False


def test_pm_itm_evening_block_allows_quick_entries():
    state = AutoTraderState()
    snaps = {"NIFTY": _snap(expiry="2026-07-07")}
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-06"):
        with patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=True):
            with patch("app.engines.expiry_day_guards.in_expiry_pm_itm_window", return_value=True):
                ok, reason, meta = check_expiry_entry_allowed(state, snaps)
    assert ok is True
    assert reason == "ok"
    assert meta.get("expiryPmItmQuickActive") is True
    assert meta.get("expiryPmItmQuickOnly") is True


@dataclass
class _Cand:
    symbol: str
    side: Side
    strike: float
    score: float
    mode: str
    snap: SymbolSnapshot


def test_check_expiry_candidate_pm_itm_requires_itm_quick():
    state = AutoTraderState()
    snap = _snap(expiry="2026-07-07")
    snap.spot = 24450.0
    snap.atmStrike = 24450.0
    snaps = {"NIFTY": snap}

    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-06"):
        with patch("app.engines.expiry_day_guards.in_expiry_pm_itm_window", return_value=True):
            ok, reason, meta = check_expiry_candidate(
                _Cand("NIFTY", Side.CALL, 24300.0, 58.0, "quick_sideways", snap),
                state, snaps,
            )
    assert ok is True
    assert meta.get("expiryPmItmQuick") is True

    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-06"):
        with patch("app.engines.expiry_day_guards.in_expiry_pm_itm_window", return_value=True):
            ok, reason, _ = check_expiry_candidate(
                _Cand("NIFTY", Side.CALL, 24500.0, 58.0, "quick_sideways", snap),
                state, snaps,
            )
    assert ok is False
    assert reason == "expiry_pm_itm_strike_only"


@patch("app.engines.expiry_day_guards.get_settings")
def test_pm_itm_chart_bypass_when_breadth_aligned(mock_settings):
    s = mock_settings.return_value
    s.expiry_pm_itm_chart_bypass_breadth = True
    snap = _snap(expiry="2026-07-07")
    snap.breadth = Breadth(bias="BULLISH", score=65, aligned=True)
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-06"):
        with patch("app.engines.expiry_day_guards.in_expiry_pm_itm_window", return_value=True):
            assert expiry_pm_itm_chart_bypass_allowed(Side.CALL, snap, mode="quick_sideways") is True
    snap.breadth = Breadth(bias="BEARISH", score=65, aligned=True)
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-06"):
        with patch("app.engines.expiry_day_guards.in_expiry_pm_itm_window", return_value=True):
            assert expiry_pm_itm_chart_bypass_allowed(Side.PUT, snap, mode="quick_sideways") is True
            assert expiry_pm_itm_chart_bypass_allowed(Side.CALL, snap, mode="scalp") is False
