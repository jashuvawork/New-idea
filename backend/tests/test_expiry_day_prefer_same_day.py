"""Expiry day: prioritize same-day expiry index first, then next."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.bad_day_routing import (
    cross_index_rank_adjustment,
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

IST = ZoneInfo("Asia/Kolkata")


def _today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _next_week() -> str:
    return (datetime.now(IST) + timedelta(days=7)).strftime("%Y-%m-%d")


def _tomorrow() -> str:
    return (datetime.now(IST) + timedelta(days=1)).strftime("%Y-%m-%d")


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
    s.expiry_day_min_option_premium_inr = 15.0
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 300.0
    s.explosion_max_premium_inr = 400.0
    s.explosion_cheap_rip_min_premium_inr = 8.0
    s.explosion_cheap_rip_min_peak_pct = 25.0
    s.expiry_day_guards_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_same_day_expiry_not_restricted(mock_exp, mock_bad):
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_bad.return_value = cfg
    snaps = {
        "NIFTY": _snap("NIFTY", _today()),
        "SENSEX": _snap("SENSEX", _next_week()),
    }
    restricted, alt = pre_expiry_index_restricted(snaps["NIFTY"], snaps)
    assert restricted is False
    assert alt is None


@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={})
def test_thu_nifty_first_fri_sensex_second(mock_fade, mock_exp, mock_bad):
    """Thu: NIFTY expires today (#1), SENSEX expires tomorrow same week (#2)."""
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_bad.return_value = cfg
    snaps = {
        "NIFTY": _snap("NIFTY", _today(), tqs=42.0),
        "SENSEX": _snap("SENSEX", _tomorrow(), tqs=48.0),
    }
    assert is_same_week_next_index(snaps["SENSEX"], snaps) is True
    assert is_same_week_next_index(snaps["NIFTY"], snaps) is False
    nifty = _Cand("NIFTY", Side.PUT, 70.0, snap=snaps["NIFTY"])
    sensex = _Cand("SENSEX", Side.PUT, 70.0, snap=snaps["SENSEX"])
    n_bonus = cross_index_rank_adjustment(nifty, AutoTraderState(), snaps)
    s_bonus = cross_index_rank_adjustment(sensex, AutoTraderState(), snaps)
    assert n_bonus >= 22.0
    assert s_bonus >= 12.0
    assert n_bonus > s_bonus


@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={})
def test_same_day_beats_far_next_week(mock_fade, mock_exp, mock_bad):
    """Same-day NIFTY outranks a far next-week SENSEX (not same-week #2)."""
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_bad.return_value = cfg
    snaps = {
        "NIFTY": _snap("NIFTY", _today(), tqs=42.0),
        "SENSEX": _snap("SENSEX", _next_week(), tqs=48.0),
    }
    assert is_same_week_next_index(snaps["SENSEX"], snaps) is False
    nifty = _Cand("NIFTY", Side.PUT, 70.0, snap=snaps["NIFTY"])
    sensex = _Cand("SENSEX", Side.PUT, 70.0, snap=snaps["SENSEX"])
    n_bonus = cross_index_rank_adjustment(nifty, AutoTraderState(), snaps)
    s_bonus = cross_index_rank_adjustment(sensex, AutoTraderState(), snaps)
    assert n_bonus >= 22.0
    assert s_bonus == 0.0


@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_same_week_next_not_restricted(mock_exp, mock_bad):
    """Thu NIFTY expiry: Fri SENSEX is #2 — still tradeable, not routed away."""
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_bad.return_value = cfg
    snaps = {
        "NIFTY": _snap("NIFTY", _today()),
        "SENSEX": _snap("SENSEX", _tomorrow()),
    }
    restricted, alt = pre_expiry_index_restricted(snaps["SENSEX"], snaps)
    assert restricted is False
    assert alt is None


@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_tomorrow_pre_expiry_still_routes(mock_exp, mock_bad):
    """Lone tomorrow pre-expiry (no same-day peer) still routes to alternate."""
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_bad.return_value = cfg
    snaps = {
        "NIFTY": _snap("NIFTY", _next_week()),
        "SENSEX": _snap("SENSEX", _tomorrow()),
    }
    restricted, alt = pre_expiry_index_restricted(snaps["SENSEX"], snaps)
    assert restricted is True
    assert alt == "NIFTY"


@patch("app.engines.premium_filter.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_expiry_day_allows_20_ltp(mock_exp, mock_prem):
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_prem.return_value = cfg
    snap = _snap("NIFTY", _today())
    assert premium_in_band(20.0, mode="explosion", snap=snap) is True
    assert premium_in_band(15.0, mode="explosion", snap=snap) is True
    assert premium_in_band(14.0, mode="explosion", snap=snap) is False


@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_tomorrow_still_gets_rank_penalty(mock_exp, mock_bad):
    cfg = _settings()
    mock_exp.return_value = cfg
    mock_bad.return_value = cfg
    snaps = {
        "NIFTY": _snap("NIFTY", _next_week(), tqs=40.0),
        "SENSEX": _snap("SENSEX", _tomorrow(), tqs=34.0),
    }
    with patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={}):
        nifty = _Cand("NIFTY", Side.PUT, 70.0, snap=snaps["NIFTY"])
        sensex = _Cand("SENSEX", Side.PUT, 70.0, snap=snaps["SENSEX"])
        assert cross_index_rank_adjustment(nifty, AutoTraderState(), snaps) > 0
        assert cross_index_rank_adjustment(sensex, AutoTraderState(), snaps) < 0
