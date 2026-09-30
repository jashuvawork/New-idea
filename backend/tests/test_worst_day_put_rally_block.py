"""Symmetric guard — block PUT chase into bullish index (Sep 30 pattern)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.worst_day_guard import worst_day_blocks_put_rally, worst_day_allows_candidate
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _bullish_snap(symbol: str = "SENSEX") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=82000.0,
        regime=Regime.TREND_EXPANSION,
        tradeQualityScore=55.0,
        breadth=Breadth(bias="BULLISH", score=62, aligned=True),
        spotChart=SpotChart(
            direction="BULLISH",
            emaBias="BULLISH",
            momentum5Pct=0.12,
            trendStrength=55,
        ),
    )


class _Cand:
    def __init__(self, side=Side.PUT, symbol="SENSEX", alert=None):
        self.side = side
        self.symbol = symbol
        self.mode = "explosion"
        self.tier = "ELITE"
        self.score = 88.0
        self.snap = _bullish_snap(symbol)
        self.alert = alert or {}
        self.pretrade_meta = {}


@patch("app.engines.index_tick_helpers.index_trend_breakout")
def test_blocks_put_on_bullish_breakout_without_fingerprint(mock_bo):
    mock_bo.side_effect = lambda sym, side, snap: (
        {"breakout": True} if side == "CALL" else {"breakout": False}
    )
    blocked, reason = worst_day_blocks_put_rally(
        _Cand(), AutoTraderState(), {"SENSEX": _bullish_snap()},
    )
    assert blocked is True
    assert reason == "worst_day_put_blocked_bullish_rally"


@patch("app.engines.index_tick_helpers.index_trend_breakout", return_value={"breakout": False})
def test_allows_put_slide_off_high_near_base(mock_bo):
    cand = _Cand(
        alert={
            "tier": "ELITE",
            "offHighMovePct": 8.0,
            "localBaseMovePct": 10.0,
        },
    )
    blocked, reason = worst_day_blocks_put_rally(
        cand, AutoTraderState(), {"SENSEX": _bullish_snap()},
    )
    assert blocked is False
    assert reason == "ok"


@patch("app.engines.index_tick_helpers.index_trend_breakout", return_value={"breakout": False})
def test_call_unaffected(mock_bo):
    blocked, reason = worst_day_blocks_put_rally(
        _Cand(side=Side.CALL), AutoTraderState(), {"SENSEX": _bullish_snap()},
    )
    assert blocked is False


@patch("app.engines.worst_day_guard.worst_day_blocks_put_rally", return_value=(True, "worst_day_put_blocked_bullish_rally"))
@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("NORMAL", {}))
def test_worst_day_allows_candidate_denies_blocked_put(mock_policy, mock_put_block):
    ok, reason, _ = worst_day_allows_candidate(
        _Cand(), AutoTraderState(), {"SENSEX": _bullish_snap()},
    )
    assert not ok
    assert reason == "worst_day_put_blocked_bullish_rally"
