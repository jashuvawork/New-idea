"""Chart structure entry waivers — open reclaim + morning continuation (CE/PE)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.chart_structure_entry import (
    chart_structure_open_reclaim_ok,
    index_continuation_chart_structure_ok,
)
from app.models.schemas import ChartAnalysis, Side

IST = ZoneInfo("Asia/Kolkata")
WHEN = datetime(2026, 11, 19, 9, 35, tzinfo=IST)


def _snap(*, spot: float, vwap_reclaim: str, pivot_p: float):
    return SimpleNamespace(
        spot=spot,
        chartAnalysis=ChartAnalysis(
            pivots={"P": pivot_p},
            vwap={"reclaim": vwap_reclaim, "vwap": pivot_p},
        ),
    )


@patch("app.engines.index_tick_helpers.resolve_index_session")
@patch("app.engines.advanced_indicators.index_vwap_confirms_side", return_value=True)
def test_call_open_reclaim_upper_range_vwap(_vwap, mock_sess):
    mock_sess.return_value = {"hi": 83_200.0, "lo": 82_800.0, "last": 83_100.0}
    snap = _snap(spot=83_100.0, vwap_reclaim="BULLISH_RECLAIM", pivot_p=82_950.0)
    ok, meta = chart_structure_open_reclaim_ok(
        "SENSEX", "CALL", snap, settings=Settings(), when=WHEN,
    )
    assert ok, meta
    assert meta.get("openChartStructureReclaimWaiver") is True
    assert meta["rangePosition"] >= 0.60 - 1e-6


@patch("app.engines.index_tick_helpers.resolve_index_session")
@patch("app.engines.advanced_indicators.index_vwap_confirms_side", return_value=False)
def test_call_open_reclaim_rejects_low_range(_vwap, mock_sess):
    mock_sess.return_value = {"hi": 83_200.0, "lo": 82_800.0, "last": 82_850.0}
    snap = _snap(spot=82_850.0, vwap_reclaim="NONE", pivot_p=82_950.0)
    ok, meta = chart_structure_open_reclaim_ok(
        "SENSEX", "CALL", snap, settings=Settings(), when=WHEN,
    )
    assert not ok
    assert meta.get("chartStructureReason") == "call_range_too_low"


@patch("app.engines.advanced_indicators.index_vwap_confirms_side", return_value=True)
def test_index_continuation_chart_structure_morning(_vwap):
    snap = _snap(spot=83_100.0, vwap_reclaim="BULLISH_RECLAIM", pivot_p=83_000.0)
    when = datetime(2026, 11, 19, 11, 0, tzinfo=IST)
    ok, meta = index_continuation_chart_structure_ok(
        "CALL", snap, settings=Settings(), when=when,
    )
    assert ok, meta


@patch("app.engines.advanced_indicators.index_vwap_confirms_side", return_value=True)
def test_index_continuation_chart_structure_closed_after_noon(_vwap):
    snap = _snap(spot=83_100.0, vwap_reclaim="BULLISH_RECLAIM", pivot_p=83_000.0)
    when = datetime(2026, 11, 19, 13, 0, tzinfo=IST)
    ok, meta = index_continuation_chart_structure_ok(
        "CALL", snap, settings=Settings(), when=when,
    )
    assert not ok
    assert meta.get("chartStructureReason") == "after_morning_window"