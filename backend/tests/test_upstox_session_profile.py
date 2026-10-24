"""Cash-session measurements use today's Upstox bars, not the warmup window."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engines.chart_advanced_analysis import build_chart_analysis
from app.engines.realtime_engine import (
    _build_greeks,
    _build_orderflow,
    _build_profile,
    _detect_regime,
)
from app.engines.strategies.opening_drive import OpeningDriveScalp
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime

IST = ZoneInfo("Asia/Kolkata")


def _bar(ts: str, open_: float, high: float, low: float, close: float) -> list:
    return [ts, open_, high, low, close, 0]


def test_profile_opening_range_is_todays_first_cash_bars():
    today = datetime.now(IST).date()
    prior = today - timedelta(days=1)
    yesterday = [
        _bar(f"{prior.isoformat()}T14:{i:02d}:00+05:30", 100, 110, 90, 100)
        for i in range(20)
    ]
    today_bars = []
    for i in range(16):
        minute = 15 + i
        hour = 9 + minute // 60
        minute = minute % 60
        high = 206 if i == 0 else (220 if i == 15 else 205)
        low = 198 if i == 0 else 200
        today_bars.append(
            _bar(
                f"{today.isoformat()}T{hour:02d}:{minute:02d}:00+05:30",
                200,
                high,
                low,
                204,
            )
        )
    profile = _build_profile(yesterday + today_bars, 204)
    assert profile.openingRangeHigh == 206
    assert profile.openingRangeLow == 198
    assert profile.vah == 220
    assert profile.val == 198
    assert profile.poc == 204


def test_profile_keeps_untimestamped_replay_bars():
    candles = [[0, 100, 110, 90, 105, 0] for _ in range(20)]
    profile = _build_profile(candles, 105)
    assert profile.openingRangeHigh == 110
    assert profile.openingRangeLow == 90
    assert profile.vah == 110
    assert profile.val == 90


def test_profile_does_not_invent_a_value_area():
    empty = _build_profile([], 24000)
    assert empty.poc == 24000
    assert empty.vah == 0
    assert empty.val == 0
    assert empty.openingRangeHigh == 0
    assert empty.openingRangeLow == 0

    prior = datetime.now(IST).date() - timedelta(days=1)
    yesterday = [_bar(f"{prior.isoformat()}T15:20:00+05:30", 100, 110, 90, 100)]
    stale = _build_profile(yesterday, 24000)
    assert stale.vah == 0
    assert stale.openingRangeHigh == 0


def test_greeks_stay_unset_when_upstox_omits_them():
    chain = [{"strike_price": 24000, "call_options": {"ltp": 100}}]
    greeks = _build_greeks(chain, 24000, 24000, symbol="NIFTY")
    assert greeks.delta == 0
    assert greeks.gamma == 0
    assert greeks.theta == 0
    assert greeks.vega == 0
    assert greeks.ivExpansion == 1.0
    assert greeks.ivRank == 0


def test_greeks_keep_the_quoted_iv_and_delta():
    chain = [
        {
            "strike_price": 24000,
            "call_options": {
                "implied_volatility": 20,
                "greeks": {"delta": 0.62, "gamma": 0.01, "theta": -3, "vega": 8},
            },
        }
    ]
    greeks = _build_greeks(chain, 24000, 24000, symbol="NIFTY")
    assert greeks.delta == 0.62
    assert greeks.gamma == 0.01
    assert greeks.theta == -3
    assert greeks.vega == 8
    assert greeks.ivExpansion == 1.05
    assert greeks.ivRank == 60


def test_regime_does_not_treat_the_overnight_gap_as_a_trend():
    today = datetime.now(IST).date()
    prior = today - timedelta(days=1)
    rows = [
        _bar(f"{prior.isoformat()}T15:{i:02d}:00+05:30", 24000, 24010, 23990, 24000)
        for i in range(15)
    ]
    rows += [
        _bar(f"{today.isoformat()}T09:{15 + i:02d}:00+05:30", 24500, 24510, 24490, 24500)
        for i in range(5)
    ]
    assert _detect_regime(rows, 24500) == Regime.RANGE_BOUND


def test_orderflow_impulse_ignores_the_overnight_gap():
    today = datetime.now(IST).date()
    prior = today - timedelta(days=1)
    rows = [
        _bar(f"{prior.isoformat()}T15:{27 + i:02d}:00+05:30", 24000, 24010, 23990, 24000)
        for i in range(3)
    ]
    rows += [
        _bar(f"{today.isoformat()}T09:{15 + i:02d}:00+05:30", 24500, 24510, 24490, 24500)
        for i in range(2)
    ]
    flow = _build_orderflow(rows, [], spot=24500, atm=24500, symbol="NIFTY")
    assert flow.deltaVelocity == 0
    assert flow.breakoutVelocity == 0
    assert flow.tickMomentum == 0


def test_opening_drive_does_not_fire_on_a_missing_range():
    signal = OpeningDriveScalp().evaluate(
        "NIFTY",
        24000,
        24000,
        [{"strike_price": 24000, "call_options": {"ltp": 100}}],
        Orderflow(breakoutVelocity=80),
        Greeks(),
        Breadth(bias="BULLISH", score=80, aligned=True),
        MarketProfile(poc=24000),
        Regime.TREND_EXPANSION,
        "open_drive",
        [],
    )
    assert signal is None


def test_chart_vwap_uses_today_when_yesterday_is_in_the_window():
    today = datetime.now(IST).date()
    prior = today - timedelta(days=1)
    yesterday = _bar(f"{prior.isoformat()}T15:20:00+05:30", 100, 110, 90, 100)
    first = _bar(f"{today.isoformat()}T09:15:00+05:30", 200, 206, 198, 204)
    second = _bar(f"{today.isoformat()}T09:16:00+05:30", 204, 210, 202, 208)
    analysis = build_chart_analysis(
        [yesterday, first, second],
        [],
        208.0,
        MarketProfile(poc=208),
        symbol="NIFTY",
    )
    assert analysis.vwap["vwap"] > 190
    assert analysis.institutional["sessionLow"] == 198.0
