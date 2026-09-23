"""Expiry-cycle local base — post-expiry slow vs near-expiry fast near-base policy."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.expiry_cycle_local_base import (
    days_until_chain_expiry,
    expiry_cycle_regime,
    refresh_symbol_chain_expiry,
    regime_local_base_window_seconds,
    resolve_local_base_window_seconds,
)
from app.engines.explosion_detector import (
    _local_base_hist,
    local_base_premium,
    reset_local_base_state_for_symbol,
)
from app.models.schemas import Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap(expiry: str) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST).isoformat(),
        marketPhase="LIVE_MARKET",
        spot=74800.0,
        atmStrike=74800.0,
        dataAvailable=True,
        optionExpiry=expiry,
    )


def test_regime_near_expiry_vs_post_expiry_week():
    today = datetime.now(IST).date()
    near = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    far = (today + timedelta(days=6)).strftime("%Y-%m-%d")
    s = Settings()
    assert expiry_cycle_regime(_snap(near), settings=s) == "NEAR_EXPIRY_FAST"
    assert expiry_cycle_regime(_snap(far), settings=s) == "POST_EXPIRY_SLOW"


def test_post_expiry_uses_shorter_local_base_window():
    s = Settings()
    assert regime_local_base_window_seconds("POST_EXPIRY_SLOW", s) == 900
    assert regime_local_base_window_seconds("NEAR_EXPIRY_FAST", s) == 1200
    assert regime_local_base_window_seconds("MID_CYCLE", s) == 1800


def test_chain_roll_clears_symbol_local_base_history():
    from app.engines import expiry_cycle_local_base as mod

    mod._symbol_chain_expiry.clear()
    _local_base_hist.clear()
    key = "SENSEX:74800:CE"
    _local_base_hist[key] = __import__("collections").deque(maxlen=10)
    refresh_symbol_chain_expiry("SENSEX", "2026-09-25")
    assert refresh_symbol_chain_expiry("SENSEX", "2026-10-02") is True
    assert key not in _local_base_hist
    mod._symbol_chain_expiry.clear()
    _local_base_hist.clear()


def test_days_until_chain_expiry():
    today = datetime.now(IST).date()
    d = days_until_chain_expiry(_snap((today + timedelta(days=3)).strftime("%Y-%m-%d")))
    assert d == 3


def test_resolve_window_from_cached_symbol_expiry():
    from app.engines import expiry_cycle_local_base as mod

    mod._symbol_chain_expiry.clear()
    today = datetime.now(IST).date()
    far = (today + timedelta(days=6)).strftime("%Y-%m-%d")
    refresh_symbol_chain_expiry("NIFTY", far)
    assert resolve_local_base_window_seconds(symbol="NIFTY") == 900
    mod._symbol_chain_expiry.clear()
