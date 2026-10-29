"""Combined open setup guards (Oct29 playbook)."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.open_setup_guards import (
    open_caution_itm_depth_ok,
    validate_open_setup_entry,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
OPEN = datetime(2026, 10, 29, 9, 35, tzinfo=IST)


def _cand(symbol: str, side: Side, strike: float, *, alert: dict | None = None):
    snap = SimpleNamespace(
        symbol=symbol,
        spot=73500.0 if symbol == "SENSEX" else 22800.0,
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


def test_open_blocks_nifty_put_when_only_sensex_lane():
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=True,
        open_sensex_call_lane_enabled=True,
        open_nifty_put_lane_enabled=False,
        open_caution_block_puts_enabled=True,
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
    )
    cand = _cand("SENSEX", Side.CALL, 73000.0)
    cand.snap.spot = 73500.0
    ok, reason, meta = validate_open_setup_entry(cand, settings=s, when=OPEN)
    assert ok, (reason, meta)
