"""Tests for EOD next-day playbook engine."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.eod_playbook_engine import (
    build_eod_playbook,
    in_eod_playbook_window,
    next_trading_day,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    ChartAnalysis,
    MarketPhase,
    Regime,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(symbol: str = "SENSEX", expiry: str = "2026-07-09") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=expiry,
        spot=77600.0,
        regime=Regime.CHOP,
        tradeQualityScore=34.0,
        breadth=Breadth(bias="BEARISH", score=45, aligned=True),
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.15, momentum30Pct=-0.4),
        chartAnalysis=ChartAnalysis(
            consensus="BEARISH",
            alignedCount=4,
            totalTimeframes=5,
            timeframes={"5m": {"direction": "BEARISH"}},
        ),
        explosionAlerts=[
            {
                "symbol": symbol,
                "side": "PUT",
                "strike": 76500.0,
                "explosionScore": 88.0,
                "tier": "ELITE",
            },
        ],
        topExplosion={"side": "PUT", "strike": 76500.0, "explosionScore": 88.0},
        pcr=1.15,
        maxPain=77500.0,
    )


def test_next_trading_day_skips_weekend():
    fri = datetime(2026, 7, 10, 16, 0, tzinfo=IST)  # Friday
    assert next_trading_day(fri) == "2026-07-13"


@patch("app.engines.eod_playbook_engine._minutes_now", return_value=16 * 60)
def test_in_eod_window_after_1520(_mins):
    assert in_eod_playbook_window() is True


@patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-08")
def test_build_eod_playbook_bearish_bias(_today):
    state = AutoTraderState()
    pb = build_eod_playbook(
        {"SENSEX": _snap(), "NIFTY": _snap("NIFTY", "2026-07-14")},
        state,
        target_date="2026-07-09",
    )
    assert pb["targetDate"] == "2026-07-09"
    assert pb["bias"] in ("PUT", "BOTH", "STAND_ASIDE")
    assert len(pb["scenarios"]) >= 3
    assert len(pb["watchlist"]) >= 1
    assert len(pb["playbook"]) >= 4
