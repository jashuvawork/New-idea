"""Open bearish/bullish cash open + session-extreme V lift waiver (CE/PE)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.open_setup_guards import (
    open_caution_side_align_ok,
    open_caution_structural_side_align_waiver,
    validate_open_setup_entry,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
OPEN = datetime(2026, 11, 6, 9, 28, tzinfo=IST)


def _alert_call_v_rip(*, lb: float = 8.0, rank: float = 92.0):
    return {
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "localBaseMovePct": lb,
        "rankScore": rank,
        "causalGrade": "A",
    }


def _alert_put_v_rip(*, lb: float = 8.0, rank: float = 92.0):
    return {
        "tier": "ELITE",
        "momentType": "v_rip_session_high",
        "localBaseMovePct": lb,
        "rankScore": rank,
        "causalGrade": "A",
    }


def _cand(symbol: str, side: Side, strike: float, *, spot: float, alert: dict):
    return SimpleNamespace(
        symbol=symbol,
        side=side,
        strike=strike,
        snap=SimpleNamespace(symbol=symbol, spot=spot, dataAvailable=True),
        mode="explosion",
        alert=alert,
    )


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_call_still_blocked_on_bearish_open_without_lift(mock_session):
    mock_session.return_value = {
        "open": 24538.2,
        "last": 24500.0,
        "hi": 24520.0,
        "lo": 24388.05,
    }
    s = Settings(open_caution_side_align_index_enabled=True)
    snap = SimpleNamespace(spot=24500.0)
    ok, reason, _ = open_caution_side_align_ok("NIFTY", "CALL", snap, settings=s, when=OPEN)
    assert not ok
    assert reason == "open_caution_call_on_bearish_open"


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_nov6_style_call_waives_bearish_open_with_v_rip(mock_session):
    """Cash below open but rally off session low — structural waiver passes."""
    mock_session.return_value = {
        "open": 24538.2,
        "last": 24500.0,
        "hi": 24520.0,
        "lo": 24388.05,
    }
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_side_align_index_enabled=True,
        open_caution_structural_side_align_waiver_enabled=True,
        open_caution_itm_band_enabled=False,
        open_caution_non_lane_index_blocked=False,
    )
    cand = _cand(
        "NIFTY",
        Side.CALL,
        24450.0,
        spot=24500.0,
        alert=_alert_call_v_rip(),
    )
    ok, reason, meta = validate_open_setup_entry(cand, settings=s, when=OPEN)
    assert ok, reason
    assert meta.get("openStructuralSideAlignWaiver") is True


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_call_waiver_rejected_without_v_rip_moment(mock_session):
    mock_session.return_value = {
        "open": 24538.2,
        "last": 24500.0,
        "hi": 24520.0,
        "lo": 24388.05,
    }
    s = Settings(open_caution_structural_side_align_waiver_enabled=True)
    cand = _cand(
        "NIFTY",
        Side.CALL,
        24450.0,
        spot=24500.0,
        alert={"tier": "ELITE", "momentType": "flat_then_vertical", "rankScore": 95.0},
    )
    waived, meta = open_caution_structural_side_align_waiver(
        cand,
        "open_caution_call_on_bearish_open",
        symbol="NIFTY",
        side="CALL",
        snap=cand.snap,
        settings=s,
        when=OPEN,
    )
    assert not waived
    assert meta.get("structuralWaiverReason") == "no_structural_lift_moment"


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_put_waives_bullish_open_with_v_rip_off_high(mock_session):
    mock_session.return_value = {
        "open": 22800.0,
        "last": 22875.0,
        "hi": 22900.0,
        "lo": 22600.0,
    }
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_side_align_index_enabled=True,
        open_caution_structural_side_align_waiver_enabled=True,
        open_caution_itm_band_enabled=False,
        open_caution_non_lane_index_blocked=False,
    )
    cand = _cand(
        "NIFTY",
        Side.PUT,
        22950.0,
        spot=22875.0,
        alert=_alert_put_v_rip(),
    )
    ok, reason, meta = validate_open_setup_entry(cand, settings=s, when=OPEN)
    assert ok, reason
    assert meta.get("openStructuralSideAlignWaiver") is True


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_structural_waiver_disabled_keeps_hard_block(mock_session):
    mock_session.return_value = {
        "open": 24538.2,
        "last": 24500.0,
        "hi": 24520.0,
        "lo": 24388.05,
    }
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_structural_side_align_waiver_enabled=False,
        open_caution_itm_band_enabled=False,
    )
    cand = _cand(
        "NIFTY",
        Side.CALL,
        24450.0,
        spot=24500.0,
        alert=_alert_call_v_rip(),
    )
    ok, reason, _ = validate_open_setup_entry(cand, settings=s, when=OPEN)
    assert not ok
    assert reason == "open_caution_call_on_bearish_open"
