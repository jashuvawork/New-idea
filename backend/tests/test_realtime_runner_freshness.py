"""Explosive-runner snapshot velocity must not bridge stale feed gaps."""

from unittest.mock import patch

from app.config import Settings
from app.engines.realtime_engine import _scan_runners


def _chain(premium: float) -> list[dict]:
    return [{
        "strike_price": 24300.0,
        "call_options": {
            "ltp": premium,
            "oi": 100_000,
            "volume": 10_000,
            "bid": premium - 0.5,
            "ask": premium + 0.5,
        },
    }]


def _call_velocity(watchlist: list[dict]) -> float:
    return next(row["premiumVelocityPct"] for row in watchlist if row["side"] == "CALL")


def test_runner_velocity_uses_fresh_consecutive_snapshot():
    settings = Settings(runner_velocity_history_max_age_seconds=15.0)
    with (
        patch("app.engines.realtime_engine.get_settings", return_value=settings),
        patch("time.monotonic", side_effect=[100.0, 101.0]),
    ):
        _scan_runners(_chain(100.0), 24300.0, 24300.0, "NIFTY")
        _, watchlist = _scan_runners(_chain(103.0), 24300.0, 24300.0, "NIFTY")

    assert _call_velocity(watchlist) == 3.0


def test_runner_velocity_resets_after_stale_snapshot_gap():
    settings = Settings(runner_velocity_history_max_age_seconds=15.0)
    with (
        patch("app.engines.realtime_engine.get_settings", return_value=settings),
        patch("time.monotonic", side_effect=[100.0, 120.0]),
    ):
        _scan_runners(_chain(100.0), 24300.0, 24300.0, "NIFTY")
        _, watchlist = _scan_runners(_chain(120.0), 24300.0, 24300.0, "NIFTY")

    assert _call_velocity(watchlist) == 0.0
