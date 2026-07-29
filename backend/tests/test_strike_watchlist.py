"""Dual-index CE/PE strike watchlist for live + next-day priority."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.engines.strike_watchlist import build_strike_watchlist
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Regime,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(symbol: str, *, alerts=None, runners=None, atm: float = 24200.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=atm + 10,
        atmStrike=atm,
        optionExpiry="2026-07-30",
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=55.0,
        breadth=Breadth(bias="BULLISH", score=70, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.1),
        explosionAlerts=alerts or [],
        explosiveRunnerWatchlist=runners or [],
    )


def test_both_indexes_have_ce_and_pe():
    snaps = {
        "NIFTY": _snap(
            "NIFTY",
            atm=24200,
            alerts=[
                {
                    "side": "CALL", "strike": 24100, "premium": 210,
                    "explosionScore": 80, "tier": "ELITE", "dailyMovePct": 40,
                    "velocity3s": 2.0, "tradeable": True, "reason": "rip",
                },
                {
                    "side": "PUT", "strike": 24300, "premium": 90,
                    "explosionScore": 55, "tier": "EXPLODING", "dailyMovePct": 22,
                    "velocity3s": 1.2, "tradeable": True, "reason": "put",
                },
            ],
        ),
        "SENSEX": _snap(
            "SENSEX",
            atm=77600,
            alerts=[
                {
                    "side": "CALL", "strike": 77500, "premium": 280,
                    "explosionScore": 100, "tier": "ELITE", "dailyMovePct": 30,
                    "velocity3s": 1.6, "tradeable": True, "reason": "elite",
                },
            ],
            runners=[
                {"side": "PUT", "strike": 77800, "premium": 120, "score": 48,
                 "premiumVelocityPct": 3.0, "elite": False},
            ],
        ),
    }
    wl = build_strike_watchlist(snaps, per_side=2)
    by_sym = {i["symbol"]: i for i in wl["indexes"]}
    assert "NIFTY" in by_sym and "SENSEX" in by_sym
    assert by_sym["NIFTY"]["calls"][0]["strike"] == 24100
    assert by_sym["NIFTY"]["puts"][0]["strike"] == 24300
    assert by_sym["SENSEX"]["calls"][0]["strike"] == 77500
    assert by_sym["SENSEX"]["puts"][0]["strike"] == 77800
    assert wl["priorityQueue"][0]["symbol"] in ("NIFTY", "SENSEX")
    assert wl["priorityQueue"][0]["side"] in ("CALL", "PUT")


def test_atm_fallback_when_no_radar():
    snaps = {"NIFTY": _snap("NIFTY", atm=24200), "SENSEX": _snap("SENSEX", atm=77600)}
    wl = build_strike_watchlist(snaps, per_side=1)
    for idx in wl["indexes"]:
        assert idx["calls"] and idx["calls"][0]["tier"] == "ATM"
        assert idx["puts"] and idx["puts"][0]["tier"] == "ATM"
