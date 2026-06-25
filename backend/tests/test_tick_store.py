"""Tests for tick store and Upstox WS protobuf decode."""

import pytest

from app.services.tick_store import (
    clear,
    collect_option_keys_from_chain,
    get_index_spot,
    get_ltp,
    overlay_chain_ltps,
    overlay_index_ltp,
    record_tick,
    status,
)
from app.services.upstox_ws import decode_feed_message
from app.proto import MarketDataFeed_pb2 as pb


@pytest.fixture(autouse=True)
def _reset_ticks():
    clear()
    yield
    clear()


def test_record_and_get_ltp():
    record_tick("NSE_INDEX|Nifty 50", 24500.5)
    assert get_ltp("NSE_INDEX|Nifty 50") == 24500.5
    assert get_index_spot("NIFTY") == 24500.5


def test_overlay_index_ltp_prefers_ws():
    record_tick("NSE_INDEX|Nifty 50", 24600.0)
    assert overlay_index_ltp("NIFTY", 24500.0) == 24600.0


def test_overlay_chain_ltps():
    chain = [
        {
            "strike_price": 24500,
            "call_options": {"instrument_key": "NSE_FO|CE1", "ltp": 50.0},
            "put_options": {"instrument_key": "NSE_FO|PE1", "ltp": 45.0},
        }
    ]
    record_tick("NSE_FO|CE1", 55.5)
    record_tick("NSE_FO|PE1", 40.0)
    updated = overlay_chain_ltps(chain)
    assert updated[0]["call_options"]["ltp"] == 55.5
    assert updated[0]["put_options"]["ltp"] == 40.0


def test_collect_option_keys_from_chain():
    chain = [
        {
            "strike_price": 24500,
            "call_options": {"instrument_key": "NSE_FO|CE1"},
            "put_options": {"instrument_key": "NSE_FO|PE1"},
        },
        {
            "strike_price": 25000,
            "call_options": {"instrument_key": "NSE_FO|CE2"},
            "put_options": {"instrument_key": "NSE_FO|PE2"},
        },
    ]
    keys = collect_option_keys_from_chain(chain, atm=24500, scan_range=100)
    assert "NSE_FO|CE1" in keys
    assert "NSE_FO|PE1" in keys
    assert "NSE_FO|CE2" not in keys


def test_decode_feed_message_ltpc():
    resp = pb.FeedResponse()
    feed = resp.feeds["NSE_INDEX|Nifty 50"]
    feed.ltpc.ltp = 24321.75
    feed.ltpc.ltt = 1234567890
    raw = resp.SerializeToString()
    ticks = decode_feed_message(raw)
    assert ticks["NSE_INDEX|Nifty 50"][0] == pytest.approx(24321.75)


def test_status_after_ticks():
    record_tick("NSE_INDEX|Nifty 50", 100.0)
    s = status()
    assert s["instrumentCount"] == 1
    assert s["tickCount"] == 1
    assert s["hasRecentTicks"] is True
