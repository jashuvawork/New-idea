"""Session side-regime & flip detector — confirm the market side and flip only on sustained turns."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.side_regime import (
    observe_side_regime,
    reset_side_regime_for_tests,
    session_trade_side,
    side_regime_rank_delta,
    side_regime_state,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _settings(**over):
    s = SimpleNamespace(
        side_regime_enabled=True,
        side_regime_influences_ranking=True,
        side_regime_min_chart_mom5_pct=0.05,
        side_regime_min_vote_confidence=2,
        side_regime_flip_min_confirms=3,
        side_regime_flip_min_seconds=20.0,
        side_regime_rank_bonus=15.0,
        side_regime_counter_penalty=15.0,
        side_regime_flip_target_bonus=6.0,
        # best_side_selection thresholds (used by side_velocity_metrics)
        best_side_selection_enabled=True,
        best_side_min_velocity_3s=2.0,
        best_side_min_velocity_ratio=1.4,
        best_side_min_explosion_score=45.0,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _snap(direction, mom5, dominant_side, *, symbol="NIFTY"):
    """Build a snapshot whose chart + dominant option leg point a given way."""
    chart = SimpleNamespace(direction=direction, momentum5Pct=mom5)
    alerts = []
    if dominant_side:
        alerts.append({"side": dominant_side, "velocity3s": 3.0, "explosionScore": 90.0})
        other = "PUT" if dominant_side == "CALL" else "CALL"
        alerts.append({"side": other, "velocity3s": 0.2, "explosionScore": 20.0})
    return SimpleNamespace(
        symbol=symbol,
        dataAvailable=True,
        spotChart=chart,
        explosionAlerts=alerts,
        explosiveRunnerWatchlist=[],
        topExplosion={},
        explosiveRunner=None,
    )


def _no_drift(*_a, **_k):
    return {"drift": False}


def test_seeds_regime_from_confident_vote():
    reset_side_regime_for_tests()
    with (
        patch("app.engines.side_regime.get_settings", return_value=_settings()),
        patch("app.engines.best_side_selection.get_settings", return_value=_settings()),
        patch("app.engines.index_tick_helpers.recent_index_drift", _no_drift),
    ):
        out = observe_side_regime("NIFTY", _snap("BEARISH", -0.20, "PUT"),
                                  now=datetime(2026, 8, 31, 10, 0, tzinfo=IST))
    assert out["side"] == "PUT"          # chart_bear + dominant_put => confidence 2
    assert session_trade_side("NIFTY") == "PUT"


def test_single_opposite_spike_does_not_flip():
    reset_side_regime_for_tests()
    t0 = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    with (
        patch("app.engines.side_regime.get_settings", return_value=_settings()),
        patch("app.engines.best_side_selection.get_settings", return_value=_settings()),
        patch("app.engines.index_tick_helpers.recent_index_drift", _no_drift),
    ):
        observe_side_regime("NIFTY", _snap("BEARISH", -0.20, "PUT"), now=t0)
        # One confident CALL spike — must NOT flip (needs sustained confirmation).
        out = observe_side_regime("NIFTY", _snap("BULLISH", 0.20, "CALL"),
                                  now=t0 + timedelta(seconds=3))
    assert out["side"] == "PUT"
    assert out["flipping"] is True
    assert out["flipTarget"] == "CALL"
    assert out["pendingCount"] == 1


def test_sustained_turn_flips_bear_to_bull():
    reset_side_regime_for_tests()
    t0 = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    with (
        patch("app.engines.side_regime.get_settings", return_value=_settings()),
        patch("app.engines.best_side_selection.get_settings", return_value=_settings()),
        patch("app.engines.index_tick_helpers.recent_index_drift", _no_drift),
    ):
        observe_side_regime("NIFTY", _snap("BEARISH", -0.20, "PUT"), now=t0)
        # >=3 confident CALL votes AND pending span >= 20s => confirmed flip.
        observe_side_regime("NIFTY", _snap("BULLISH", 0.20, "CALL"), now=t0 + timedelta(seconds=10))
        observe_side_regime("NIFTY", _snap("BULLISH", 0.20, "CALL"), now=t0 + timedelta(seconds=25))
        out = observe_side_regime("NIFTY", _snap("BULLISH", 0.20, "CALL"), now=t0 + timedelta(seconds=35))
    assert out["side"] == "CALL"
    assert out["justFlipped"] is True
    assert session_trade_side("NIFTY") == "CALL"


def test_flip_resets_if_turn_not_sustained():
    reset_side_regime_for_tests()
    t0 = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    with (
        patch("app.engines.side_regime.get_settings", return_value=_settings()),
        patch("app.engines.best_side_selection.get_settings", return_value=_settings()),
        patch("app.engines.index_tick_helpers.recent_index_drift", _no_drift),
    ):
        observe_side_regime("NIFTY", _snap("BEARISH", -0.20, "PUT"), now=t0)
        observe_side_regime("NIFTY", _snap("BULLISH", 0.20, "CALL"), now=t0 + timedelta(seconds=5))
        # Reverts to the regime side before the flip confirms → pending cleared.
        out = observe_side_regime("NIFTY", _snap("BEARISH", -0.20, "PUT"), now=t0 + timedelta(seconds=8))
    assert out["side"] == "PUT"
    assert out["flipping"] is False
    assert out["pendingCount"] == 0


def test_rank_delta_prefers_regime_and_helps_flip_target():
    reset_side_regime_for_tests()
    t0 = datetime(2026, 8, 31, 10, 0, tzinfo=IST)
    with (
        patch("app.engines.side_regime.get_settings", return_value=_settings()),
        patch("app.engines.best_side_selection.get_settings", return_value=_settings()),
        patch("app.engines.index_tick_helpers.recent_index_drift", _no_drift),
    ):
        observe_side_regime("NIFTY", _snap("BEARISH", -0.20, "PUT"), now=t0)
        # Confirmed PUT regime, no pending flip yet.
        assert side_regime_rank_delta("NIFTY", Side.PUT) == 15.0
        assert side_regime_rank_delta("NIFTY", Side.CALL) == -15.0
        # Start a pending flip toward CALL — CALL should now be helped, not penalized.
        observe_side_regime("NIFTY", _snap("BULLISH", 0.20, "CALL"), now=t0 + timedelta(seconds=5))
        assert side_regime_rank_delta("NIFTY", Side.CALL) == 6.0
        assert side_regime_rank_delta("NIFTY", Side.PUT) == 15.0


def test_neutral_when_signals_conflict():
    reset_side_regime_for_tests()
    with (
        patch("app.engines.side_regime.get_settings", return_value=_settings()),
        patch("app.engines.best_side_selection.get_settings", return_value=_settings()),
        patch("app.engines.index_tick_helpers.recent_index_drift", _no_drift),
    ):
        # Chart bullish but dominant leg PUT → 1 vs 1 → NEUTRAL, no regime seeded.
        out = observe_side_regime("NIFTY", _snap("BULLISH", 0.20, "PUT"),
                                  now=datetime(2026, 8, 31, 10, 0, tzinfo=IST))
    assert out["side"] == "NEUTRAL"
    assert side_regime_rank_delta("NIFTY", Side.CALL) == 0.0


def test_disabled_returns_neutral_and_zero_delta():
    reset_side_regime_for_tests()
    s = _settings(side_regime_enabled=False)
    with patch("app.engines.side_regime.get_settings", return_value=s):
        out = observe_side_regime("NIFTY", _snap("BEARISH", -0.2, "PUT"),
                                  now=datetime(2026, 8, 31, 10, 0, tzinfo=IST))
        assert out["side"] == "NEUTRAL"
        assert side_regime_rank_delta("NIFTY", Side.PUT) == 0.0
