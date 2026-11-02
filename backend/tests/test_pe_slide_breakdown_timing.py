"""PE slide breakdown timing — at-base waivers; mid-leg PUT entries allowed."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.pe_slide_breakdown_timing import (
    pe_at_armed_base_capture_ok,
    pe_slide_breakdown_ready,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
NOON_BOUNCE = datetime(2026, 11, 2, 12, 6, tzinfo=IST)
AFTERNOON_SLIDE = datetime(2026, 11, 2, 13, 30, tzinfo=IST)


def _snap(*, mom5: float, candle_bias: str = "NEUTRAL", direction: str = "BEARISH", macd_hist: float = -1.0):
    chart = SimpleNamespace(
        rsi=48.0,
        macdBias="BEARISH" if macd_hist < 0 else "NEUTRAL",
        macdHistogram=macd_hist,
        momentum5Pct=mom5,
        direction=direction,
        candleBias=candle_bias,
    )
    return SimpleNamespace(symbol="NIFTY", spot=23300.0, spotChart=chart, timestamp=AFTERNOON_SLIDE)


def _candidate(snap, *, local_pct: float = 8.0):
    return SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23500.0,
        snap=snap,
        mode="explosion",
        alert={
            "ictBaseArmed": True,
            "localBaseMovePct": local_pct,
            "firstLift": True,
        },
    )


@patch("app.engines.index_rally_side_flip.index_rally_metrics")
def test_bounce_trap_not_pretrade_blocked(mock_metrics):
    """Bounce bar fails slide-ready (signal quality) but pretrade no longer hard-blocks."""
    mock_metrics.return_value = {
        "sessionHigh": 23360.5,
        "sessionLow": 23211.8,
        "spot": 23303.05,
        "slidePoints": 57.0,
        "minMovePoints": 45.0,
        "momentum5Pct": 0.21,
    }
    snap = _snap(mom5=0.21, candle_bias="BULLISH", direction="BEARISH", macd_hist=-4.0)
    ready, reason, _ = pe_slide_breakdown_ready("NIFTY", snap)
    assert not ready and reason == "pe_slide_bounce_trap"


def test_at_armed_base_inside_book_pad_band():
    ok, meta = pe_at_armed_base_capture_ok(
        _candidate(_snap(mom5=-0.1), local_pct=14.0),
        settings=Settings(pe_slide_at_base_max_local_base_pct=22.0),
    )
    assert ok and meta["localBasePct"] == 14.0


@patch("app.engines.index_rally_side_flip.index_rally_metrics")
def test_allows_breakdown_slide_leg(mock_metrics):
    mock_metrics.return_value = {
        "sessionHigh": 23360.5,
        "sessionLow": 23211.8,
        "spot": 23245.0,
        "slidePoints": 115.0,
        "minMovePoints": 45.0,
        "momentum5Pct": -0.15,
    }
    snap = _snap(mom5=-0.15, candle_bias="BEARISH", direction="BEARISH", macd_hist=-8.0)
    ready, reason, _ = pe_slide_breakdown_ready("NIFTY", snap)
    assert ready and reason == "pe_slide_breakdown_ready"
