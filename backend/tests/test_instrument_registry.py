"""MCX commodity option underlyings + symbol merge."""

from __future__ import annotations

import re

from app.config import Settings
from app.engines.chop_live_guards import _OPTION_SYMBOL_RE, parse_broker_option_symbol
from app.models.schemas import Side
from app.engines.moneyness import strike_step
from app.services.instrument_registry import (
    COMMODITY_SYMBOLS,
    get_spec,
    index_keys_map,
    is_commodity,
)
from app.services.upstox import get_nearest_expiry


def test_commodity_specs_registered():
    assert "CRUDEOIL" in index_keys_map()
    assert index_keys_map()["CRUDEOIL"].startswith("MCX_FO|")
    assert get_spec("NATURALGAS") is not None
    assert is_commodity("CRUDEOIL")
    assert not is_commodity("NIFTY")
    assert "CRUDEOIL" in COMMODITY_SYMBOLS


def test_settings_merge_commodity_symbols():
    s = Settings(
        _env_file=None,
        symbols_csv="NIFTY,SENSEX",
        commodity_symbols_csv="CRUDEOIL,NATURALGAS",
    )
    assert s.symbols == ["NIFTY", "SENSEX", "CRUDEOIL", "NATURALGAS"]


def test_strike_step_commodity():
    assert strike_step("CRUDEOIL") == 50.0
    assert strike_step("NATURALGAS") == 5.0


def test_parse_broker_crudeoil_option():
    assert parse_broker_option_symbol("CRUDEOIL 8350 CE") == ("CRUDEOIL", 8350.0, Side.CALL)
    assert _OPTION_SYMBOL_RE.match("NATURALGAS 280 PE") is not None


def test_parse_broker_gold_silver_aliases():
    assert parse_broker_option_symbol("GOLDM 129000 CE") == ("GOLD", 129000.0, Side.CALL)
    assert parse_broker_option_symbol("SILVERM 243000 PE") == ("SILVER", 243000.0, Side.PUT)
    assert "GOLD" in COMMODITY_SYMBOLS
    assert "SILVER" in COMMODITY_SYMBOLS


def test_monthly_expiry_candidate():
    exp = get_nearest_expiry("CRUDEOIL")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", exp)


def test_weekly_expiry_unchanged_for_nifty():
    exp = get_nearest_expiry("NIFTY")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", exp)