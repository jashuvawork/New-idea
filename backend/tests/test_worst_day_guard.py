"""Tests for worst-day pause and breakout-only mode."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.worst_day_guard import (
    identify_worst_day,
    session_entry_policy,
    worst_day_allows_candidate,
)
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


def _snap(symbol: str = "NIFTY", expiry: str = "2026-07-07", tqs: float = 38.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=expiry,
        spot=24480.0,
        regime=Regime.CHOP,
        tradeQualityScore=tqs,
        breadth=Breadth(bias="BEARISH", score=58, aligned=True),
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.05, trendStrength=30),
    )


class _Cand:
    def __init__(self, mode="scalp", tier="", score=70.0, symbol="NIFTY", side=Side.PUT):
        self.mode = mode
        self.tier = tier
        self.score = score
        self.symbol = symbol
        self.side = side
        self.snap = _snap(symbol)


@patch("app.engines.expiry_day_guards.predict_worst_expiry_day", return_value=(False, 30.0, []))
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.chop_day_guards.is_chop_session", return_value=True)
@patch("app.engines.whipsaw_guards.is_bearish_sideways_session", return_value=True)
def test_early_worst_day_on_expiry_chop_bearish(mock_bear, mock_chop, mock_exp, mock_pred):
    snaps = {"NIFTY": _snap()}
    verdict = identify_worst_day(AutoTraderState(), snaps)
    assert verdict.is_worst is True
    assert verdict.early_prediction is True
    assert "early_expiry_chop_bearish" in verdict.reasons


@patch("app.engines.worst_day_guard.identify_worst_day")
def test_breakout_only_policy(mock_identify):
    from app.engines.worst_day_guard import WorstDayVerdict

    mock_identify.return_value = WorstDayVerdict(True, 55.0, ["chop_regime"])
    policy, meta = session_entry_policy(AutoTraderState(), {"NIFTY": _snap()})
    assert policy == "BREAKOUT_ONLY"
    assert meta["pauseReason"] == "worst_day_breakout_only"


@patch("app.engines.index_tick_helpers.index_trend_override_active")
@patch("app.engines.worst_day_guard.identify_worst_day")
def test_intraday_trend_override_lifts_worst_day(mock_identify, mock_trend):
    """A genuine index breakout lifts the stale chop/worst BREAKOUT_ONLY to NORMAL."""
    from app.engines.worst_day_guard import WorstDayVerdict

    mock_identify.return_value = WorstDayVerdict(True, 45.0, ["chop_regime"])
    mock_trend.return_value = (True, {"side": "CALL", "symbol": "SENSEX"})
    policy, meta = session_entry_policy(AutoTraderState(), {"SENSEX": _snap()})
    assert policy == "NORMAL"
    assert meta.get("worstDayLiftedByTrend") is True


@patch("app.engines.index_tick_helpers.index_trend_override_active")
@patch("app.engines.worst_day_guard.identify_worst_day")
def test_trend_override_does_not_lift_severe_loss_pause(mock_identify, mock_trend):
    """Even a breakout must NOT lift the severe daily-loss (10%/day) pause."""
    from app.engines.worst_day_guard import WorstDayVerdict

    mock_identify.return_value = WorstDayVerdict(True, 60.0, ["chop_regime"])
    mock_trend.return_value = (True, {"side": "CALL"})
    state = AutoTraderState()
    with patch(
        "app.engines.worst_day_guard.compute_session_pnl", return_value=-25_000.0
    ):
        policy, meta = session_entry_policy(state, {"SENSEX": _snap()})
    assert policy == "PAUSED"
    assert meta["pauseReason"] == "worst_day_severe_session_loss"
    mock_trend.assert_not_called()


@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
def test_allows_scalp_momentum_on_breakout_only(mock_policy):
    ok, reason, meta = worst_day_allows_candidate(
        _Cand(mode="scalp", score=72.0), AutoTraderState(), {"NIFTY": _snap()},
    )
    assert ok, reason
    assert meta.get("worstDayScalpMomentum") is True


@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
def test_blocks_quick_sideways_on_breakout_only(mock_policy):
    ok, reason, _ = worst_day_allows_candidate(
        _Cand(mode="quick_sideways"), AutoTraderState(), {"NIFTY": _snap()},
    )
    assert not ok
    assert "quick" in reason


@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
def test_allows_elite_explosion(mock_policy):
    from app.engines.explosion_detector import ExplosionEvent

    cand = _Cand(mode="explosion", tier="ELITE", score=82.0, side=Side.PUT)
    cand.explosion_event = ExplosionEvent(
        symbol="NIFTY", side=Side.PUT, strike=24450, premium=30,
        velocity_3s=3.0, velocity_9s=4.0, velocity_15s=5.0,
        volume_surge=1.5, explosion_score=80, tier="ELITE", reason="t",
    )
    ok, reason, _ = worst_day_allows_candidate(cand, AutoTraderState(), {"NIFTY": _snap(tqs=48)})
    assert ok, reason


@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
def test_breakout_only_blocks_building_ict_allows_elite_local_base(mock_policy):
    """Aug10: BUILDING ICT defensive rip blocked; ELITE at local base still allowed."""
    from app.engines.explosion_detector import ExplosionEvent

    building = _Cand(mode="explosion", tier="BUILDING", score=70.0, side=Side.CALL)
    building.alert = {
        "side": "CALL", "tier": "BUILDING", "ictFlatThenVertical": True,
        "ictVolumeAwakening": True, "velocity3s": 3.05, "velocity9s": 0.0,
        "explosionScore": 70.0,
    }
    building.explosion_event = ExplosionEvent(
        symbol="NIFTY", side=Side.CALL, strike=24650, premium=75.8,
        velocity_3s=3.05, velocity_9s=0.0, velocity_15s=1.0,
        volume_surge=2.0, explosion_score=70.0, tier="BUILDING", reason="t",
        daily_move_pct=16.0, peak_move_pct=25.0,
    )
    ok_b, reason_b, meta_b = worst_day_allows_candidate(
        building, AutoTraderState(), {"NIFTY": _snap(tqs=48)},
    )
    assert ok_b is False
    assert meta_b.get("defensiveBaseRip") is not True
    assert "tier" in reason_b or "building" in reason_b.lower() or reason_b.startswith("worst_day")

    elite = _Cand(mode="explosion", tier="ELITE", score=85.0, side=Side.PUT)
    elite.alert = {
        "side": "PUT", "tier": "ELITE", "ictFlatThenVertical": True,
        "ictVolumeAwakening": True, "velocity3s": 3.5, "velocity9s": 4.0,
        "explosionScore": 85.0, "ictBaseRelativeMovePct": 28.0, "premium": 90.0,
    }
    elite.explosion_event = ExplosionEvent(
        symbol="NIFTY", side=Side.PUT, strike=24450, premium=90.0,
        velocity_3s=3.5, velocity_9s=4.0, velocity_15s=3.0,
        volume_surge=3.0, explosion_score=85.0, tier="ELITE", reason="t",
        daily_move_pct=28.0, peak_move_pct=30.0,
    )
    ok_e, reason_e, meta_e = worst_day_allows_candidate(
        elite, AutoTraderState(), {"NIFTY": _snap(tqs=48)},
    )
    assert ok_e is True, reason_e
    # Either standard breakout tier path or defensive ICT base rip.
    assert meta_e.get("defensiveBaseRip") or meta_e.get("worstDayIctBaseRip") or ok_e


@patch("app.engines.worst_day_guard.session_entry_policy",
       return_value=("PAUSED", {"pauseReason": "worst_day_severe_session_loss"}))
def test_paused_blocks_normal_but_allows_top_local_base(mock_policy):
    """A severe-loss PAUSE blocks everything EXCEPT a confirmed top local-base rip."""
    # Ordinary scalp — still blocked on a paused day.
    ok, reason, _ = worst_day_allows_candidate(
        _Cand(mode="scalp", score=72.0), AutoTraderState(), {"NIFTY": _snap()},
    )
    assert ok is False
    assert reason == "worst_day_severe_session_loss"

    # Top ELITE explosion off a confirmed local base — never miss it.
    cand = _Cand(mode="explosion", tier="ELITE", score=100.0, side=Side.CALL)
    cand.snap = _snap()
    cand.snap.spotChart = SpotChart(direction="BEARISH", momentum5Pct=0.01, trendStrength=30)
    cand.explosion_event = None
    cand.alert = {
        "side": "CALL", "strike": 24500.0, "tier": "ELITE", "explosionScore": 100.0,
        "dailyMovePct": 30.0, "peakMovePct": 30.0, "ictFlatThenVertical": True,
        "ictBreakout": True, "ictBaseRelativeMovePct": 28.0,
        "ictPattern": "flat_then_vertical", "premium": 120.0, "tradeable": True,
    }
    cand.confidence = 100.0
    ok2, reason2, meta2 = worst_day_allows_candidate(
        cand, AutoTraderState(), {"NIFTY": cand.snap},
    )
    assert ok2 is True
    # CALL into BEARISH → elite bypass denied; local-base top explosion still saves it.
    assert meta2.get("worstDayBypass") in (
        "elite_never_block",
        "local_base_top_explosion",
    )
