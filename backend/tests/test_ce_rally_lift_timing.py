"""CE rally lift timing — at-base capture waivers; continuation entries allowed."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.ce_rally_lift_timing import (
    ce_at_armed_base_capture_ok,
    ce_cold_timing_chase_blocked,
    ce_rally_lift_ready,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
AFTERNOON = datetime(2026, 11, 2, 15, 22, tzinfo=IST)


def _snap(*, mom5: float, candle_bias: str = "NEUTRAL", direction: str = "BULLISH"):
    chart = SimpleNamespace(
        rsi=52.0,
        macdBias="BULLISH",
        macdHistogram=1.0,
        momentum5Pct=mom5,
        direction=direction,
        candleBias=candle_bias,
    )
    return SimpleNamespace(symbol="NIFTY", spot=23330.0, spotChart=chart, timestamp=AFTERNOON)


def _candidate(snap, *, local_pct: float = 13.8, ict_armed: bool = True):
    return SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL,
        strike=23050.0,
        snap=snap,
        mode="explosion",
        alert={
            "ictBaseArmed": ict_armed,
            "localBaseMovePct": local_pct,
            "firstLift": True,
        },
    )


def test_at_armed_base_inside_book_pad_band():
    ok, meta = ce_at_armed_base_capture_ok(
        _candidate(_snap(mom5=0.1), local_pct=14.0),
        settings=Settings(ce_rally_at_base_max_local_base_pct=22.0),
    )
    assert ok and meta["localBasePct"] == 14.0


def test_at_armed_base_rejects_extended_chase_pad():
    ok, _ = ce_at_armed_base_capture_ok(
        _candidate(_snap(mom5=0.1), local_pct=24.0),
        settings=Settings(ce_rally_at_base_max_local_base_pct=22.0),
    )
    assert not ok


@patch("app.engines.index_rally_side_flip.index_rally_metrics")
def test_rally_ready_on_bullish_leg(mock_metrics):
    mock_metrics.return_value = {
        "sessionHigh": 23360.0,
        "sessionLow": 23200.0,
        "spot": 23340.0,
        "rallyPoints": 140.0,
        "minMovePoints": 45.0,
    }
    ready, reason, _ = ce_rally_lift_ready("NIFTY", _snap(mom5=0.12, direction="BULLISH"))
    assert ready and reason == "ce_rally_lift_ready"


def test_cold_timing_chase_block_disabled_by_default():
    cand = _candidate(_snap(mom5=0.1), local_pct=13.81)
    blocked, reason, _ = ce_cold_timing_chase_blocked(
        cand,
        {"assessment": "COLD", "action": "block", "localBasePct": 13.81},
    )
    assert not blocked and not reason


def test_cold_timing_chase_block_opt_in():
    cand = _candidate(_snap(mom5=0.1), local_pct=13.81)
    blocked, reason, _ = ce_cold_timing_chase_blocked(
        cand,
        {"assessment": "COLD", "action": "block", "localBasePct": 13.81},
        settings=Settings(ce_cold_timing_chase_block_enabled=True),
    )
    assert blocked and reason == "ce_cold_timing_chase_past_base"
