"""Allow PUT explosions when live 5m chart is bearish but OI breadth still bullish."""

from app.engines.aligned_side_guard import breadth_hard_blocks_side
from app.engines.morning_premium_capture import _market_opposes_side
from app.models.schemas import Side, SpotChart, SymbolSnapshot


def test_breadth_allows_put_when_live_chart_bearish():
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-07-15T12:57:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=24071.0,
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.49, trendStrength=35.0),
    )
    blocked, reason = breadth_hard_blocks_side(Side.PUT, "BULLISH", snap=snap)
    assert not blocked
    assert reason == "ok"


def test_market_does_not_oppose_put_on_bearish_live_chart():
    chart = SpotChart(direction="BEARISH", momentum5Pct=-0.49, trendStrength=35.0)
    assert not _market_opposes_side(Side.PUT, "BULLISH", chart)
