"""Nearest expiry index priority — Tue NIFTY / Thu SENSEX, roles flip."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.bad_day_routing import (
    cross_index_rank_adjustment,
    expiry_proximity_ranks,
    is_same_week_next_index,
    pre_expiry_index_restricted,
)
from app.engines.premium_filter import premium_in_band
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)
from app.services.upstox import get_nearest_expiry

IST = ZoneInfo("Asia/Kolkata")


def _today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _next_week() -> str:
    return (datetime.now(IST) + timedelta(days=7)).strftime("%Y-%m-%d")


def _tomorrow() -> str:
    return (datetime.now(IST) + timedelta(days=1)).strftime("%Y-%m-%d")


def _in_days(n: int) -> str:
    return (datetime.now(IST) + timedelta(days=n)).strftime("%Y-%m-%d")


def _snap(symbol: str, expiry: str, tqs: float = 40.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=expiry,
        spot=24500.0 if symbol == "NIFTY" else 78700.0,
        atmStrike=24500.0 if symbol == "NIFTY" else 78700.0,
        regime=Regime.CHOP,
        tradeQualityScore=tqs,
        breadth=Breadth(bias="BEARISH", score=50, aligned=True),
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.2, trendStrength=40),
    )


class _Cand:
    def __init__(self, symbol, side, score, mode="explosion", tier="ELITE", snap=None):
        self.symbol = symbol
        self.side = side
        self.score = score
        self.mode = mode
        self.tier = tier
        self.snap = snap


def _settings(**overrides):
    s = MagicMock()
    s.bad_day_routing_enabled = True
    s.pre_expiry_cross_index_enabled = True
    s.pre_expiry_symbol_rank_penalty = 12.0
    s.bad_day_fading_symbol_penalty = 18.0
    s.bad_day_alternate_index_bonus = 14.0
    s.bad_day_alternate_aligned_bonus = 8.0
    s.expiry_day_prefer_same_day_enabled = True
    s.expiry_day_symbol_rank_bonus = 22.0
    s.expiry_day_same_week_next_rank_bonus = 12.0
    s.expiry_day_same_week_next_sort_bonus = 15.0
    s.expiry_day_same_week_next_max_days = 3
    s.expiry_day_min_option_premium_inr = 15.0
    s.expiry_fading_symbol_loss_inr = -1_000_000.0
    s.expiry_fading_max_symbol_tqs = 0.0
    s.expiry_fading_session_loss_inr = -1_000_000.0
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 300.0
    s.explosion_max_premium_inr = 400.0
    s.explosion_cheap_rip_min_premium_inr = 8.0
    s.explosion_cheap_rip_min_peak_pct = 25.0
    s.expiry_day_guards_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_nearest_expiry_weekdays_tue_nifty_thu_sensex():
    """Calendar helpers: NIFTY→Tuesday, SENSEX→Thursday."""
    monday = datetime(2026, 8, 3, 10, 0, tzinfo=IST)  # Mon

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return monday

    with patch("app.services.upstox.datetime", _FixedDateTime):
        with patch("app.services.upstox.timedelta", timedelta):
            assert get_nearest_expiry("NIFTY") == "2026-08-04"   # Tue
            assert get_nearest_expiry("SENSEX") == "2026-08-06"  # Thu


@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={})
@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_tue_nifty_today_first_sensex_thu_second(mock_exp, mock_bad, _fade):
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_bad.return_value = cfg
    snaps = {
        "NIFTY": _snap("NIFTY", _today()),
        "SENSEX": _snap("SENSEX", _in_days(2)),  # Thu if today Tue
    }
    nearest, nxt = expiry_proximity_ranks(snaps)
    assert nearest == ["NIFTY"]
    assert nxt == ["SENSEX"]
    assert is_same_week_next_index(snaps["SENSEX"], snaps) is True
    n = cross_index_rank_adjustment(
        _Cand("NIFTY", Side.PUT, 70.0, snap=snaps["NIFTY"]), AutoTraderState(), snaps,
    )
    s = cross_index_rank_adjustment(
        _Cand("SENSEX", Side.PUT, 70.0, snap=snaps["SENSEX"]), AutoTraderState(), snaps,
    )
    assert n >= 22.0
    assert s >= 12.0
    assert n > s


@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={})
@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_wed_sensex_near_is_priority_after_nifty_expired(mock_exp, mock_bad, _fade):
    """After Tue NIFTY expiry: Wed with SENSEX tomorrow → SENSEX #1."""
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_bad.return_value = cfg
    snaps = {
        "NIFTY": _snap("NIFTY", _next_week()),       # next Tue
        "SENSEX": _snap("SENSEX", _tomorrow()),      # Thu near
    }
    nearest, nxt = expiry_proximity_ranks(snaps)
    assert nearest == ["SENSEX"]
    s = cross_index_rank_adjustment(
        _Cand("SENSEX", Side.PUT, 70.0, snap=snaps["SENSEX"]), AutoTraderState(), snaps,
    )
    n = cross_index_rank_adjustment(
        _Cand("NIFTY", Side.PUT, 70.0, snap=snaps["NIFTY"]), AutoTraderState(), snaps,
    )
    assert s >= 22.0
    assert n >= 0.0
    assert s > n
    # Near SENSEX must NOT be soft-routed away
    restricted, _ = pre_expiry_index_restricted(snaps["SENSEX"], snaps)
    assert restricted is False


@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={})
@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_thu_sensex_today_first(mock_exp, mock_bad, _fade):
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_bad.return_value = cfg
    snaps = {
        "NIFTY": _snap("NIFTY", _in_days(5)),  # next week
        "SENSEX": _snap("SENSEX", _today()),
    }
    nearest, nxt = expiry_proximity_ranks(snaps)
    assert nearest == ["SENSEX"]
    s = cross_index_rank_adjustment(
        _Cand("SENSEX", Side.PUT, 70.0, snap=snaps["SENSEX"]), AutoTraderState(), snaps,
    )
    assert s >= 22.0


@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_same_day_expiry_not_restricted(mock_exp, mock_bad):
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_bad.return_value = cfg
    snaps = {
        "NIFTY": _snap("NIFTY", _today()),
        "SENSEX": _snap("SENSEX", _in_days(2)),
    }
    restricted, alt = pre_expiry_index_restricted(snaps["NIFTY"], snaps)
    assert restricted is False
    assert alt is None


@patch("app.engines.premium_filter.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_expiry_day_allows_20_ltp(mock_exp, mock_prem):
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_prem.return_value = cfg
    snap = _snap("NIFTY", _today())
    assert premium_in_band(20.0, mode="explosion", snap=snap) is True
    assert premium_in_band(15.0, mode="explosion", snap=snap) is True
