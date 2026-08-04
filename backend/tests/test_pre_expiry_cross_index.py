"""Pre-expiry cross-index routing — trade NIFTY when SENSEX expires tomorrow, and vice versa."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.bad_day_routing import (
    alternate_index_for,
    check_bad_day_candidate,
    cross_index_rank_adjustment,
    pm_itm_alternate_symbols,
    pre_expiry_index_restricted,
)
from app.engines.expiry_day_guards import is_pre_expiry_day, near_expiry_symbols
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


def _tomorrow() -> str:
    return (datetime.now(IST) + timedelta(days=1)).strftime("%Y-%m-%d")


def _next_week() -> str:
    return (datetime.now(IST) + timedelta(days=7)).strftime("%Y-%m-%d")


def _snap(symbol: str, expiry: str, tqs: float = 40.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=expiry,
        spot=24200.0 if symbol == "NIFTY" else 77600.0,
        atmStrike=24200.0 if symbol == "NIFTY" else 77600.0,
        regime=Regime.CHOP,
        tradeQualityScore=tqs,
        breadth=Breadth(bias="BEARISH", score=50, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.01, trendStrength=20),
    )


class _Cand:
    def __init__(self, symbol, side, score, mode="explosion", tier="EXPLODING", snap=None):
        self.symbol = symbol
        self.side = side
        self.score = score
        self.mode = mode
        self.tier = tier
        self.snap = snap


def test_sensex_near_expiry_is_not_routed_away():
    """Near-expiry SENSEX (tomorrow) is priority — not demoted to NIFTY."""
    tomorrow = _tomorrow()
    snaps = {
        "NIFTY": _snap("NIFTY", _next_week(), tqs=38.0),
        "SENSEX": _snap("SENSEX", tomorrow, tqs=34.0),
    }
    assert near_expiry_symbols(snaps) == ["SENSEX"]
    assert is_pre_expiry_day(snaps["SENSEX"]) is True
    assert alternate_index_for("SENSEX", snaps) == "NIFTY"

    restricted, alt = pre_expiry_index_restricted(snaps["SENSEX"], snaps)
    assert restricted is False
    assert alt is None


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
@patch("app.engines.bad_day_routing.expiry_index_fading", return_value=(False, []))
def test_near_expiry_sensex_stays_eligible_on_bad_day(mock_fade, mock_bad):
    """Near-expiry index is not soft-routed away on a bad-day session."""
    tomorrow = _tomorrow()
    snaps = {
        "NIFTY": _snap("NIFTY", _next_week(), tqs=38.0),
        "SENSEX": _snap("SENSEX", tomorrow, tqs=45.0),
    }
    snaps["SENSEX"].breadth = Breadth(bias="BEARISH", score=80, aligned=True)
    cand = _Cand("SENSEX", Side.PUT, 74.0, mode="explosion", tier="ELITE", snap=snaps["SENSEX"])
    ok, reason, meta = check_bad_day_candidate(cand, AutoTraderState(), snaps)
    assert ok, reason
    assert not meta.get("preExpiryRestricted")


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
@patch("app.engines.bad_day_routing.expiry_index_fading", return_value=(False, []))
def test_allows_aligned_sensex_elite_on_pre_expiry(mock_fade, mock_bad):
    """Jul29: breadth-aligned ELITE/EXPLODING on near-expiry SENSEX must not be deferred."""
    tomorrow = _tomorrow()
    snaps = {
        "NIFTY": _snap("NIFTY", _next_week(), tqs=38.0),
        "SENSEX": _snap("SENSEX", tomorrow, tqs=45.0),
    }
    snaps["SENSEX"].breadth = Breadth(bias="BULLISH", score=80, aligned=True)
    from app.engines.explosion_detector import ExplosionEvent

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77500.0,
        premium=270.0,
        velocity_3s=4.0,
        velocity_9s=6.0,
        velocity_15s=8.0,
        volume_surge=2.5,
        explosion_score=80.0,
        tier="ELITE",
        reason="open-gap",
        daily_move_pct=192.0,
        peak_move_pct=192.0,
    )
    cand = _Cand("SENSEX", Side.CALL, 80.0, mode="explosion", tier="ELITE", snap=snaps["SENSEX"])
    cand.explosion_event = event
    ok, reason, meta = check_bad_day_candidate(cand, AutoTraderState(), snaps)
    assert ok, reason
    # Extreme session-move bypass and/or explicit near-expiry allow both count.
    assert (
        meta.get("openGapNearExpiryAllow")
        or meta.get("nearExpirySymbolExplosionAllow")
        or reason == "ok"
    )


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
@patch("app.engines.bad_day_routing.expiry_index_fading", return_value=(False, []))
def test_allows_nifty_explosion_when_sensex_pre_expiry(mock_fade, mock_bad):
    tomorrow = _tomorrow()
    snaps = {
        "NIFTY": _snap("NIFTY", _next_week(), tqs=38.0),
        "SENSEX": _snap("SENSEX", tomorrow, tqs=34.0),
    }
    cand = _Cand("NIFTY", Side.PUT, 74.0, snap=snaps["NIFTY"])
    snaps["NIFTY"].tradeQualityScore = 45.0
    ok, reason, _ = check_bad_day_candidate(cand, AutoTraderState(), snaps)
    assert ok, reason


def test_cross_index_bonus_sensex_when_near_expiry():
    """SENSEX nearer expiry beats next-week NIFTY (vice versa of old demote)."""
    tomorrow = _tomorrow()
    snaps = {
        "NIFTY": _snap("NIFTY", _next_week(), tqs=38.0),
        "SENSEX": _snap("SENSEX", tomorrow, tqs=34.0),
    }
    nifty_cand = _Cand("NIFTY", Side.PUT, 70.0, snap=snaps["NIFTY"])
    sensex_cand = _Cand("SENSEX", Side.PUT, 70.0, snap=snaps["SENSEX"])
    nifty_bonus = cross_index_rank_adjustment(nifty_cand, AutoTraderState(), snaps)
    sensex_bonus = cross_index_rank_adjustment(sensex_cand, AutoTraderState(), snaps)
    assert sensex_bonus > nifty_bonus
    assert sensex_bonus > 0


@patch("app.engines.expiry_day_guards.in_expiry_pm_itm_window", return_value=True)
def test_pm_itm_alternate_nifty_when_sensex_pre_expiry(mock_pm):
    tomorrow = _tomorrow()
    snaps = {
        "NIFTY": _snap("NIFTY", _next_week(), tqs=38.0),
        "SENSEX": _snap("SENSEX", tomorrow, tqs=34.0),
    }
    alts = pm_itm_alternate_symbols(AutoTraderState(), snaps)
    assert "NIFTY" in alts
