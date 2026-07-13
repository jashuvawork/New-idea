"""Breadth blend — stocks vs OI conflict resolution."""

from app.engines.constituent_engine import blend_breadth, resolve_snapshot_breadth
from app.models.schemas import Breadth, ConstituentHeatmap


def test_blend_prefers_stock_bias_when_o_i_conflicts():
    stocks = Breadth(score=72.2, bias="BULLISH", aligned=True, source="stocks", stockScore=72.2)
    oi = Breadth(score=88.0, bias="BEARISH", aligned=True, source="oi", oiScore=88.0)
    blended = blend_breadth(oi, stocks)
    assert blended.bias == "BULLISH"
    assert blended.source == "blended"
    assert blended.stockScore == 72.2
    assert blended.oiScore == 88.0
    assert 75 <= blended.score <= 80


def test_resolve_snapshot_breadth_uses_constituents_when_available():
    oi = Breadth(score=88.0, bias="BEARISH", aligned=True)
    hm = ConstituentHeatmap(
        symbol="NIFTY",
        dataAvailable=True,
        breadthPct=71.7,
        bias="BULLISH",
        advancing=32,
        declining=15,
    )
    breadth = resolve_snapshot_breadth(oi, hm, use_constituents=True)
    assert breadth.bias == "BULLISH"
    assert breadth.source == "blended"


def test_resolve_snapshot_breadth_falls_back_to_o_i():
    oi = Breadth(score=78.0, bias="BEARISH", aligned=True)
    breadth = resolve_snapshot_breadth(oi, None, use_constituents=True)
    assert breadth.bias == "BEARISH"
    assert breadth.source == "oi"
