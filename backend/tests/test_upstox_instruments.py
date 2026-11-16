"""MCX commodity futures key resolution from Upstox instrument master."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.upstox_instruments import resolve_nearest_mcx_futures_key

IST = ZoneInfo("Asia/Kolkata")


def _fut_row(asset: str, key: str, y: int, m: int, d: int) -> dict:
    exp = datetime(y, m, d, 23, 30, tzinfo=IST)
    return {
        "segment": "MCX_FO",
        "instrument_type": "FUT",
        "asset_symbol": asset,
        "instrument_key": key,
        "expiry": int(exp.timestamp() * 1000),
    }


def test_resolve_nearest_mcx_futures_key_picks_earliest_live_contract():
    rows = [
        _fut_row("CRUDEOILM", "MCX_FO|old", 2026, 10, 1),
        _fut_row("CRUDEOILM", "MCX_FO|near", 2026, 11, 19),
        _fut_row("CRUDEOILM", "MCX_FO|far", 2026, 12, 18),
        _fut_row("NATGASMINI", "MCX_FO|gas", 2026, 11, 24),
    ]
    as_of = datetime(2026, 11, 16, 12, 0, tzinfo=IST)
    assert (
        resolve_nearest_mcx_futures_key(rows, "CRUDEOILM", as_of=as_of) == "MCX_FO|near"
    )
    assert resolve_nearest_mcx_futures_key(rows, "NATGASMINI", as_of=as_of) == "MCX_FO|gas"


def test_commodity_registry_uses_mcx_fo_not_futcom():
    from app.services.instrument_registry import get_spec

    crude = get_spec("CRUDEOIL")
    assert crude is not None
    assert crude.instrument_key.startswith("MCX_FO|")
    assert crude.futures_asset_symbol == "CRUDEOILM"
    assert crude.fallback_lot_size == 10