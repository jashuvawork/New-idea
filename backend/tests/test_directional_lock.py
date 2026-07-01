"""Directional side lock — BULLISH = CE only, no CE↔PE switch."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.directional_lock import (
    check_directional_side_lock,
    check_directional_side_lock_simple,
    market_direction,
    record_trade_side,
    reset_directional_lock,
    session_locked_side,
)
from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.directional_side_lock_enabled = True
    s.directional_sticky_per_symbol = True
    s.directional_lock_use_chart = True
    s.directional_lock_block_chart_counter = True
    return s


def _snap(
    symbol: str = "NIFTY",
    bias: str = "BULLISH",
    chart_dir: str = "NEUTRAL",
) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        breadth=Breadth(bias=bias),
        spotChart=SpotChart(direction=chart_dir),
    )


@patch("app.engines.directional_lock.get_settings", _settings)
def test_bullish_blocks_put():
    blocked, reason = check_directional_side_lock("NIFTY", Side.PUT, _snap(bias="BULLISH"))
    assert blocked
    assert reason == "directional_lock_bullish_ce_only"


@patch("app.engines.directional_lock.get_settings", _settings)
def test_bearish_blocks_call():
    blocked, reason = check_directional_side_lock("NIFTY", Side.CALL, _snap(bias="BEARISH"))
    assert blocked
    assert reason == "directional_lock_bearish_pe_only"


@patch("app.engines.directional_lock.get_settings", _settings)
def test_chart_counter_blocks_put_on_bullish_chart():
    blocked, reason = check_directional_side_lock(
        "NIFTY", Side.PUT, _snap(bias="NEUTRAL", chart_dir="BULLISH"),
    )
    assert blocked
    assert reason in (
        "directional_lock_chart_bullish_ce_only",
        "directional_lock_bullish_ce_only",
    )


@patch("app.engines.directional_lock.get_settings", _settings)
def test_sticky_lock_blocks_ce_pe_switch():
    reset_directional_lock()
    snap = _snap(bias="NEUTRAL", chart_dir="NEUTRAL")
    record_trade_side("NIFTY", Side.CALL, snap)
    assert session_locked_side("NIFTY") == "CALL"

    blocked, reason = check_directional_side_lock("NIFTY", Side.PUT, snap)
    assert blocked
    assert "directional_lock_no_ce_pe_switch_CALL_locked" in reason


@patch("app.engines.directional_lock.get_settings", _settings)
def test_bullish_trade_locks_call_even_if_first_side_was_put_attempt_blocked():
    reset_directional_lock()
    snap = _snap(bias="BULLISH")
    record_trade_side("NIFTY", Side.CALL, snap)
    assert session_locked_side("NIFTY") == "CALL"


@patch("app.engines.directional_lock.get_settings", _settings)
def test_market_direction_prefers_breadth():
    assert market_direction(_snap(bias="BULLISH", chart_dir="BEARISH")) == "BULLISH"


@patch("app.engines.directional_lock.get_settings", _settings)
def test_simple_lock_blocks_put_on_bullish_breadth():
    blocked, reason = check_directional_side_lock_simple("NIFTY", Side.PUT, "BULLISH")
    assert blocked
    assert reason == "directional_lock_bullish_ce_only"


@patch("app.engines.directional_lock.get_settings", _settings)
def test_reset_clears_sticky_lock():
    reset_directional_lock()
    record_trade_side("NIFTY", Side.CALL, _snap(bias="NEUTRAL"))
    assert session_locked_side("NIFTY") == "CALL"
    reset_directional_lock()
    assert session_locked_side("NIFTY") is None
