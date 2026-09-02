"""Aug10 regression: block fake BUILDING ICT; ELITE takes at local-base pad."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_entry_guards import explosion_entry_window_blocked
from app.engines.explosion_detector import ExplosionEvent
from app.engines.worst_day_guard import worst_day_allows_candidate
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


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24650.0,
        atmStrike=24650.0,
        regime=Regime.CHOP,
        tradeQualityScore=48.0,
        breadth=Breadth(bias="BULLISH", score=55, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.04, trendStrength=40),
    )


class _Cand:
    def __init__(self, *, tier: str, score: float, side: Side = Side.CALL):
        self.mode = "explosion"
        self.tier = tier
        self.score = score
        self.symbol = "NIFTY"
        self.side = side
        self.strike = 24650.0
        self.premium = 75.8
        self.snap = _snap()
        self.confidence = score
        self.alert = {}
        self.explosion_event = None


@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
def test_aug10_building_ce_blocked_on_breakout_only(mock_policy):
    """Live Aug10 NIFTY 24650 CE — BUILDING ICT mid-pad, cold v9 → blocked."""
    cand = _Cand(tier="BUILDING", score=70.0, side=Side.CALL)
    cand.alert = {
        "side": "CALL",
        "tier": "BUILDING",
        "ictFlatThenVertical": True,
        "ictVolumeAwakening": True,
        "velocity3s": 3.05,
        "velocity9s": 0.0,
        "explosionScore": 70.0,
        "dailyMovePct": 16.0,
        "peakMovePct": 25.0,
    }
    cand.explosion_event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24650.0,
        premium=75.8,
        velocity_3s=3.05,
        velocity_9s=0.0,
        velocity_15s=1.0,
        volume_surge=2.0,
        explosion_score=70.0,
        tier="BUILDING",
        reason="defensive_base_flat_vertical",
        daily_move_pct=16.0,
        peak_move_pct=25.0,
    )
    ok, reason, meta = worst_day_allows_candidate(
        cand, AutoTraderState(), {"NIFTY": cand.snap},
    )
    assert ok is False
    assert meta.get("defensiveBaseRip") is not True
    assert "building" in reason


def test_building_aligned_fail_closed_no_state():
    """No state + BREAKOUT_ONLY snap path must still block BUILDING."""
    from app.engines.trade_selector import _building_aligned_ict_alert_ok

    alert = {
        "side": "CALL",
        "tier": "BUILDING",
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictScore": 40.0,
        "explosionScore": 70.0,
        "velocity3s": 3.2,
        "velocity9s": 3.0,
        "ictVolumeAwakening": True,
    }
    with (
        patch(
            "app.engines.worst_day_itm_fade.worst_day_defensive_session_active",
            return_value=True,
        ),
        patch(
            "app.engines.worst_day_guard.session_entry_policy",
            return_value=("BREAKOUT_ONLY", {}),
        ),
    ):
        assert _building_aligned_ict_alert_ok(alert, _snap(), "BUILDING") is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_elite_entry_window_prefers_local_base_pad(mock_settings):
    """Non-must-take ELITE capped at elite_local_base_max_move_pct (40)."""
    s = MagicMock()
    s.explosion_entry_window_hard_enabled = True
    s.explosion_early_window_min_move_pct = 28.0
    s.explosion_early_window_max_move_pct = 65.0
    s.ict_structured_early_min_move_pct = 15.0
    s.ict_structured_early_max_move_pct = 65.0
    s.elite_local_base_max_move_pct = 40.0
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_trust_min_move_pct = 8.0
    s.explosion_local_base_recent_window_enabled = False
    s.session_move_max_credible_pct = 500.0
    s.eod_learning_apply_enabled = False
    mock_settings.return_value = s

    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24500.0,
        premium=100.0,
        velocity_3s=3.5,
        velocity_9s=4.0,
        velocity_15s=3.0,
        volume_surge=3.0,
        explosion_score=85.0,
        tier="ELITE",
        reason="t",
        daily_move_pct=50.0,
        peak_move_pct=52.0,
    )
    ict = MagicMock()
    ict.base_relative_move_pct = 48.0
    ict.session_move_pct = 50.0
    ict.flat_then_vertical = True
    ict.volume_awakening = True
    ict.displacement = True
    ict.premium_fvg = False
    ict.active = True

    blocked, reason = explosion_entry_window_blocked(
        event, ict=ict, top_must_take=False,
    )
    assert blocked is True
    assert "local_high" in reason or "high" in reason

    # Same pad under must-take — still inside structured 15–65%.
    blocked2, _ = explosion_entry_window_blocked(
        event, ict=ict, top_must_take=True,
    )
    assert blocked2 is False

    # Early local-base ELITE (28%) — allowed without must-take.
    ict.base_relative_move_pct = 28.0
    ict.session_move_pct = 28.0
    event.daily_move_pct = 28.0
    event.peak_move_pct = 30.0
    blocked3, _ = explosion_entry_window_blocked(
        event, ict=ict, top_must_take=False,
    )
    assert blocked3 is False
