"""Constituent quote resolution — Upstox returns NSE_EQ:SYMBOL keys, not ISIN keys."""

from app.engines.constituent_engine import _parse_quote
from app.services.upstox import normalize_quotes_map, resolve_quote_payload


def test_resolve_quote_by_instrument_token_when_key_is_symbol():
    raw = {
        "NSE_EQ:HDFCBANK": {
            "symbol": "HDFCBANK",
            "instrument_token": "NSE_EQ|INE040A01034",
            "last_price": 1950.5,
            "ohlc": {"open": 1940, "high": 1960, "low": 1935, "close": 1945},
            "average_price": 1948.2,
            "volume": 1_200_000,
        }
    }
    data = normalize_quotes_map(raw)
    quote = resolve_quote_payload(data, "NSE_EQ|INE040A01034")
    assert quote["last_price"] == 1950.5
    assert quote["symbol"] == "HDFCBANK"


def test_normalize_quotes_map_aliases_instrument_token():
    raw = {
        "BSE_EQ:RELIANCE": {
            "symbol": "RELIANCE",
            "instrument_token": "BSE_EQ|INE002A01018",
            "last_price": 1420.0,
            "ohlc": {"close": 1410.0},
        }
    }
    data = normalize_quotes_map(raw)
    assert "BSE_EQ|INE002A01018" in data
    assert data["BSE_EQ|INE002A01018"]["last_price"] == 1420.0


def test_parse_quote_uses_cp_when_no_ohlc():
    parsed = _parse_quote({"last_price": 101.0, "cp": 100.0, "volume": 5000}, 0)
    assert parsed["changePct"] == 1.0
    assert parsed["ltp"] == 101.0
