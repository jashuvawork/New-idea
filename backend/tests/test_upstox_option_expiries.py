"""MCX option expiry parsing and chain-resolution candidate order."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.services.upstox import (
    UpstoxClient,
    get_nearest_expiry,
    parse_contract_expiry_date,
)
from app.services.upstox_instruments import list_option_expiries_from_master

IST = ZoneInfo("Asia/Kolkata")


def test_parse_contract_expiry_date_formats():
    assert parse_contract_expiry_date("2026-11-17") == "2026-11-17"
    assert parse_contract_expiry_date(1794940199000) == "2026-11-17"
    assert parse_contract_expiry_date("1794940199000") == "2026-11-17"


def test_commodity_guess_expiry_not_mcx_listed_date():
    """Monthly 19th guess is not the MCX crude listing (17 Nov)."""
    as_of = datetime(2026, 11, 16, 12, 0, tzinfo=IST)
    with patch("app.services.upstox.datetime") as mock_dt:
        mock_dt.now.return_value = as_of
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        guess = get_nearest_expiry("CRUDEOIL")
    assert guess == "2026-11-19"
    assert list_option_expiries_from_master(
        [
            {
                "segment": "MCX_FO",
                "instrument_type": "CE",
                "asset_symbol": "CRUDEOILM",
                "expiry": 1794940199000,
            }
        ],
        "CRUDEOILM",
        as_of=as_of,
    ) == ["2026-11-17"]


def test_chain_resolved_probes_api_expiry_before_giving_up():
    import asyncio

    client = UpstoxClient()

    async def fake_expiries(sym: str) -> list[str]:
        return ["2026-11-17", "2026-12-16"]

    async def fake_chain(sym: str, expiry: str) -> list:
        if expiry == "2026-11-19":
            return []
        if expiry == "2026-11-17":
            return [{"strike_price": 6800, "call_options": {}, "put_options": {}}]
        return []

    async def run():
        with patch.object(client, "get_option_expiries", side_effect=fake_expiries), patch.object(
            client, "get_option_chain", side_effect=fake_chain
        ), patch(
            "app.services.upstox._cache_get",
            return_value=None,
        ), patch("app.services.upstox._cache_set"), patch(
            "app.services.upstox._resolved_expiry",
            {},
        ):
            return await client.get_option_chain_resolved("CRUDEOIL")

    chain, expiry = asyncio.run(run())
    assert expiry == "2026-11-17"
    assert len(chain) == 1