"""Upstox candles are newest-first and V2 history excludes today — charts need oldest-first + today."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.engines.spot_direction import analyze_premium_chart, premium_blocks_entry
from app.models.schemas import Side
from app.services.upstox import UpstoxClient, chronological_candles

IST = ZoneInfo("Asia/Kolkata")


def _bar(ts: datetime, close: float) -> list:
    return [ts.isoformat(), close, close + 0.5, close - 0.5, close, 1000, 0]


def _session(day: datetime, start_close: float, step: float, bars: int) -> list:
    """Oldest-first 1m bars from 09:15 on ``day``."""
    t0 = day.replace(hour=9, minute=15, second=0, microsecond=0)
    return [_bar(t0 + timedelta(minutes=i), start_close + step * i) for i in range(bars)]


def test_chronological_candles_sorts_newest_first_and_dedupes():
    day = datetime(2026, 10, 14, tzinfo=IST)
    asc = _session(day, 100.0, 1.0, 5)
    newest_first = list(reversed(asc))
    restated = [_bar(day.replace(hour=9, minute=19), 999.0)]

    merged = chronological_candles(newest_first, restated)

    assert [row[0] for row in merged] == [row[0] for row in asc]
    assert merged[-1][4] == 999.0


def test_chronological_candles_keeps_order_without_timestamps():
    rows = [{"close": 3.0}, {"close": 1.0}, {"close": 2.0}]
    assert chronological_candles(rows) == rows


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_historical_candles_end_at_today_live_bar_ce_pe(side):
    """Oct 14: premium lifting today was read as 'fading' vs a days-old decayed price."""
    now = datetime.now(IST)
    prior = now - timedelta(days=1)
    older = now - timedelta(days=2)
    # Prior sessions: contract was pricier (more time value) — newest-first like Upstox V2.
    history = list(reversed(_session(older, 180.0, -0.05, 375) + _session(prior, 170.0, -0.05, 375)))
    # Today: base then a clean lift into the live bar — newest-first like Upstox V3 intraday.
    today = list(reversed(_session(now, 100.0, 0.5, 40)))

    client = UpstoxClient()
    client._get = AsyncMock(return_value={"candles": history})
    client._get_v3 = AsyncMock(return_value={"candles": today})

    candles = asyncio.run(
        client.get_historical_candles("NSE_FO|TEST", count=60, force_refresh=True)
    )

    assert len(candles) == 60
    stamps = [row[0] for row in candles]
    assert stamps == sorted(stamps)
    assert candles[-1][0] == today[0][0]

    live_ltp = today[0][4] + 0.5
    chart = analyze_premium_chart(candles, live_ltp)
    assert chart.momentum3Pct > 0
    assert chart.momentum5Pct > 0
    blocked, reason = premium_blocks_entry(side, chart, trade_score=95.0)
    assert blocked is False, reason


def test_historical_candles_survive_intraday_failure():
    now = datetime.now(IST)
    history = list(reversed(_session(now - timedelta(days=1), 50.0, 0.1, 30)))

    client = UpstoxClient()
    client._get = AsyncMock(return_value={"candles": history})
    client._get_v3 = AsyncMock(side_effect=RuntimeError("intraday down"))

    candles = asyncio.run(
        client.get_historical_candles("NSE_FO|TEST", count=10, force_refresh=True)
    )

    stamps = [row[0] for row in candles]
    assert stamps == sorted(stamps)
    assert candles[-1][0] == history[0][0]


def test_monday_indicator_window_keeps_friday_and_todays_open():
    """26 Oct 09:40 IST. Two calendar days is Sat–Mon, so Friday never arrives."""
    from app.engines.index_candle_rollover import (
        cash_session_candles,
        prior_close_before_cash_session,
    )
    from app.engines.spot_direction import build_spot_chart
    from app.models.schemas import MarketProfile

    monday = datetime(2026, 10, 26, 9, 40, tzinfo=IST)
    friday = datetime(2026, 10, 23, tzinfo=IST)
    friday_bars = _session(friday, 22600.0, -0.5, 375)
    monday_bars = _session(monday, 22524.4, -0.2, 25)
    history = list(reversed(friday_bars))
    today = list(reversed(monday_bars))

    client = UpstoxClient()
    client._get = AsyncMock(return_value={"candles": history})
    client._get_v3 = AsyncMock(return_value={"candles": today})

    asyncio.run(
        client.get_historical_candles(
            "NSE_INDEX|Nifty 50", count=400, force_refresh=True, as_of=monday,
        )
    )
    assert client._get.call_args[0][0].endswith("/2026-10-26/2026-10-24")

    seeded = asyncio.run(
        client.get_historical_candles(
            "NSE_INDEX|Nifty 50",
            count=400,
            lookback_days=7,
            force_refresh=True,
            as_of=monday,
        )
    )
    assert client._get.call_args[0][0].endswith("/2026-10-26/2026-10-19")
    assert len(seeded) == 400
    assert seeded[0][0] == friday_bars[0][0]
    assert seeded[-1][0] == monday_bars[-1][0]

    session = cash_session_candles(seeded, now=monday)
    assert session[0][1] == monday_bars[0][1]
    assert prior_close_before_cash_session(seeded, now=monday) == friday_bars[-1][4]

    chart = build_spot_chart(
        monday_bars[:5],
        float(monday_bars[-1][4]),
        MarketProfile(),
        indicator_candles_1m=seeded,
    )
    assert chart.barCount == 5
    assert chart.macdReady is True
    assert chart.indicatorBarCount >= 35
    assert chart.macd != 0.0


def test_index_fetches_pass_the_seed_lookback():
    from app.engines.index_chart_candles import fetch_index_chart_candles
    from app.engines.mtf_chart_analysis import fetch_mtf_charts

    monday = datetime(2026, 10, 26, 9, 40, tzinfo=IST)
    seen: dict[str, int | None] = {}

    async def fake_hist(*_args, **kwargs):
        seen["lookback"] = kwargs.get("lookback_days")
        seen["count"] = kwargs.get("count")
        return _session(monday, 22524.4, -0.2, 40)

    client = UpstoxClient()
    client.get_historical_candles = fake_hist  # type: ignore[method-assign]
    client.get_intraday_candles_v3 = AsyncMock(return_value=[])

    asyncio.run(fetch_index_chart_candles(client, "NIFTY", force_refresh=True))
    assert seen["lookback"] >= 7
    assert seen["count"] >= 400

    asyncio.run(
        fetch_mtf_charts(
            client,
            "NSE_INDEX|Nifty 50",
            22520.0,
            force_refresh=True,
            lookback_days=7,
        )
    )
    assert seen["lookback"] == 7

    asyncio.run(
        fetch_mtf_charts(
            client, "NSE_FO|OPT", 80.0, force_refresh=True,
        )
    )
    assert seen["lookback"] is None


def test_intraday_v3_returns_oldest_first():
    now = datetime.now(IST)
    asc = _session(now, 200.0, 1.0, 6)

    client = UpstoxClient()
    client._get_v3 = AsyncMock(return_value={"candles": list(reversed(asc))})

    candles = asyncio.run(
        client.get_intraday_candles_v3("NSE_INDEX|Nifty 50", force_refresh=True)
    )

    assert [row[0] for row in candles] == [row[0] for row in asc]
