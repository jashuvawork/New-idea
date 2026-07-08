"""Tests for forward signals engine."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.engines.forward_signals_engine import build_forward_signals, _build_moments
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    PremarketAnalysis,
    Regime,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-07-09",
        spot=77600.0,
        regime=Regime.CHOP,
        tradeQualityScore=34.0,
        breadth=Breadth(bias="BULLISH", score=55, aligned=True),
        premarket=PremarketAnalysis(openPlay="GAP_AND_GO", confidence=72.0, gapDirection="GAP_UP"),
        explosionAlerts=[
            {
                "symbol": "SENSEX",
                "side": "PUT",
                "strike": 76900.0,
                "premium": 400.0,
                "explosionScore": 78.0,
                "tier": "EXPLODING",
                "dailyMovePct": 4520.0,
                "tradeable": True,
                "allDayExplosion": True,
                "reason": "volAwaken×48k",
            },
        ],
        swingAlerts=[
            {
                "symbol": "SENSEX",
                "side": "PUT",
                "strike": 77000.0,
                "premium": 200.0,
                "swingType": "PCR_EXTREME",
                "confidence": 65.0,
                "reason": "test",
                "targetPct": 30.0,
                "stopPct": 12.0,
                "maxHoldDays": 3,
                "tradeable": True,
            },
        ],
    )


def test_build_moments_has_power_hour():
    moments = _build_moments()
    ids = [m["id"] for m in moments]
    assert "power_hour" in ids
    assert "all_day_explosion" in ids


def test_forward_signals_includes_explosion_and_moments():
    state = AutoTraderState()
    report = build_forward_signals({"SENSEX": _snap()}, state)
    assert report.get("moments")
    horizons = {s["horizon"] for s in report.get("signals") or []}
    assert "EXPLOSION" in horizons
    assert "SWING" in horizons
    assert report.get("tradeableCount", 0) >= 1
