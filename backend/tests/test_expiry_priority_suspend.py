"""Conditional expiry-index priority suspend after symbol loss / whip."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.bad_day_routing import (
    cross_index_alternate_for_suspend,
    cross_index_rank_adjustment,
    expiry_index_priority_suspended,
)
from app.engines.pretrade_validator import TradeRecord
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


def _snap(
    symbol: str = "NIFTY",
    expiry: str | None = None,
    tqs: float = 38.0,
    mom5: float = 0.01,
) -> SymbolSnapshot:
    if expiry is None:
        expiry = datetime.now(IST).strftime("%Y-%m-%d")
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=expiry,
        spot=24480.0 if symbol == "NIFTY" else 78500.0,
        atmStrike=24500.0 if symbol == "NIFTY" else 78500.0,
        regime=Regime.CHOP,
        tradeQualityScore=tqs,
        breadth=Breadth(bias="BEARISH", score=58, aligned=False),
        spotChart=SpotChart(direction="NEUTRAL", momentum5Pct=mom5, trendStrength=20),
    )


class _Cand:
    def __init__(self, symbol, side=Side.PUT, score=70.0, snap=None):
        self.symbol = symbol
        self.side = side
        self.score = score
        self.mode = "explosion"
        self.tier = "EXPLODING"
        self.snap = snap


def _state() -> AutoTraderState:
    return AutoTraderState()


@patch("app.engines.bad_day_routing.collect_session_trades")
def test_suspend_on_symbol_loss_inr(mock_trades):
    mock_trades.return_value = [
        TradeRecord("NIFTY", "PUT", -1800, strike=24500),
        TradeRecord("NIFTY", "PUT", -2000, strike=24400),
    ]
    snaps = {"NIFTY": _snap("NIFTY")}
    ok, reasons = expiry_index_priority_suspended("NIFTY", _state(), snaps)
    assert ok
    assert any(r.startswith("symbol_loss") for r in reasons)


@patch("app.engines.bad_day_routing.collect_session_trades")
def test_suspend_on_repeated_material_losses(mock_trades):
    mock_trades.return_value = [
        TradeRecord("NIFTY", "PUT", -800, strike=24500),
        TradeRecord("NIFTY", "CALL", -700, strike=24600),
    ]
    snaps = {"NIFTY": _snap("NIFTY")}
    ok, reasons = expiry_index_priority_suspended("NIFTY", _state(), snaps)
    assert ok
    assert any("same_symbol_losses" in r for r in reasons)


def test_alternate_picker_skips_punished_symbol():
    far = (datetime.now(IST) + timedelta(days=7)).strftime("%Y-%m-%d")
    snaps = {
        "NIFTY": _snap("NIFTY", tqs=30),
        "SENSEX": _snap("SENSEX", expiry=far, tqs=45),
    }
    assert cross_index_alternate_for_suspend("NIFTY", snaps) == "SENSEX"


@patch("app.engines.bad_day_routing.collect_session_trades")
def test_nearest_rank_penalty_when_suspended(mock_trades):
    mock_trades.return_value = [TradeRecord("NIFTY", "PUT", -4000, strike=24500)]
    today = datetime.now(IST).strftime("%Y-%m-%d")
    far = (datetime.now(IST) + timedelta(days=7)).strftime("%Y-%m-%d")
    nifty = _snap("NIFTY", expiry=today, tqs=35)
    sensex = _snap("SENSEX", expiry=far, tqs=40)
    snaps = {"NIFTY": nifty, "SENSEX": sensex}
    state = _state()
    cand = _Cand("NIFTY", snap=nifty)
    bonus = cross_index_rank_adjustment(cand, state, snaps)
    assert bonus < 0


@patch("app.engines.bad_day_routing.collect_session_trades")
def test_alternate_bonus_when_nearest_suspended(mock_trades):
    mock_trades.return_value = [TradeRecord("NIFTY", "PUT", -4000, strike=24500)]
    today = datetime.now(IST).strftime("%Y-%m-%d")
    far = (datetime.now(IST) + timedelta(days=7)).strftime("%Y-%m-%d")
    nifty = _snap("NIFTY", expiry=today, tqs=35)
    sensex = _snap("SENSEX", expiry=far, tqs=42)
    snaps = {"NIFTY": nifty, "SENSEX": sensex}
    state = _state()
    cand = _Cand("SENSEX", snap=sensex)
    bonus = cross_index_rank_adjustment(cand, state, snaps)
    assert bonus > 20.0