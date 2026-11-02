"""#676 flip capture guards — CE/PE symmetric entry infra (not pad ranking)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.mtf_chart_analysis import TimeframeChartRead, validate_mtf_scalp
from app.engines.pad676_flip_capture_guard import (
    pad676_defer_opposite_after_mtf_fade_blocked,
    pad676_defer_put_after_ce_fade_blocked,
    pad676_flip_capture_entry_blocked,
    pad676_put_into_index_rally_blocked,
    pad676_session_tape_blocks_side,
    premium_mtf_opposes_entry_side,
    record_pad676_ce_mtf_fade_reject,
    record_pad676_mtf_fade_reject,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
NOON = datetime(2026, 11, 2, 12, 6, tzinfo=IST)


def _snap(spot: float = 23350.0):
    chart = SimpleNamespace(
        rsi=52.0,
        macdBias="NEUTRAL",
        macdHistogram=0.0,
        momentum5Pct=0.24,
    )
    return SimpleNamespace(symbol="NIFTY", spot=spot, spotChart=chart, timestamp=NOON)


def _candidate(side: Side, *, spot: float = 23350.0):
    return SimpleNamespace(
        symbol="NIFTY",
        side=side,
        strike=23550.0 if side == Side.PUT else 23300.0,
        snap=_snap(spot),
        mode="explosion",
    )


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_session_tape_blocks_put_on_bullish_open(mock_session):
    mock_session.return_value = {"open": 23222.0, "last": 23350.0, "hi": 23360.0, "lo": 23211.0}
    s = Settings(pad676_session_tape_align_enabled=True)
    blocked, reason, _ = pad676_session_tape_blocks_side(
        "NIFTY", Side.PUT, _snap(), when=NOON, settings=s,
    )
    assert blocked and reason == "pad676_session_put_on_bullish_tape"


@patch("app.engines.index_tick_helpers.resolve_index_session")
@patch("app.engines.index_rally_side_flip.index_rally_metrics")
def test_put_into_rally_blocked_on_chop_rally(mock_metrics, mock_session):
    mock_session.return_value = {"open": 23222.0, "last": 23350.0, "hi": 23360.0, "lo": 23211.0}
    mock_metrics.return_value = {
        "rallyPoints": 98.0,
        "slidePoints": 10.0,
        "minMovePoints": 45.0,
        "momentum5Pct": 0.2,
    }
    blocked, reason, _ = pad676_put_into_index_rally_blocked(
        "NIFTY", Side.PUT, _snap(), day_mode="CHOP + RALLY",
    )
    assert blocked and reason == "pad676_put_into_index_rally"


def test_premium_mtf_opposing_put():
    premium_mtf = {
        "5m": TimeframeChartRead(
            label="5m", direction="BULLISH", momentumPct=5.8, trendStrength=80,
        ),
    }
    blocked, reason = premium_mtf_opposes_entry_side(Side.PUT, premium_mtf)
    assert blocked and reason == "exec_mtf_premium_5m_opposing_put"


def test_defer_put_after_ce_fade_reject():
    record_pad676_ce_mtf_fade_reject(
        "NIFTY", Side.CALL, "exec_mtf_premium_5m_fading", now=NOON,
    )
    blocked, reason = pad676_defer_put_after_ce_fade_blocked(
        "NIFTY", Side.PUT, now=NOON + timedelta(seconds=30),
    )
    assert blocked and reason == "pad676_defer_put_after_ce_mtf_fade_reject"


def test_defer_call_after_pe_fade_reject_symmetric():
    record_pad676_mtf_fade_reject(
        "NIFTY", Side.PUT, "exec_mtf_premium_5m_fading", now=NOON,
    )
    blocked, reason = pad676_defer_opposite_after_mtf_fade_blocked(
        "NIFTY", Side.CALL, now=NOON + timedelta(seconds=15),
    )
    assert blocked and reason == "pad676_defer_call_after_pe_mtf_fade_reject"


@patch("app.engines.index_tick_helpers.resolve_index_session")
@patch("app.engines.index_rally_side_flip.index_rally_metrics")
def test_pretrade_bundle_blocks_put(mock_metrics, mock_session):
    mock_session.return_value = {"open": 23222.0, "last": 23350.0, "hi": 23360.0, "lo": 23211.0}
    mock_metrics.return_value = {
        "rallyPoints": 98.0,
        "slidePoints": 10.0,
        "minMovePoints": 45.0,
        "momentum5Pct": 0.2,
    }
    blocked, reason, _ = pad676_flip_capture_entry_blocked(
        _candidate(Side.PUT),
        day_mode="CHOP + RALLY",
    )
    assert blocked
    assert reason in {
        "pad676_session_put_on_bullish_tape",
        "pad676_put_into_index_rally",
        "pad676_defer_put_after_ce_mtf_fade_reject",
    }


@patch("app.engines.index_tick_helpers.resolve_index_session")
@patch("app.engines.mtf_chart_analysis.get_settings")
def test_mtf_bypass_still_blocks_opposing_put_premium(mock_settings, mock_session):
    mock_session.return_value = {"open": 23222.0, "last": 23350.0, "hi": 23360.0, "lo": 23211.0}
    mock_settings.return_value = Settings(
        execution_mtf_enabled=True,
        execution_chart_premium_check_enabled=True,
        execution_chart_min_premium_momentum_pct=-0.15,
        pad676_premium_mtf_opposing_block_enabled=True,
        pad676_premium_mtf_opposing_min_momentum_pct=0.45,
    )
    index_mtf = {
        "1m": TimeframeChartRead(label="1m", direction="BEARISH", momentumPct=-0.01, trendStrength=20),
        "5m": TimeframeChartRead(label="5m", direction="BEARISH", momentumPct=-0.01, trendStrength=22),
        "15m": TimeframeChartRead(label="15m", direction="BEARISH", momentumPct=-0.1, trendStrength=17),
        "1h": TimeframeChartRead(label="1h", direction="NEUTRAL", momentumPct=0, trendStrength=10),
        "4h": TimeframeChartRead(label="4h", direction="NEUTRAL", momentumPct=0, trendStrength=10),
    }
    premium_mtf = {
        "5m": TimeframeChartRead(label="5m", direction="BULLISH", momentumPct=5.0, trendStrength=90),
        "1m": TimeframeChartRead(label="1m", direction="NEUTRAL", momentumPct=0, trendStrength=0),
    }
    ok, reason, _ = validate_mtf_scalp(
        Side.PUT,
        index_mtf,
        premium_mtf,
        pad_lane_bypass=True,
        first_lift_bypass=True,
        symbol="NIFTY",
        snap=_snap(),
    )
    assert not ok and reason == "exec_mtf_premium_5m_opposing_put"
