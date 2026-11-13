"""ABC bundle: open CE off low, block blind open PE, afternoon slide lane."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.index_slide_capture_lane import (
    index_slide_capture_elite_floor,
    index_slide_capture_lane_status,
)
from app.engines.open_index_lane import in_open_side_align_window_at
from app.engines.open_setup_guards import (
    open_caution_index_leg_confirmed,
    open_caution_side_align_ok,
    validate_open_setup_entry,
)

IST = ZoneInfo("Asia/Kolkata")
OPEN_925 = datetime(2026, 11, 13, 9, 25, tzinfo=IST)
OPEN_932 = datetime(2026, 11, 13, 9, 32, tzinfo=IST)
AFTER_1045 = datetime(2026, 11, 13, 10, 50, tzinfo=IST)


def test_side_align_window_ends_0930():
    s = Settings()
    assert in_open_side_align_window_at(OPEN_925)
    assert not in_open_side_align_window_at(OPEN_932)


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_call_bearish_open_allowed_with_rally_off_low(mock_session):
    mock_session.return_value = {
        "open": 26000.0,
        "last": 25950.0,
        "hi": 26010.0,
        "lo": 25800.0,
    }
    s = Settings(open_caution_index_rally_side_align_waiver_enabled=True)
    snap = SimpleNamespace(spot=25950.0, symbol="NIFTY")
    with patch("app.engines.index_rally_side_flip.index_rally_metrics") as m:
        m.return_value = {
            "rallyPoints": 150.0,
            "slidePoints": 60.0,
            "momentum5Pct": 0.08,
        }
        ok, reason, meta = open_caution_side_align_ok(
            "NIFTY", "CALL", snap, settings=s, when=OPEN_925,
        )
    assert ok, reason
    assert meta.get("openIndexRallySideAlignWaiver") is True


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_put_bearish_open_blocked_without_slide(mock_session):
    mock_session.return_value = {
        "open": 83500.0,
        "last": 83400.0,
        "hi": 83520.0,
        "lo": 83300.0,
    }
    s = Settings(open_caution_open_put_requires_slide_off_high_enabled=True)
    snap = SimpleNamespace(spot=83400.0, symbol="SENSEX")
    with patch("app.engines.index_rally_side_flip.index_rally_metrics") as m:
        m.return_value = {
            "rallyPoints": 100.0,
            "slidePoints": 20.0,
            "momentum5Pct": -0.01,
        }
        ok, reason, _ = open_caution_side_align_ok(
            "SENSEX", "PUT", snap, settings=s, when=OPEN_925,
        )
    assert not ok
    assert reason == "open_caution_put_bearish_open_without_slide"


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_exploding_tier_structural_waiver_with_index_leg_only(mock_session):
    mock_session.return_value = {
        "open": 26000.0,
        "last": 25940.0,
        "hi": 26020.0,
        "lo": 25800.0,
    }
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_structural_side_align_waiver_enabled=True,
        open_caution_structural_waiver_allow_exploding_tier=True,
        open_caution_itm_band_enabled=False,
        open_caution_non_lane_index_blocked=False,
        open_caution_structural_waiver_exploding_rank_floor=70.0,
    )
    alert = {
        "tier": "EXPLODING",
        "momentType": "flat_then_vertical",
        "rankScore": 75.0,
        "localBaseMovePct": 30.0,
    }
    cand = SimpleNamespace(
        symbol="NIFTY",
        side="CALL",
        strike=25900.0,
        snap=SimpleNamespace(spot=25940.0),
        alert=alert,
        mode="explosion",
    )
    with patch("app.engines.index_rally_side_flip.index_rally_metrics") as m:
        m.return_value = {
            "rallyPoints": 140.0,
            "slidePoints": 80.0,
            "momentum5Pct": 0.05,
        }
        ok, reason, meta = validate_open_setup_entry(cand, settings=s, when=OPEN_925)
    assert ok, reason
    assert meta.get("openStructuralSideAlignWaiver") or meta.get("openIndexRallySideAlignWaiver")


def test_afternoon_slide_lane_puts_elite_floor():
    s = Settings(index_slide_capture_lane_enabled=True)
    snap = SimpleNamespace(symbol="SENSEX", spot=81800.0)
    with patch(
        "app.engines.index_session_dominant_trend.index_session_dominant_trend"
    ) as dom, patch(
        "app.engines.index_rally_side_flip.index_rally_metrics"
    ) as m:
        dom.return_value = ("SLIDE", {"dominantTrend": "SLIDE"})
        m.return_value = {
            "rallyPoints": 50.0,
            "slidePoints": 200.0,
            "momentum5Pct": -0.04,
        }
        armed, reason, _ = index_slide_capture_lane_status(
            "SENSEX", "PUT", snap, when=AFTER_1045, settings=s,
        )
        assert armed, reason
        floor = index_slide_capture_elite_floor(
            {"symbol": "SENSEX", "side": "PUT"},
            snap=snap,
            when=AFTER_1045,
            settings=s,
        )
        assert floor == 78.0


def test_open_index_leg_confirmed_ce_pe_symmetric():
    s = Settings()
    snap = SimpleNamespace(spot=100.0)
    with patch("app.engines.index_rally_side_flip.index_rally_metrics") as m:
        m.return_value = {"rallyPoints": 140.0, "slidePoints": 20.0, "momentum5Pct": 0.03}
        ok, meta = open_caution_index_leg_confirmed("NIFTY", "CALL", snap, settings=s)
        assert ok
        assert meta["indexLeg"] == "rally_off_low"
    with patch("app.engines.index_rally_side_flip.index_rally_metrics") as m:
        m.return_value = {"rallyPoints": 20.0, "slidePoints": 140.0, "momentum5Pct": -0.03}
        ok, meta = open_caution_index_leg_confirmed("SENSEX", "PUT", snap, settings=s)
        assert ok
        assert meta["indexLeg"] == "slide_off_high"
