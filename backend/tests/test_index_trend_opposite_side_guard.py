"""Symmetric index rally/slide blocks opposite side before entry."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.index_trend_opposite_side_guard import index_trend_opposite_side_blocks_entry
from tests.mock_defaults import settings_mock
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


def _snap(symbol: str = "NIFTY") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=22700.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="NEUTRAL", score=50, aligned=False),
        spotChart=SpotChart(direction="NEUTRAL", emaBias="NEUTRAL", momentum5Pct=0.08),
    )


class _Cand:
    def __init__(self, side=Side.PUT, symbol="NIFTY", alert=None):
        self.side = side
        self.symbol = symbol
        self.alert = alert or {"tier": "ELITE"}
        self.pretrade_meta = {}


def _symmetric_settings():
    s = settings_mock()
    s.symmetric_best_trade_capture_enabled = True
    s.sep917_legacy_profile_enabled = True
    s.index_trend_opposite_side_block_enabled = True
    return s


def test_blocks_put_when_call_rally_armed():
    patches = [
        patch(
            "app.engines.index_tick_helpers.index_trend_breakout",
            return_value={"breakout": False},
        ),
        patch(
            "app.engines.worst_day_guard._put_rally_bullish_context",
            return_value=(False, {}),
        ),
        patch(
            "app.engines.index_trend_opposite_side_guard._resolve_trend_arms",
            return_value=(True, False, {}),
        ),
    ]
    for p in patches:
        p.start()
    try:
        with patch(
            "app.engines.index_trend_opposite_side_guard.get_settings",
            return_value=_symmetric_settings(),
        ):
            blocked, reason, _ = index_trend_opposite_side_blocks_entry(
                _Cand(side=Side.PUT),
                AutoTraderState(),
                {"NIFTY": _snap()},
            )
        assert blocked is True
        assert reason == "index_trend_put_blocked_call_rally"
    finally:
        for p in patches:
            p.stop()


def test_blocks_call_when_put_slide_armed():
    patches = [
        patch(
            "app.engines.index_tick_helpers.index_trend_breakout",
            return_value={"breakout": False},
        ),
        patch(
            "app.engines.index_trend_opposite_side_guard._resolve_trend_arms",
            return_value=(False, True, {}),
        ),
    ]
    for p in patches:
        p.start()
    try:
        with patch(
            "app.engines.index_trend_opposite_side_guard.get_settings",
            return_value=_symmetric_settings(),
        ):
            blocked, reason, _ = index_trend_opposite_side_blocks_entry(
                _Cand(side=Side.CALL),
                AutoTraderState(),
                {"NIFTY": _snap()},
            )
        assert blocked is True
        assert reason == "index_trend_call_blocked_put_slide"
    finally:
        for p in patches:
            p.stop()


def test_allows_put_with_slide_fingerprint():
    patches = [
        patch(
            "app.engines.index_tick_helpers.index_trend_breakout",
            return_value={"breakout": False},
        ),
        patch(
            "app.engines.worst_day_guard._put_rally_bullish_context",
            return_value=(True, {}),
        ),
        patch(
            "app.engines.index_trend_opposite_side_guard._resolve_trend_arms",
            return_value=(True, False, {}),
        ),
        patch(
            "app.engines.index_trend_opposite_side_guard._put_rally_bypass",
            return_value=True,
        ),
    ]
    for p in patches:
        p.start()
    try:
        with patch(
            "app.engines.index_trend_opposite_side_guard.get_settings",
            return_value=_symmetric_settings(),
        ):
            blocked, reason, _ = index_trend_opposite_side_blocks_entry(
                _Cand(side=Side.PUT),
                AutoTraderState(),
                {"NIFTY": _snap()},
            )
        assert blocked is False
        assert reason == "ok"
    finally:
        for p in patches:
            p.stop()


def test_guard_off_when_legacy_profile_disabled():
    s = Settings(
        sep917_legacy_profile_enabled=False,
        index_trend_opposite_side_block_enabled=True,
    )
    with patch("app.engines.index_trend_opposite_side_guard.get_settings", return_value=s):
        blocked, reason, _ = index_trend_opposite_side_blocks_entry(
            _Cand(side=Side.PUT),
            AutoTraderState(),
            {"NIFTY": _snap()},
        )
    assert blocked is False
