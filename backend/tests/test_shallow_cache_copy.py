"""Shallow cache copies must not deep-clone ~130KB snapshot trees."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.models.schemas import AutoTraderState, MultiSnapshot
from app.routers import market

IST = ZoneInfo("Asia/Kolkata")


def test_shallow_cache_copy_shares_nested_snapshots():
    # Bypass nested SymbolSnapshot validation — we only care that the dict
    # reference is shared (deep=True would rebuild a new snapshots tree).
    inner = object()
    cache = MultiSnapshot.model_construct(
        timestamp=datetime.now(IST),
        dataReady=True,
        waitingReason=None,
        snapshots={"NIFTY": inner},
        autoTrader=AutoTraderState(),
        news=[],
    )
    market._cache = cache
    trader = AutoTraderState()
    with patch.object(market, "get_state", return_value=trader):
        copy = market._shallow_cache_copy(auto_trader=trader, waiting_reason=None)
    assert copy is not cache
    assert copy.snapshots is cache.snapshots
    assert copy.snapshots["NIFTY"] is inner
    assert copy.dataReady is True
    assert copy.waitingReason is None
    assert copy.autoTrader is trader
