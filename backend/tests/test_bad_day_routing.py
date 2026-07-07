"""Tests for bad-day cross-index routing."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.bad_day_routing import (
    alternate_index_for,
    bad_day_min_rank_floor,
    check_bad_day_candidate,
    cross_index_rank_adjustment,
    expiry_index_fading,
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
    expiry: str = "2026-07-07",
    tqs: float = 38.0,
    bias: str = "BEARISH",
) -> SymbolSnapshot:
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
        breadth=Breadth(bias=bias, score=58, aligned=bias != "NEUTRAL"),
        spotChart=SpotChart(direction="NEUTRAL", momentum5Pct=0.01, trendStrength=20),
    )


class _Cand:
    def __init__(self, symbol, side, score, mode="explosion", tier="EXPLODING", snap=None):
        self.symbol = symbol
        self.side = side
        self.score = score
        self.mode = mode
        self.tier = tier
        self.snap = snap or _snap(symbol)


def _state_with_nifty_loss() -> AutoTraderState:
    state = AutoTraderState()
    state.closedPaperTrades = []
    return state


@patch("app.engines.bad_day_routing.collect_session_trades")
@patch("app.engines.bad_day_routing.compute_session_pnl", return_value=-15000)
@patch("app.engines.bad_day_routing.is_bearish_sideways_session", return_value=True)
def test_expiry_index_fading_detected(mock_bear, mock_pnl, mock_trades):
    mock_trades.return_value = [
        TradeRecord("NIFTY", "CALL", -12000, strike=24500),
    ]
    snap = _snap("NIFTY", tqs=35)
    fading, reasons = expiry_index_fading(snap, _state_with_nifty_loss(), {"NIFTY": snap})
    assert fading is True
    assert "bearish_sideways" in reasons


def test_alternate_index_skips_expiry_symbol():
    snaps = {
        "NIFTY": _snap("NIFTY", expiry="2026-07-07", tqs=35),
        "SENSEX": _snap("SENSEX", expiry="2026-07-09", tqs=40),
    }
    assert alternate_index_for("NIFTY", snaps) == "SENSEX"


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
@patch("app.engines.bad_day_routing.expiry_index_fading", return_value=(True, ["low_tqs"]))
def test_blocks_low_rank_explosion_on_fading_expiry(mock_fade, mock_bad):
    snap = _snap("NIFTY", tqs=35)
    cand = _Cand("NIFTY", Side.PUT, 65.0, tier="EXPLODING", snap=snap)
    ok, reason, _ = check_bad_day_candidate(cand, _state_with_nifty_loss(), {"NIFTY": snap})
    assert not ok
    assert "elite_only" in reason or "rank_below" in reason


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
@patch("app.engines.bad_day_routing.expiry_index_fading", return_value=(False, []))
def test_bad_day_requires_high_rank_on_sensex(mock_fade, mock_bad):
    snap = _snap("SENSEX", expiry="2026-07-09", tqs=45, bias="BEARISH")
    cand = _Cand("SENSEX", Side.CALL, 60.0, mode="explosion", tier="EXPLODING", snap=snap)
    ok, reason, _ = check_bad_day_candidate(cand, _state_with_nifty_loss(), {"SENSEX": snap})
    assert not ok
    assert "rank_below" in reason


@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={"NIFTY": ["loss"]})
@patch("app.engines.bad_day_routing.alternate_index_for", return_value="SENSEX")
def test_cross_index_bonus_for_alternate(mock_alt, mock_fading):
    nifty = _snap("NIFTY", tqs=35)
    sensex = _snap("SENSEX", expiry="2026-07-09", tqs=42, bias="BEARISH")
    cand = _Cand("SENSEX", Side.PUT, 70.0, snap=sensex)
    bonus = cross_index_rank_adjustment(cand, _state_with_nifty_loss(), {"NIFTY": nifty, "SENSEX": sensex})
    assert bonus > 0


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["session_loss"]))
def test_bad_day_min_rank_floor(mock_active):
    floor = bad_day_min_rank_floor(_state_with_nifty_loss(), {"NIFTY": _snap()})
    assert floor >= 72.0
