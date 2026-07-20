"""WS overlay must not deep-clone full SymbolSnapshot trees."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.snapshot_fast import overlay_snapshot_ltps, overlay_snapshot_spot_charts
from app.models.schemas import (
    Breadth,
    ExplosiveRunner,
    HeatmapStrike,
    MarketPhase,
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
        spot=24200.0,
        heatmap=[
            HeatmapStrike(
                strike=24200.0,
                callLtp=50.0,
                putLtp=40.0,
                callInstrumentKey="NSE_FO|C1",
                putInstrumentKey="NSE_FO|P1",
            ),
            HeatmapStrike(
                strike=24250.0,
                callLtp=30.0,
                putLtp=55.0,
                callInstrumentKey="NSE_FO|C2",
                putInstrumentKey="NSE_FO|P2",
            ),
        ],
        explosiveRunner=ExplosiveRunner(strike=24200.0, side=Side.CALL, premium=50.0),
        breadth=Breadth(bias="BULLISH", score=60, aligned=True),
        spotChart=SpotChart(direction="BULLISH", spot=24200.0, timeframe="5m"),
    )


@patch("app.engines.snapshot_fast.get_ltp")
def test_ltp_overlay_shares_unmutated_rows(mock_ltp):
    mock_ltp.side_effect = lambda key, max_age_seconds=1.0: {
        "NSE_FO|C1": 51.5,
    }.get(key)

    original = _snap()
    untouched_row = original.heatmap[1]
    out = overlay_snapshot_ltps({"NIFTY": original})
    updated = out["NIFTY"]

    assert updated is not original
    assert updated.heatmap[0].callLtp == 51.5
    # Unmutated row object is shared (proves no deep tree clone)
    assert updated.heatmap[1] is untouched_row
    # Original row object not mutated in place
    assert original.heatmap[0].callLtp == 50.0


@patch("app.engines.spot_direction.refresh_spot_chart_live")
@patch("app.engines.snapshot_fast.get_index_spot", return_value=24210.0)
def test_spot_overlay_is_shallow(_mock_spot, mock_refresh):
    chart = SpotChart(direction="BULLISH", spot=24210.0, timeframe="5m")
    mock_refresh.return_value = chart

    original = _snap()
    heatmap_ref = original.heatmap
    out = overlay_snapshot_spot_charts({"NIFTY": original})
    updated = out["NIFTY"]

    assert updated is not original
    assert updated.spot == 24210.0
    # Heatmap list shared — shallow clone did not rebuild nested tree
    assert updated.heatmap is heatmap_ref
