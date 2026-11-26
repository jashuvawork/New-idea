"""Live broker fill + index leg hard align."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.live_entry_integrity import live_index_leg_hard_blocks_entry
from app.engines.session_trade_integrity import is_phantom_session_trade
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    PaperTrade,
    Regime,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25900.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="NEUTRAL", score=50, aligned=False),
        spotChart=SpotChart(direction="BULLISH", emaBias="BULLISH", momentum5Pct=0.4),
    )


class _Cand:
    def __init__(self, side=Side.CALL, symbol="NIFTY"):
        self.side = side
        self.symbol = symbol


def test_live_hard_blocks_call_on_slide_leg():
    s = settings_mock()
    s.enable_live_trading = True
    s.auto_trading_enabled = True
    s.live_index_leg_hard_align_enabled = True
    patches = [
        patch(
            "app.engines.index_session_dominant_trend.index_session_dominant_trend",
            return_value=("SLIDE", {"dominantTrend": "SLIDE"}),
        ),
        patch(
            "app.engines.index_tick_helpers.index_trend_breakout",
            return_value={"breakout": False},
        ),
    ]
    for p in patches:
        p.start()
    try:
        with patch("app.engines.live_entry_integrity.get_settings", return_value=s):
            blocked, reason, _ = live_index_leg_hard_blocks_entry(
                _Cand(side=Side.CALL),
                AutoTraderState(),
                {"NIFTY": _snap()},
                settings=s,
            )
        assert blocked is True
        assert reason == "live_index_leg_misaligned"
    finally:
        for p in patches:
            p.stop()


def test_live_hard_allows_call_on_rally_leg():
    s = settings_mock()
    s.enable_live_trading = True
    s.auto_trading_enabled = True
    with patch(
        "app.engines.index_session_dominant_trend.index_session_dominant_trend",
        return_value=("RALLY", {}),
    ):
        blocked, reason, _ = live_index_leg_hard_blocks_entry(
            _Cand(side=Side.CALL),
            AutoTraderState(),
            {"NIFTY": _snap()},
            settings=s,
        )
    assert blocked is False
    assert reason == "ok"


def test_phantom_live_without_broker_fill():
    trade = PaperTrade(
        id="abc",
        symbol="NIFTY",
        side=Side.CALL,
        strike=25850,
        entryPremium=200.0,
        currentPremium=200.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={
            "brokerOrderId": "123",
            "brokerSimulated": False,
            "executionMode": "LIVE",
        },
    )
    assert is_phantom_session_trade(trade) is True