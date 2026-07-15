"""Tests for snapshot lag analyzer."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.snapshot_lag_analyzer import analyze_snapshot_lag
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


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-07-14",
        spot=24200.0,
        regime=Regime.CHOP,
        tradeQualityScore=34.0,
        breadth=Breadth(bias="BEARISH", score=50, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.1),
        explosionAlerts=[
            {
                "symbol": "NIFTY",
                "side": "PUT",
                "strike": 23850.0,
                "premium": 183.0,
                "velocity3s": 40.0,
                "velocity9s": 100.0,
                "explosionScore": 72.0,
                "tier": "EXPLODING",
                "dailyMovePct": 200.0,
                "tradeable": True,
                "allDayExplosion": True,
            },
        ],
    )


@patch("app.engines.snapshot_lag_analyzer.find_best_entry", return_value=None)
@patch("app.engines.morning_premium_capture.in_all_day_explosion_window", return_value=True)
def test_lag_evening_block_not_misleading_on_non_expiry_afternoon(mock_all_day, mock_best):
    state = AutoTraderState()
    snap = _snap()
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-08"):
        with patch("app.engines.expiry_day_guards._minutes_now", return_value=15 * 60 + 30):
            report = analyze_snapshot_lag({"NIFTY": snap}, state)
    misleading = [m["field"] for m in report.get("misleadingLabels", [])]
    assert "expiryGuards.eveningBlock" not in misleading
    assert report.get("windows", {}).get("allDayExplosion") is True
    gaps = report.get("explosionGaps") or []
    assert any(g.get("side") == "PUT" for g in gaps)
