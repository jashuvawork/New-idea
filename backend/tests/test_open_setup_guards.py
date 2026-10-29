"""Open setup guards + daily selector prefilter (all sessions)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.open_setup_guards import (
    daily_entry_prefilter_reason,
    filter_daily_entry_candidates,
    open_caution_itm_depth_ok,
    open_caution_side_align_ok,
    validate_open_setup_entry,
)
from app.models.schemas import Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
OPEN = datetime(2026, 10, 29, 9, 35, tzinfo=IST)


def _cand(symbol: str, side: Side, strike: float, *, spot: float | None = None, alert: dict | None = None):
    spot_v = spot if spot is not None else (73500.0 if symbol == "SENSEX" else 22800.0)
    snap = SimpleNamespace(
        symbol=symbol,
        spot=spot_v,
        dataAvailable=True,
        timestamp=OPEN,
    )
    return SimpleNamespace(
        symbol=symbol,
        side=side,
        strike=strike,
        snap=snap,
        alert=alert or {"ictFirstLift": True, "tier": "ELITE"},
    )


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_put_blocked_on_bullish_open(mock_session):
    mock_session.return_value = {"open": 73000.0, "last": 73500.0, "hi": 73500.0, "lo": 73000.0}
    s = Settings(open_caution_side_align_index_enabled=True)
    snap = SimpleNamespace(spot=73500.0)
    ok, reason, _ = open_caution_side_align_ok("SENSEX", "PUT", snap, settings=s)
    assert not ok
    assert reason == "open_caution_put_on_bullish_open"


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_call_blocked_on_bearish_open(mock_session):
    mock_session.return_value = {"open": 73500.0, "last": 73000.0, "hi": 73500.0, "lo": 73000.0}
    s = Settings(open_caution_side_align_index_enabled=True)
    snap = SimpleNamespace(spot=73000.0)
    ok, reason, _ = open_caution_side_align_ok("SENSEX", "CALL", snap, settings=s)
    assert not ok
    assert reason == "open_caution_call_on_bearish_open"


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_sensex_put_allowed_on_bearish_open(mock_session):
    mock_session.return_value = {"open": 73500.0, "last": 73000.0, "hi": 73500.0, "lo": 73000.0}
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_side_align_index_enabled=True,
    )
    cand = _cand("SENSEX", Side.PUT, 73800.0, spot=73000.0)
    ok, reason, _ = validate_open_setup_entry(cand, settings=s, when=OPEN)
    assert ok, reason


def test_open_blocks_nifty_put_when_legacy_block_puts_on():
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=True,
        open_sensex_call_lane_enabled=True,
        open_nifty_put_lane_enabled=False,
        open_caution_block_puts_enabled=True,
        open_caution_side_align_index_enabled=False,
        open_caution_non_lane_index_blocked=True,
    )
    cand = _cand("NIFTY", Side.PUT, 22700.0)
    ok, reason, _ = validate_open_setup_entry(cand, settings=s, when=OPEN)
    assert not ok
    assert reason == "open_caution_puts_blocked"


def test_open_blocks_otm_sensex_call():
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_itm_band_enabled=True,
        open_caution_side_align_index_enabled=False,
    )
    cand_otm = _cand("SENSEX", Side.CALL, 73700.0)
    cand_otm.snap.spot = 73500.0
    ok2, reason2, _ = validate_open_setup_entry(cand_otm, settings=s, when=OPEN)
    assert not ok2
    assert reason2 == "call_not_itm"


def test_itm_depth_cap_sensex():
    s = Settings(open_caution_sensex_call_max_itm_points=800.0)
    ok2, depth, meta = open_caution_itm_depth_ok(
        "CALL", 72600.0, 73500.0, symbol="SENSEX", settings=s,
    )
    assert depth == 900.0
    assert not ok2
    assert meta.get("itmReason") == "open_caution_itm_too_deep"


def test_sensex_call_itm_passes_lane_side():
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_non_lane_index_blocked=True,
        open_sensex_call_lane_enabled=True,
        open_caution_itm_band_enabled=True,
        open_caution_side_align_index_enabled=False,
    )
    cand = _cand("SENSEX", Side.CALL, 73000.0)
    cand.snap.spot = 73500.0
    ok, reason, meta = validate_open_setup_entry(cand, settings=s, when=OPEN)
    assert ok, (reason, meta)


@patch("app.engines.expiry_day_guards._today_str", return_value="2026-09-17")
def test_daily_prefilter_drops_sensex_expiry_otm(_mock_today):
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_side_align_index_enabled=False,
        selector_expiry_otm_prefilter_enabled=True,
    )
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-09-17T11:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=74003.0,
        atmStrike=74000.0,
        dataAvailable=True,
        optionExpiry="2026-09-17",
    )
    otm = MagicMock(
        mode="explosion",
        symbol="SENSEX",
        side=Side.CALL,
        strike=74500.0,
        premium=192.0,
        snap=snap,
        alert={"premium": 192.0},
    )
    itm = MagicMock(
        mode="explosion",
        symbol="SENSEX",
        side=Side.CALL,
        strike=73500.0,
        premium=350.0,
        snap=snap,
        alert={"premium": 350.0},
    )
    snapshots = {"SENSEX": snap}
    assert daily_entry_prefilter_reason(otm, snapshots, settings=s) == (
        "best_trade_block_expiry_otm_itm_atm_only"
    )
    assert daily_entry_prefilter_reason(itm, snapshots, settings=s) == ""

    with patch(
        "app.engines.open_setup_guards._record_selector_prefilter_rejection",
    ) as mock_rec:
        kept = filter_daily_entry_candidates([otm, itm], snapshots, settings=s)
        assert kept == [itm]
        mock_rec.assert_called_once()
        assert mock_rec.call_args[0][1] == "best_trade_block_expiry_otm_itm_atm_only"
