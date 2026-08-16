"""Historical time-to-flat-to-vertical probability regressions."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from app.engines.ftv_probability import (
    build_ftv_probability_dashboard,
    build_historical_profile,
    clear_ftv_probability_cache,
    estimate_live_probabilities,
    normalize_candles,
)
from app.models.schemas import Breadth, MarketPhase, SpotChart, SymbolSnapshot
from app.services.upstox import UpstoxClient

IST = ZoneInfo("Asia/Kolkata")


def _session(day: datetime, *, breakout_side: str = "CALL") -> list[list[object]]:
    rows: list[list[object]] = []
    price = 100.0
    for minute in range(76):
        ts = day.replace(hour=9, minute=15) + timedelta(minutes=minute)
        if minute == 45:
            price = 100.3 if breakout_side == "CALL" else 99.7
        elif minute == 46:
            price = 100.4 if breakout_side == "CALL" else 99.6
        open_px = rows[-1][4] if rows else 100.0
        high = max(float(open_px), price) + 0.01
        low = min(float(open_px), price) - 0.01
        rows.append([ts.isoformat(), open_px, high, low, price, 1_000 + minute, 0])
    return rows


def _snap(direction: str = "BULLISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 8, 12, 10, 0, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24_500,
        breadth=Breadth(
            bias=direction,
            score=65,
            aligned=True,
        ),
        spotChart=SpotChart(direction=direction),
        explosionAlerts=[{
            "side": "CALL" if direction == "BULLISH" else "PUT",
            "explosionScore": 70,
            "firstLift": True,
        }],
    )


def test_normalize_candles_sorts_and_deduplicates_upstox_rows():
    day = datetime(2026, 8, 10, tzinfo=IST)
    rows = _session(day)[:3]
    result = normalize_candles([rows[2], rows[0], rows[1], rows[1]])

    assert len(result) == 3
    assert [row["ts"] for row in result] == sorted(row["ts"] for row in result)


def test_historical_profile_learns_call_breakouts_after_flat_bases():
    rows: list[list[object]] = []
    for offset in range(8):
        rows.extend(_session(
            datetime(2026, 8, 3, tzinfo=IST) + timedelta(days=offset),
            breakout_side="CALL",
        ))
    profile = build_historical_profile(
        reversed(rows),
        flat_max_range_pct=0.08,
        vertical_move_pct=0.18,
    )

    assert profile["status"] == "READY"
    assert profile["sessionCount"] == 8
    assert profile["baseSamples"] > 100
    assert (
        profile["rates"]["CALL"]["5"]["probabilityPct"]
        > profile["rates"]["PUT"]["5"]["probabilityPct"]
    )
    assert profile["timeOfDayLeaders"]["CALL"]


def test_live_estimate_combines_flat_base_with_call_confirmation():
    history: list[list[object]] = []
    for offset in range(10):
        history.extend(_session(
            datetime(2026, 7, 20, tzinfo=IST) + timedelta(days=offset),
            breakout_side="CALL",
        ))
    profile = build_historical_profile(
        history,
        flat_max_range_pct=0.08,
        vertical_move_pct=0.18,
    )
    live = _session(datetime(2026, 8, 12, tzinfo=IST))[:25]
    estimate = estimate_live_probabilities(profile, live, _snap("BULLISH"))

    assert estimate["status"] == "READY"
    assert estimate["localBaseReady"] is True
    assert estimate["sides"]["CALL"]["probabilities"]["5"] > (
        estimate["sides"]["PUT"]["probabilities"]["5"]
    )
    assert estimate["dominantSide"] in {"CALL", "NEUTRAL"}


def test_upstox_v3_historical_method_builds_encoded_bounded_path(monkeypatch):
    client = UpstoxClient()
    get = AsyncMock(return_value={"candles": [["2026-08-12T09:15:00+05:30", 1, 2, 1, 2]]})
    monkeypatch.setattr(client, "_get_v3", get)

    result = asyncio.run(client.get_historical_candles_v3(
        "NSE_INDEX|Nifty 50",
        unit="minutes",
        interval=1,
        to_date="2026-08-12",
        from_date="2026-07-20",
        force_refresh=True,
    ))

    assert len(result) == 1
    get.assert_awaited_once_with(
        "/historical-candle/NSE_INDEX%7CNifty%2050/minutes/1/2026-08-12/2026-07-20"
    )


def test_dashboard_uses_upstox_history_and_reports_live_readiness():
    clear_ftv_probability_cache()
    historical: list[list[object]] = []
    for offset in range(10):
        historical.extend(_session(
            datetime(2026, 7, 20, tzinfo=IST) + timedelta(days=offset),
            breakout_side="CALL",
        ))
    client = AsyncMock(spec=UpstoxClient)
    client.get_historical_candles_v3.return_value = historical
    client.get_intraday_candles_v3.return_value = _session(
        datetime(2026, 8, 12, tzinfo=IST),
    )[:30]

    payload = asyncio.run(build_ftv_probability_dashboard(
        {"NIFTY": _snap("BULLISH")},
        client=client,
        force=True,
    ))

    assert payload["enabled"] is True
    assert payload["status"] == "LIVE"
    assert payload["symbols"]["NIFTY"]["source"] == "upstox_v3_index_1m"
    assert payload["symbols"]["NIFTY"]["live"]["liveReady"] is True
    assert "advisory only" in payload["guardrail"].lower()
