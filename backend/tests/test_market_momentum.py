"""NSE/BSE index momentum from constituent heatmap + gap."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.market_momentum import (
    exchange_for_symbol,
    index_moment_active,
    index_moment_rank_bonus,
    side_aligned_with_index_moment,
)
from app.models.schemas import (
    Breadth,
    ConstituentHeatmap,
    MarketPhase,
    PremarketAnalysis,
    Side,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(gap_direction: str = "GAP_DOWN", gap_size: str = "LARGE") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        breadth=Breadth(score=45, bias="BEARISH", aligned=True),
        premarket=PremarketAnalysis(
            gapDirection=gap_direction,
            gapSize=gap_size,
            gapPct=-0.85,
            auctionBias="BEARISH",
            explosionRisk="HIGH",
            confidence=70,
            volumeSurgeScore=60,
        ),
        constituentHeatmap=ConstituentHeatmap(
            symbol="NIFTY",
            dataAvailable=True,
            breadthPct=35,
            bias="BEARISH",
            advancing=10,
            declining=35,
        ),
    )


def test_exchange_labels():
    assert exchange_for_symbol("NIFTY") == "NSE"
    assert exchange_for_symbol("SENSEX") == "BSE"


@patch("app.engines.market_momentum.is_open_drive_window", return_value=True)
def test_gap_down_put_moment(mock_open):
    snap = _snap("GAP_DOWN", "LARGE")
    active, reason = index_moment_active(snap)
    assert active
    assert "NSE" in reason
    assert side_aligned_with_index_moment(Side.PUT, snap)
    assert not side_aligned_with_index_moment(Side.CALL, snap)
    assert index_moment_rank_bonus(snap, Side.PUT) >= 15


@patch("app.engines.market_momentum.is_open_drive_window", return_value=False)
def test_no_moment_outside_open_drive(mock_open):
    snap = _snap()
    assert not index_moment_active(snap)[0]
